"""Download discovered original source assets into GCS."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from google.cloud import storage
from google.api_core import exceptions as google_exceptions

from vie_doc_pipeline.ledger.events import failed, source_downloaded
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.locking import acquisition_lock
from vie_doc_pipeline.ledger.projection import eligible_source_assets, load_current
from vie_doc_pipeline.config.models import PipelineConfig
from vie_doc_pipeline.sources.http import HttpClient, SourceHttpError, TransientSourceError, http_client
from vie_doc_pipeline.domain.assets import SourceAsset
from vie_doc_pipeline.domain.results import DownloadSummary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Downloaded:
    asset: SourceAsset


@dataclass(frozen=True)
class AlreadyDownloaded:
    asset: SourceAsset


@dataclass(frozen=True)
class DownloadFailed:
    asset: SourceAsset


DownloadOutcome = Downloaded | AlreadyDownloaded | DownloadFailed


@dataclass(frozen=True)
class DownloadContext:
    """External capabilities and policy fixed for one download-stage run."""

    bucket: storage.Bucket
    storage_client: storage.Client
    http: HttpClient
    ledger_path: Path
    retry_delay: float

    def download(self, asset: SourceAsset) -> DownloadOutcome:
        """Store one asset and persist its outcome in this stage session."""
        try:
            blob = self.bucket.blob(asset.gcs_object)
            if blob.exists(self.storage_client):
                blob.reload(self.storage_client)
                append_event(self.ledger_path, source_downloaded(asset, checksum=blob.md5_hash or "unknown", size_bytes=blob.size or 0))
                return AlreadyDownloaded(asset)
            data = self.http.fetch_bytes(asset.source_url)
            blob.upload_from_string(data, content_type=_content_type(asset), timeout=600)
            append_event(self.ledger_path, source_downloaded(asset, checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))
            return Downloaded(asset)
        except (SourceHttpError, TransientSourceError, google_exceptions.GoogleAPIError, OSError) as error:
            record_download_failure(self.ledger_path, asset, error, self.retry_delay)
            return DownloadFailed(asset)


def download_source_assets(config: PipelineConfig, ledger_path: Path, limit: int | None = None) -> DownloadSummary:
    """Download discovered source assets, resuming from the ledger."""
    with acquisition_lock(ledger_path):
        storage_client = storage.Client(project=config.gcs.project)
        try:
            bucket = storage_client.bucket(config.gcs.bucket)
            assets = iter_download_candidates(ledger_path, limit)
            client = http_client(config.acquisition)
            try:
                context = DownloadContext(
                    bucket=bucket,
                    storage_client=storage_client,
                    http=client,
                    ledger_path=ledger_path,
                    retry_delay=config.acquisition.backoff_max_seconds,
                )
                outcomes = run_downloads(context, assets, config.acquisition.max_workers)
                return summarize_downloads(outcomes)
            finally:
                client.close()
        finally:
            storage_client.close()


def iter_download_candidates(ledger_path: Path, limit: int | None) -> Iterator[SourceAsset]:
    """Yield source assets that the ledger says are eligible for another attempt."""
    current = load_current(ledger_path)
    assets = (state.asset for state in eligible_source_assets(current) if state.asset is not None)
    yield from islice(assets, limit)


def run_downloads(
    context: DownloadContext,
    assets: Iterable[SourceAsset],
    max_workers: int,
) -> Iterator[DownloadOutcome]:
    """Apply one download function concurrently while retaining input ordering."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        yield from executor.map(context.download, assets)


def record_download_failure(ledger_path: Path, asset: SourceAsset, error: Exception, retry_delay: float) -> None:
    """Persist retry metadata for one failed source acquisition."""
    retryable, attempts = _failure_details(error)
    append_event(
        ledger_path,
        failed(
            asset.key,
            stage="download",
            error=str(error),
            retryable=retryable,
            attempts=attempts,
            retry_not_before=time.time() + retry_delay if retryable else None,
        ),
    )
    logger.warning("Failed to download %s: %s", asset.key, error)


def summarize_downloads(outcomes: Iterable[DownloadOutcome]) -> DownloadSummary:
    """Reduce individual download outcomes into a typed stage summary."""
    downloaded = 0
    already_present = 0
    failed = 0
    for outcome in outcomes:
        match outcome:
            case Downloaded():
                downloaded += 1
            case AlreadyDownloaded():
                already_present += 1
            case DownloadFailed():
                failed += 1
    return DownloadSummary(downloaded, already_present, failed)


def _content_type(asset: SourceAsset) -> str:
    return "application/pdf" if asset.kind == "pdf" else "image/jpeg"


def _failure_details(error: Exception) -> tuple[bool, int]:
    if isinstance(error, SourceHttpError):
        return False, 1
    if isinstance(error, TransientSourceError):
        return True, error.attempts
    if isinstance(
        error,
        (
            google_exceptions.DeadlineExceeded,
            google_exceptions.GatewayTimeout,
            google_exceptions.InternalServerError,
            google_exceptions.ServiceUnavailable,
            google_exceptions.TooManyRequests,
        ),
    ):
        return True, 1
    return False, 1
