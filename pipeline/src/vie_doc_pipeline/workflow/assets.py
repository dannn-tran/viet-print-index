"""Shared conversion helpers for source and image workflow stages."""

from __future__ import annotations

import urllib.parse
from pathlib import PurePosixPath

from vie_doc_pipeline.models import DocumentAsset, PageAsset, SourceItem
from vie_doc_pipeline.pipeline_config import PipelineConfig

SourceAsset = DocumentAsset | PageAsset


def asset_from_source_item(config: PipelineConfig, item: SourceItem) -> SourceAsset:
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
    filename = PurePosixPath(urllib.parse.urlsplit(item.source_url).path).name or PurePosixPath(item.source_url).name
    document_id = urllib.parse.unquote(filename).removesuffix(".pdf")
    return DocumentAsset(
        publication_id=config.publication.id,
        document_id=document_id,
        source_url=item.source_url,
        object_name=f"{config.gcs.pdf_prefix}/{filename}",
    )


def asset_from_state(raw: dict[str, object]) -> SourceAsset:
    asset = raw["asset"]
    assert isinstance(asset, dict)
    return DocumentAsset.from_dict(asset) if asset.get("kind") == "pdf" else PageAsset.from_dict(asset)
