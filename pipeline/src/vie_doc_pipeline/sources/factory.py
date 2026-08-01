"""Factory and unified interface for source-item enumeration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from vie_doc_pipeline.sources.contracts import DiscoveredSourceItem, SourceItemProvider
from vie_doc_pipeline.config import (
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
    match config.source:
        case VeridianSource() as source:
            provider = VeridianSourceItemProvider.open(source, config)
        case WebPagePdfSource() as source:
            provider = WebPageSourceItemProvider.open(source, config)
        case UrlSequencePdfSource() as source:
            provider = UrlSequenceSourceItemProvider.from_source(source)
        case UrlListPdfSource() as source:
            provider = UrlListSourceItemProvider.from_source(source)
        case LocalPdfSource() as source:
            provider = LocalDirectorySourceItemProvider.from_source(source)
    try:
        yield provider
    finally:
        provider.close()
