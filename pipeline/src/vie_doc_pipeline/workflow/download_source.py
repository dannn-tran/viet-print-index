"""Download discovered original source assets into GCS."""

from __future__ import annotations

import hashlib
import logging

from google.cloud import storage

from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.sources.http import fetch_bytes, rate_limited
from vie_doc_pipeline.state import JsonlStateStore
from vie_doc_pipeline.workflow.assets import SourceAsset, asset_from_state

logger = logging.getLogger(__name__)


def download_source_assets(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> tuple[int, int]:
    """Download discovered source assets, resuming from the ledger."""
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)
    current = state.current()
    assets = [asset_from_state(raw) for raw in current.values() if raw.get("event") == "discovered" and "asset" in raw]
    if limit is not None:
        assets = assets[:limit]

    downloaded = 0
    existing = 0
    fetch = rate_limited(fetch_bytes, config.source.delay_seconds) if config.source.type == "veridian" else fetch_bytes
    for asset in assets:
        blob = bucket.blob(asset.object_name)
        if blob.exists(client):
            blob.reload(client)
            state.record_fetched(asset, checksum=blob.md5_hash or "unknown", size_bytes=blob.size or 0)
            existing += 1
            continue
        try:
            data = fetch(asset.source_url)
            blob.upload_from_string(data, content_type=_content_type(asset), timeout=600)
            state.record_fetched(asset, checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
            downloaded += 1
            print(f"Downloaded: {asset.object_name}")
        except Exception as error:
            state.record_failure(asset.key, stage="download", error=str(error))
            logger.exception("Failed to download %s", asset.key)
    return downloaded, existing


def _content_type(asset: SourceAsset) -> str:
    return "application/pdf" if asset.kind == "pdf" else "image/jpeg"
