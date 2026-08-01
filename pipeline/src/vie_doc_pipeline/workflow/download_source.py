"""Download discovered original source assets into the configured target."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from google.api_core import exceptions as google_exceptions

from vie_doc_pipeline.ledger.events import failed, source_downloaded
from vie_doc_pipeline.ledger.jsonl import append_event, ensure_ledger_config
from vie_doc_pipeline.ledger.locking import source_download_lock
from vie_doc_pipeline.ledger.projection import CurrentState, eligible_source_assets, load_current
from vie_doc_pipeline.config import PipelineConfig
from vie_doc_pipeline.sources.http import HttpClient, SourceHttpError, TransientSourceError, http_client
from vie_doc_pipeline.assets import SourceAsset
from vie_doc_pipeline.storage import TargetStore, open_target_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadSummary:
    downloaded: int = 0
    already_present: int = 0
    failed: int = 0


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

    store: TargetStore
    http: HttpClient
    ledger_path: Path
    retry_delay: float

    def download(self, asset: SourceAsset) -> DownloadOutcome:
        """Store one asset and persist its outcome in this stage session."""
        try:
            existing = self.store.inspect(asset.target_path)
            if existing is not None:
                append_event(self.ledger_path, source_downloaded(asset, checksum=existing.checksum, size_bytes=existing.size_bytes))
                return AlreadyDownloaded(asset)
            data = self.http.fetch_bytes(asset.source_url)
            self.store.write_bytes(asset.target_path, data, content_type=_content_type(asset))
            append_event(self.ledger_path, source_downloaded(asset, checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))
            return Downloaded(asset)
        except (SourceHttpError, TransientSourceError, google_exceptions.GoogleAPIError, OSError) as error:
            self.record_failure(asset, error)
            return DownloadFailed(asset)

    def record_failure(self, asset: SourceAsset, error: Exception) -> None:
        """Persist retry metadata for one failed source download."""
        retryable, attempts = _failure_details(error)
        append_event(
            self.ledger_path,
            failed(
                asset.key,
                stage="download",
                error=str(error),
                retryable=retryable,
                attempts=attempts,
                retry_not_before=time.time() + self.retry_delay if retryable else None,
            ),
        )
        logger.warning("Failed to download %s: %s", asset.key, error)


def download_source_assets(config: PipelineConfig, ledger_path: Path, limit: int | None = None) -> DownloadSummary:
    """Download discovered source assets, resuming from the ledger."""
    with source_download_lock(ledger_path):
        ensure_ledger_config(ledger_path, config.config_sha256)
        with open_target_store(config.target) as store:
            current = load_current(ledger_path, config.config_sha256)
            assets = iter_download_candidates(current, limit)
            client = http_client(config.source_requests)
            try:
                context = DownloadContext(
                    store=store,
                    http=client,
                    ledger_path=ledger_path,
                    retry_delay=config.source_requests.backoff_max_seconds,
                )
                outcomes = run_downloads(context, assets, config.source_requests.max_concurrent_requests)
                return summarize_downloads(outcomes)
            finally:
                client.close()


def iter_download_candidates(
    current: CurrentState,
    limit: int | None,
) -> Iterator[SourceAsset]:
    """Yield source assets eligible for another download attempt."""
    assets = (state.asset for state in eligible_source_assets(current) if state.asset is not None)
    yield from islice(assets, limit)


def run_downloads(
    context: DownloadContext,
    assets: Iterable[SourceAsset],
    max_concurrent_requests: int,
) -> Iterator[DownloadOutcome]:
    """Apply one download function concurrently while retaining input ordering."""
    with ThreadPoolExecutor(max_workers=max_concurrent_requests) as executor:
        yield from executor.map(context.download, assets)


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
