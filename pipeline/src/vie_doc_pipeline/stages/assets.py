"""Source-agnostic discovery, fetch, and page materialisation stages."""

from __future__ import annotations

import hashlib
import logging
import urllib.parse
from pathlib import PurePosixPath

from google.cloud import storage

from vie_doc_pipeline.models import DocumentAsset, PageAsset, SourceItem
from vie_doc_pipeline.explode_mem import explode_pdf_bytes
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.sources import discover_source_items
from vie_doc_pipeline.sources.http import fetch_bytes
from vie_doc_pipeline.state import JsonlStateStore

logger = logging.getLogger(__name__)

SourceAsset = DocumentAsset | PageAsset


def discover_assets(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> list[SourceAsset]:
    """Discover source documents or native page images into the JSONL ledger."""
    items = discover_source_items(config.source, limit)
    assets = [_asset_from_source_item(config, item) for item in items]

    current = state.current()
    new_assets = [asset for asset in assets if asset.key not in current]
    for asset in new_assets:
        state.record_discovered(asset)
    return new_assets


def fetch_assets(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> tuple[int, int]:
    """Fetch all discovered source assets into GCS, resuming from the ledger."""
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)
    current = state.current()
    assets = [_asset_from_state(raw) for raw in current.values() if raw.get("event") == "discovered" and "asset" in raw]
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
            data = fetch_bytes(asset.source_url)
            checksum = hashlib.sha256(data).hexdigest()
            blob.upload_from_string(data, content_type=_content_type(asset), timeout=600)
            state.record_fetched(asset, checksum=checksum, size_bytes=len(data))
            fetched += 1
            print(f"Fetched: {asset.object_name}")
        except Exception as error:
            state.record_failure(asset.key, stage="fetch", error=str(error))
            logger.exception("Failed to fetch %s", asset.key)
    return fetched, skipped


def materialize_pages(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> tuple[int, int]:
    """Turn fetched documents into OCR-ready page assets.

    Native image assets are materialised in place: this records the canonical
    image as a page without copying or re-uploading it. PDF assets are exploded
    into new objects under ``images_prefix``.
    """
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)
    current = state.current()
    assets = [_asset_from_state(raw) for raw in current.values() if raw.get("event") == "fetched" and "asset" in raw]
    if limit is not None:
        assets = assets[:limit]

    pages = 0
    passthrough = 0
    for asset in assets:
        if isinstance(asset, PageAsset):
            state.record_materialized(asset)
            passthrough += 1
            continue
        try:
            pdf_bytes = bucket.blob(asset.object_name).download_as_bytes(timeout=600)
            for filename, image_bytes in explode_pdf_bytes(pdf_bytes, config.explode):
                page = PageAsset(
                    publication_id=asset.publication_id,
                    issue_id=asset.document_id,
                    page_id=PurePosixPath(filename).stem,
                    source_url=asset.source_url,
                    object_name=f"{config.gcs.images_prefix}/{asset.document_id}/{filename}",
                )
                image_blob = bucket.blob(page.object_name)
                if not image_blob.exists(client):
                    image_blob.upload_from_string(image_bytes, content_type=_image_content_type(filename), timeout=600)
                state.record_materialized(page)
                pages += 1
            state.record_materialized(asset)
        except Exception as error:
            state.record_failure(asset.key, stage="materialize", error=str(error))
            logger.exception("Failed to materialize %s", asset.key)
    return pages, passthrough


def _asset_from_source_item(config: PipelineConfig, item: SourceItem) -> SourceAsset:
    if item.kind == "image":
        assert item.issue_id and item.page_id
        return PageAsset(
            publication_id=config.publication.id,
            issue_id=item.issue_id,
            page_id=item.page_id,
            source_url=item.source_url,
            object_name=f"{config.gcs.images_prefix}/{item.issue_id}/{item.page_id}.jpg",
            width=item.width,
            height=item.height,
        )
    return _document_from_url(config, item.source_url)


def _document_from_url(config: PipelineConfig, item: str) -> DocumentAsset:
    filename = PurePosixPath(urllib.parse.urlsplit(item).path).name or PurePosixPath(item).name
    document_id = urllib.parse.unquote(filename).removesuffix(".pdf")
    return DocumentAsset(
        publication_id=config.publication.id,
        document_id=document_id,
        source_url=item,
        object_name=f"{config.gcs.pdf_prefix}/{filename}",
    )


def _asset_from_state(raw: dict[str, object]) -> SourceAsset:
    asset = raw["asset"]
    assert isinstance(asset, dict)
    return DocumentAsset.from_dict(asset) if asset.get("kind") == "pdf" else PageAsset.from_dict(asset)


def _content_type(asset: SourceAsset) -> str:
    return "application/pdf" if isinstance(asset, DocumentAsset) else "image/jpeg"


def _image_content_type(filename: str) -> str:
    return "image/png" if filename.endswith(".png") else "image/jpeg"
