"""Download discovered original source assets into GCS."""

from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from google.cloud import storage

from vie_doc_pipeline.ledger.events import failed, source_downloaded
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.locks import acquisition_lock
from vie_doc_pipeline.ledger.projection import eligible_source_assets, load_current
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.sources.http import SourceHttpError, TransientSourceError, http_client
from vie_doc_pipeline.workflow.assets import SourceAsset, asset_from_state

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadOutcome:
    downloaded: bool
    existing: bool


def download_source_assets(config: PipelineConfig, ledger_path: Path, limit: int | None = None) -> tuple[int, int]:
    """Download discovered source assets, resuming from the ledger."""
    with acquisition_lock(ledger_path):
        storage_client = storage.Client(project=config.gcs.project)
        bucket = storage_client.bucket(config.gcs.bucket)
        assets = [asset_from_state(raw) for raw in eligible_source_assets(load_current(ledger_path))]
        if limit is not None:
            assets = assets[:limit]
        client = http_client(config.acquisition)
        try:
            def download_one(asset: SourceAsset) -> DownloadOutcome:
                try:
                    blob = bucket.blob(asset.gcs_object)
                    if blob.exists(storage_client):
                        blob.reload(storage_client)
                        append_event(ledger_path, source_downloaded(asset, checksum=blob.md5_hash or "unknown", size_bytes=blob.size or 0))
                        return DownloadOutcome(downloaded=False, existing=True)
                    data = client.fetch_bytes(asset.source_url)
                    blob.upload_from_string(data, content_type=_content_type(asset), timeout=600)
                    append_event(ledger_path, source_downloaded(asset, checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))
                    return DownloadOutcome(downloaded=True, existing=False)
                except Exception as error:
                    retryable, attempts = _failure_details(error)
                    append_event(
                        ledger_path,
                        failed(
                            asset.key,
                            stage="download",
                            error=str(error),
                            retryable=retryable,
                            attempts=attempts,
                            retry_not_before=time.time() + config.acquisition.backoff_max_seconds if retryable else None,
                        ),
                    )
                    logger.exception("Failed to download %s", asset.key)
                    return DownloadOutcome(downloaded=False, existing=False)

            downloaded = 0
            existing = 0
            with ThreadPoolExecutor(max_workers=config.acquisition.max_workers) as executor:
                futures = {executor.submit(download_one, asset): asset for asset in assets}
                for future in as_completed(futures):
                    outcome = future.result()
                    downloaded += outcome.downloaded
                    existing += outcome.existing
                    if outcome.downloaded:
                        print(f"Downloaded: {futures[future].gcs_object}")
            return downloaded, existing
        finally:
            client.close()


def _content_type(asset: SourceAsset) -> str:
    return "application/pdf" if asset.kind == "pdf" else "image/jpeg"


def _failure_details(error: Exception) -> tuple[bool, int]:
    if isinstance(error, SourceHttpError):
        return False, 1
    if isinstance(error, TransientSourceError):
        return True, error.attempts
    return True, 1
