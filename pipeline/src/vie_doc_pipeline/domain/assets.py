"""Shared conversion helpers for source and image workflow stages."""

from __future__ import annotations

import urllib.parse
from pathlib import PurePosixPath

from vie_doc_pipeline.models import DiscoveredSourceItem, ImageAsset, PdfAsset, SourceAsset
from vie_doc_pipeline.config.models import PipelineConfig


def asset_from_source_item(config: PipelineConfig, item: DiscoveredSourceItem) -> SourceAsset:
    if item.kind == "image":
        if not item.issue_id or not item.page_id:
            raise ValueError(f"Image source item is missing issue/page identity: {item.source_url}")
        return ImageAsset(
            publication_id=config.publication.id,
            issue_id=item.issue_id,
            page_id=item.page_id,
            source_url=item.source_url,
            gcs_object=f"{config.gcs.images_prefix}/{item.issue_label or item.issue_id}/{item.page_id}.jpg",
            width=item.width,
            height=item.height,
            issue_label=item.issue_label,
        )
    filename = PurePosixPath(urllib.parse.urlsplit(item.source_url).path).name or PurePosixPath(item.source_url).name
    document_id = urllib.parse.unquote(filename).removesuffix(".pdf")
    return PdfAsset(
        publication_id=config.publication.id,
        document_id=document_id,
        source_url=item.source_url,
        gcs_object=f"{config.gcs.pdf_prefix}/{filename}",
    )
