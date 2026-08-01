"""Factory and unified interface for source-item enumeration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from vie_doc_pipeline.models import DiscoveredSourceItem
from vie_doc_pipeline.pipeline_config import (
    LocalPdfSource,
    PipelineConfig,
    UrlListPdfSource,
    UrlSequencePdfSource,
    VeridianSource,
    WebPagePdfSource,
)
from vie_doc_pipeline.sources.http import HttpClient, http_client
from vie_doc_pipeline.sources.pdf import (
    iter_source_items_from_local_directory,
    iter_source_items_from_url_list,
    iter_source_items_from_url_sequence,
    iter_source_items_from_web_page,
)
from vie_doc_pipeline.sources.veridian import iter_source_items_from_veridian


class SourceItemProvider(ABC):
    """One source-specific enumeration session."""

    @abstractmethod
    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        """Yield this session's source items."""

    @abstractmethod
    def close(self) -> None:
        """Release resources owned by this session."""


@dataclass(frozen=True)
class UrlSequenceSourceItemProvider(SourceItemProvider):
    source: UrlSequencePdfSource

    @classmethod
    def from_source(cls, source: UrlSequencePdfSource) -> "UrlSequenceSourceItemProvider":
        return cls(source)

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_url_sequence(
            self.source.base_url,
            self.source.pattern,
            self.source.issue_range,
            self.source.extra_urls,
        )

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class UrlListSourceItemProvider(SourceItemProvider):
    source: UrlListPdfSource

    @classmethod
    def from_source(cls, source: UrlListPdfSource) -> "UrlListSourceItemProvider":
        return cls(source)

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_url_list(self.source.urls)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class LocalDirectorySourceItemProvider(SourceItemProvider):
    source: LocalPdfSource

    @classmethod
    def from_source(cls, source: LocalPdfSource) -> "LocalDirectorySourceItemProvider":
        return cls(source)

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_local_directory(self.source.path)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class VeridianSourceItemProvider(SourceItemProvider):
    source: VeridianSource
    http: HttpClient

    @classmethod
    def open(cls, source: VeridianSource, config: PipelineConfig) -> "VeridianSourceItemProvider":
        return cls(source, http_client(config.acquisition))

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_veridian(self.source, self.http)

    def close(self) -> None:
        self.http.close()


@dataclass(frozen=True)
class WebPageSourceItemProvider(SourceItemProvider):
    source: WebPagePdfSource
    http: HttpClient

    @classmethod
    def open(cls, source: WebPagePdfSource, config: PipelineConfig) -> "WebPageSourceItemProvider":
        return cls(source, http_client(config.acquisition))

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_web_page(
            self.source.page_url,
            self.http.fetch_text(self.source.page_url),
        )

    def close(self) -> None:
        self.http.close()


@contextmanager
def open_source_items(config: PipelineConfig) -> Iterator[SourceItemProvider]:
    """Open exactly the resources required to enumerate one configured source."""
    provider = source_item_provider(config)
    try:
        yield provider
    finally:
        provider.close()


def source_item_provider(config: PipelineConfig) -> SourceItemProvider:
    """Construct the provider selected by the one typed source-variant match."""
    match config.source:
        case VeridianSource() as source:
            return VeridianSourceItemProvider.open(source, config)
        case WebPagePdfSource() as source:
            return WebPageSourceItemProvider.open(source, config)
        case UrlSequencePdfSource() as source:
            return UrlSequenceSourceItemProvider.from_source(source)
        case UrlListPdfSource() as source:
            return UrlListSourceItemProvider.from_source(source)
        case LocalPdfSource() as source:
            return LocalDirectorySourceItemProvider.from_source(source)
