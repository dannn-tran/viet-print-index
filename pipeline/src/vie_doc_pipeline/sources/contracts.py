"""Source discovery contract and its returned record."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from vie_doc_pipeline.assets import AssetKind


@dataclass(frozen=True)
class DiscoveredSourceItem:
    """One source document or native image returned by a provider."""

    kind: AssetKind
    source_url: str
    issue_id: str | None = None
    issue_label: str | None = None
    page_id: str | None = None
    width: int | None = None
    height: int | None = None


class SourceItemProvider(ABC):
    """One source-specific enumeration session."""

    @abstractmethod
    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        """Yield this session's source items."""

    @abstractmethod
    def close(self) -> None:
        """Release resources owned by this session."""
