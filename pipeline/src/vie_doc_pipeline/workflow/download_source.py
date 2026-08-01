"""Download discovered original source assets into GCS."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from itertools import islice
from pathlib import Path

from google.cloud import storage

from vie_doc_pipeline.ledger.events import failed, source_downloaded
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.locks import acquisition_lock
from vie_doc_pipeline.ledger.projection import eligible_source_assets, load_current
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.sources.http import HttpClient, SourceHttpError, TransientSourceError, http_client
from vie_doc_pipeline.workflow.assets import SourceAsset, asset_from_state

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


def download_source_assets(config: PipelineConfig, ledger_path: Path, limit: int | None = None) -> tuple[int, int]:
    """Download discovered source assets, resuming from the ledger."""
    with acquisition_lock(ledger_path):
        storage_client = storage.Client(project=config.gcs.project)
        bucket = storage_client.bucket(config.gcs.bucket)
        assets = iter_download_candidates(ledger_path, limit)
        client = http_client(config.acquisition)
        try:
            download = partial(
                download_one,
                bucket=bucket,
                storage_client=storage_client,
                client=client,
                ledger_path=ledger_path,
                retry_delay=config.acquisition.backoff_max_seconds,
            )
            outcomes = run_downloads(assets, config.acquisition.max_workers, download)
            return summarize_downloads(outcomes)
        finally:
            client.close()


def iter_download_candidates(ledger_path: Path, limit: int | None) -> Iterator[SourceAsset]:
    """Yield source assets that the ledger says are eligible for another attempt."""
    current = load_current(ledger_path)
    assets = map(asset_from_state, eligible_source_assets(current))
    yield from islice(assets, limit)


def run_downloads(
    assets: Iterable[SourceAsset],
    max_workers: int,
    download: Callable[[SourceAsset], DownloadOutcome],
) -> Iterator[DownloadOutcome]:
    """Apply one download function concurrently while retaining input ordering."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        yield from executor.map(download, assets)


def download_one(
    asset: SourceAsset,
    *,
    bucket: storage.Bucket,
    storage_client: storage.Client,
    client: HttpClient,
    ledger_path: Path,
    retry_delay: float,
) -> DownloadOutcome:
    """Store one source asset and immediately record its durable outcome."""
    try:
        blob = bucket.blob(asset.gcs_object)
        if blob.exists(storage_client):
            blob.reload(storage_client)
            append_event(ledger_path, source_downloaded(asset, checksum=blob.md5_hash or "unknown", size_bytes=blob.size or 0))
            return AlreadyDownloaded(asset)
        data = client.fetch_bytes(asset.source_url)
        blob.upload_from_string(data, content_type=_content_type(asset), timeout=600)
        append_event(ledger_path, source_downloaded(asset, checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))
        return Downloaded(asset)
    except Exception as error:
        record_download_failure(ledger_path, asset, error, retry_delay)
        return DownloadFailed(asset)


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
    logger.exception("Failed to download %s", asset.key)


def summarize_downloads(outcomes: Iterable[DownloadOutcome]) -> tuple[int, int]:
    """Print newly stored assets and return (new, already-present) counts."""
    downloaded = 0
    existing = 0
    for outcome in outcomes:
        match outcome:
            case Downloaded(asset):
                downloaded += 1
                print(f"Downloaded: {asset.gcs_object}")
            case AlreadyDownloaded():
                existing += 1
    return downloaded, existing


def _content_type(asset: SourceAsset) -> str:
    return "application/pdf" if asset.kind == "pdf" else "image/jpeg"


def _failure_details(error: Exception) -> tuple[bool, int]:
    if isinstance(error, SourceHttpError):
        return False, 1
    if isinstance(error, TransientSourceError):
        return True, error.attempts
    return True, 1
