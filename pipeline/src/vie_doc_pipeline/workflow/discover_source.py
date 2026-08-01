"""Discover external source records and record source assets."""

from itertools import islice
from pathlib import Path
from pathlib import PurePosixPath
import urllib.parse

from vie_doc_pipeline.assets import PdfAsset, SourceAsset, ImageAsset
from vie_doc_pipeline.config import PipelineConfig
from vie_doc_pipeline.sources.contracts import DiscoveredSourceItem
from vie_doc_pipeline.sources.factory import open_source_items
from vie_doc_pipeline.ledger.events import source_discovered
from vie_doc_pipeline.ledger.jsonl import ensure_ledger_config
from vie_doc_pipeline.ledger.projection import AppState
from vie_doc_pipeline.ledger.store import EventStore


def asset_from_source_item(config: PipelineConfig, item: DiscoveredSourceItem) -> SourceAsset:
    """Convert one source-provider record into a durable asset identity."""
    if item.kind == "image":
        if not item.issue_id or not item.page_id:
            raise ValueError(f"Image source item is missing issue/page identity: {item.source_url}")
        return ImageAsset(
            publication_id=config.publication.id,
            issue_id=item.issue_id,
            page_id=item.page_id,
            source_url=item.source_url,
            target_path=f"{config.target.images_prefix}/{item.issue_label or item.issue_id}/{item.page_id}.jpg",
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
        target_path=f"{config.target.pdf_prefix}/{filename}",
    )


def discover_source_assets(
    config: PipelineConfig, ledger_path: Path, limit: int | None = None
) -> list[SourceAsset]:
    """Discover external source records that are not already in the ledger."""
    ensure_ledger_config(ledger_path, config.config_sha256)
    state = AppState.replay(EventStore.open(ledger_path))
    with open_source_items(config) as source_items:
        known_asset_keys = set(state.current)
        new_assets: list[SourceAsset] = []
        for item in islice(source_items.iter_source_items(), limit):
            asset = asset_from_source_item(config, item)
            if asset.key not in known_asset_keys:
                state.record(source_discovered(asset))
                known_asset_keys.add(asset.key)
                new_assets.append(asset)
        return new_assets
