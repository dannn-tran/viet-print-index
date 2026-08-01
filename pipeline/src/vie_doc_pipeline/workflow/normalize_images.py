"""Create or designate image assets for presentation and OCR."""

from __future__ import annotations

import logging
from pathlib import Path
from pathlib import PurePosixPath

from google.cloud import storage

from vie_doc_pipeline.explode_mem import explode_pdf_bytes
from vie_doc_pipeline.ledger.events import failed, image_normalized
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.projection import assets_at, load_current
from vie_doc_pipeline.models import ImageAsset
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.workflow.assets import asset_from_state
from vie_doc_pipeline.workflow.image_processing import check_inversion, invert_image

logger = logging.getLogger(__name__)


def normalize_images(
    config: PipelineConfig,
    ledger_path: Path,
    limit: int | None = None,
    source_id: str | None = None,
    image_key: str | None = None,
) -> tuple[int, int]:
    """Create image assets from PDFs or designate native images without copying."""
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)
    current = load_current(ledger_path)
    assets = [asset_from_state(raw) for raw in assets_at(current, "source_downloaded")]
    if source_id or image_key:
        assets = [
            asset_from_state(raw)
            for key, raw in current.items()
            if "asset" in raw and raw.get("event") in {"source_downloaded", "image_normalized"}
            and ((source_id is not None and _source_id(asset_from_state(raw)) == source_id) or key == image_key)
        ]
    if limit is not None:
        assets = assets[:limit]

    created = 0
    passthrough = 0
    for asset in assets:
        if isinstance(asset, ImageAsset):
            raw_bytes = bucket.blob(asset.gcs_object).download_as_bytes(timeout=600)
            image = _normalize_bytes(asset, raw_bytes, asset.gcs_object, _is_forced_inverted(ledger_path, asset))
            if image.gcs_object != asset.gcs_object:
                bucket.blob(image.gcs_object).upload_from_string(
                    invert_image(raw_bytes, asset.gcs_object), content_type=_image_content_type(image.gcs_object), timeout=600
                )
            append_event(ledger_path, image_normalized(image))
            passthrough += 1
            continue
        try:
            pdf_bytes = bucket.blob(asset.gcs_object).download_as_bytes(timeout=600)
            for filename, image_bytes in explode_pdf_bytes(pdf_bytes, config.explode):
                image = ImageAsset(
                    publication_id=asset.publication_id,
                    issue_id=asset.document_id,
                    page_id=PurePosixPath(filename).stem,
                    source_url=asset.source_url,
                    gcs_object=f"{config.gcs.images_prefix}/{asset.document_id}/{filename}",
                )
                image = _normalize_bytes(image, image_bytes, filename, _is_forced_inverted(ledger_path, image))
                blob = bucket.blob(image.gcs_object)
                if not blob.exists(client):
                    output = invert_image(image_bytes, filename) if image.inverted else image_bytes
                    blob.upload_from_string(output, content_type=_image_content_type(image.gcs_object), timeout=600)
                append_event(ledger_path, image_normalized(image))
                created += 1
            append_event(ledger_path, image_normalized(asset))
        except Exception as error:
            append_event(ledger_path, failed(asset.key, stage="normalize", error=str(error)))
            logger.exception("Failed to normalize %s", asset.key)
    return created, passthrough


def _image_content_type(filename: str) -> str:
    return "image/png" if filename.endswith(".png") else "image/jpeg"


def _source_id(asset: object) -> str:
    return asset.document_id if hasattr(asset, "document_id") else asset.issue_id  # type: ignore[union-attr]


def _is_forced_inverted(ledger_path: Path, asset: ImageAsset) -> bool:
    from vie_doc_pipeline.ledger.jsonl import read_events

    return any(
        event.event == "image_inverted" and event.asset_key == asset.key
        or event.event == "source_inverted" and event.asset_key == _source_id(asset)
        for event in read_events(ledger_path)
    )


def _normalize_bytes(asset: ImageAsset, data: bytes, filename: str, forced_inverted: bool) -> ImageAsset:
    check = check_inversion(data)
    inverted = forced_inverted or check.inverted
    if not inverted:
        return ImageAsset(**{**asset.to_dict(), "needs_review": check.needs_review})  # type: ignore[arg-type]
    suffix = PurePosixPath(filename).suffix
    stem = PurePosixPath(filename).stem
    return ImageAsset(
        publication_id=asset.publication_id,
        issue_id=asset.issue_id,
        page_id=f"{asset.page_id}-inverted",
        source_url=asset.source_url,
        gcs_object=str(PurePosixPath(asset.gcs_object).with_name(f"{stem}-inverted{suffix}")),
        width=asset.width,
        height=asset.height,
        inverted=True,
    )
