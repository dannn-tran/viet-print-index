"""Manifest-driven discovery and fetch stages for page assets."""

from __future__ import annotations

import hashlib
import logging

from google.cloud import storage

from vie_doc_pipeline.domain import PageAsset
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.state import JsonlStateStore
from vie_doc_pipeline.veridian import VeridianClient

logger = logging.getLogger(__name__)


def discover_assets(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> list[PageAsset]:
    """Discover every fetchable page asset and append it to the JSONL ledger."""
    if config.source.type != "veridian":
        raise ValueError(f"Asset discovery is not implemented for source type {config.source.type!r}")

    client = VeridianClient(config.source)
    assets: list[PageAsset] = []
    for issue in client.list_issues(limit=limit):
        for page in client.list_pages(issue):
            asset = PageAsset(
                publication_id=config.publication.id,
                issue_id=issue.oid,
                page_id=page.filename.removesuffix(".jpg"),
                source_url=client.page_image_url(page),
                object_name=f"{config.gcs.images_prefix}/{issue.oid}/{page.filename}",
                width=page.width,
                height=page.height,
            )
            state.record_discovered(asset)
            assets.append(asset)
    return assets


def fetch_assets(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> tuple[int, int]:
    """Fetch all discovered-but-unfetched assets into GCS.

    Existing objects are backfilled into state rather than redownloaded, making
    it safe to migrate a publication that used the earlier direct ingest path.
    """
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)
    current = state.current()
    assets = [
        PageAsset.from_dict(raw["asset"])
        for raw in current.values()
        if "asset" in raw and raw.get("event") == "discovered"
    ]
    if limit is not None:
        assets = assets[:limit]

    fetched = 0
    skipped = 0
    for asset in assets:
        blob = bucket.blob(asset.object_name)
        if blob.exists(client):
            blob.reload(client)
            state.record_fetched(asset, checksum=blob.md5_hash or "unknown", size_bytes=blob.size or 0)
            skipped += 1
            continue
        try:
            data = _fetch_asset_bytes(asset.source_url)
            checksum = hashlib.sha256(data).hexdigest()
            blob.upload_from_string(data, content_type="image/jpeg", timeout=600)
            state.record_fetched(asset, checksum=checksum, size_bytes=len(data))
            fetched += 1
            print(f"Fetched: {asset.issue_id}/{asset.page_id}.jpg")
        except Exception as error:
            state.record_failure(asset.key, stage="fetch", error=str(error))
            logger.exception("Failed to fetch %s", asset.key)
    return fetched, skipped


def _fetch_asset_bytes(url: str) -> bytes:
    # The source URL is already fully percent-encoded by VeridianClient.
    from vie_doc_pipeline.source_adapter import fetch_bytes

    return fetch_bytes(url)
