"""Discover external source records and record source assets."""

from pathlib import Path

from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.sources import discover_source_items
from vie_doc_pipeline.ledger.events import source_discovered
from vie_doc_pipeline.ledger.projection import load_current
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.workflow.assets import SourceAsset, asset_from_source_item


def discover_source_assets(
    config: PipelineConfig, ledger_path: Path, limit: int | None = None
) -> list[SourceAsset]:
    """Discover external source records that are not already in the ledger."""
    assets = [asset_from_source_item(config, item) for item in discover_source_items(config.source, limit)]
    current = load_current(ledger_path)
    new_assets = [asset for asset in assets if asset.key not in current]
    for asset in new_assets:
        append_event(ledger_path, source_discovered(asset))
    return new_assets
