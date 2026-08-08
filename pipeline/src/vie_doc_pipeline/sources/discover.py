"""Discover external source records and record source assets."""

from itertools import islice
from pathlib import PurePosixPath
import urllib.parse
from dataclasses import dataclass, field

from vie_doc_pipeline.common.assets import PdfAsset, SourceAsset, ImageAsset
from vie_doc_pipeline.common.config import PipelineConfig
from vie_doc_pipeline.sources.models import DiscoveredSourceItem
from vie_doc_pipeline.sources.factory import open_source_item_provider
from vie_doc_pipeline.ledger.events import source_discovered
from vie_doc_pipeline.state import PipelineState


@dataclass(frozen=True)
class SourceItemAssetMapper:
    """Map typed source-provider records using one run's configuration."""

    config: PipelineConfig

    def to_asset(self, item: DiscoveredSourceItem) -> SourceAsset:
        """Convert one source-provider record into a durable asset identity."""
        if item.kind == "image":
            if not item.issue_id or not item.page_id:
                raise ValueError(f"Image source item is missing issue/page identity: {item.source_url}")
            return ImageAsset(
                publication_id=self.config.publication.id,
                issue_id=item.issue_id,
                page_id=item.page_id,
                source_url=item.source_url,
                target_path=f"{self.config.target.images_prefix}/{item.issue_label or item.issue_id}/{item.page_id}.jpg",
                width=item.width,
                height=item.height,
                issue_label=item.issue_label,
            )
        filename = PurePosixPath(urllib.parse.urlsplit(item.source_url).path).name or PurePosixPath(item.source_url).name
        document_id = urllib.parse.unquote(filename).removesuffix(".pdf")
        return PdfAsset(
            publication_id=self.config.publication.id,
            document_id=document_id,
            source_url=item.source_url,
            target_path=f"{self.config.target.pdf_prefix}/{filename}",
        )


@dataclass(frozen=True)
class SourceAssetDiscoveryService:
    """Discover source records and persist new source assets."""

    state: PipelineState
    _mapper: SourceItemAssetMapper = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_mapper", SourceItemAssetMapper(self.state.configuration))

    def execute(self, max_items: int | None = None) -> list[SourceAsset]:
        """Discover external source records that are not already recorded."""
        config = self.state.configuration
        with open_source_item_provider(config) as source_item_provider:
            known_asset_keys = set(self.state.asset_keys())
            new_assets: list[SourceAsset] = []
            for item in islice(source_item_provider.iter_source_items(), max_items):
                asset = self._mapper.to_asset(item)
                if asset.key not in known_asset_keys:
                    self.state.record(source_discovered(asset))
                    known_asset_keys.add(asset.key)
                    new_assets.append(asset)
            return new_assets
