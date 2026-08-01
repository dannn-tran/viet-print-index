"""Create or designate image assets for presentation and OCR."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from google.cloud import storage

from vie_doc_pipeline.explode_mem import explode_pdf_bytes
from vie_doc_pipeline.models import DocumentAsset, PageAsset
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.state import JsonlStateStore
from vie_doc_pipeline.workflow.assets import asset_from_state

logger = logging.getLogger(__name__)


def normalize_images(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> tuple[int, int]:
    """Create image assets from PDFs or designate native images without copying."""
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)
    current = state.current()
    assets = [asset_from_state(raw) for raw in current.values() if raw.get("event") == "fetched" and "asset" in raw]
    if limit is not None:
        assets = assets[:limit]

    created = 0
    passthrough = 0
    for asset in assets:
        if isinstance(asset, PageAsset):
            state.record_materialized(asset)
            passthrough += 1
            continue
        try:
            pdf_bytes = bucket.blob(asset.object_name).download_as_bytes(timeout=600)
            for filename, image_bytes in explode_pdf_bytes(pdf_bytes, config.explode):
                image = PageAsset(
                    publication_id=asset.publication_id,
                    issue_id=asset.document_id,
                    page_id=PurePosixPath(filename).stem,
                    source_url=asset.source_url,
                    object_name=f"{config.gcs.images_prefix}/{asset.document_id}/{filename}",
                )
                blob = bucket.blob(image.object_name)
                if not blob.exists(client):
                    blob.upload_from_string(image_bytes, content_type=_image_content_type(filename), timeout=600)
                state.record_materialized(image)
                created += 1
            state.record_materialized(asset)
        except Exception as error:
            state.record_failure(asset.key, stage="normalize", error=str(error))
            logger.exception("Failed to normalize %s", asset.key)
    return created, passthrough


def _image_content_type(filename: str) -> str:
    return "image/png" if filename.endswith(".png") else "image/jpeg"
