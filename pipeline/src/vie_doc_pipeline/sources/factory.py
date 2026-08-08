"""Factory and unified interface for source-item enumeration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from vie_doc_pipeline.sources.models import DiscoveredSourceItem, SourceItemProvider
from vie_doc_pipeline.common.config import (
    LocalPdfSource,
    PipelineConfig,
    SourceRequestsConfig,
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

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_url_list(self.source.urls)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class LocalDirectorySourceItemProvider(SourceItemProvider):
    source: LocalPdfSource

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_local_directory(self.source.path)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class VeridianSourceItemProvider(SourceItemProvider):
    source: VeridianSource
    http: HttpClient

    @classmethod
    def open(
        cls,
        source: VeridianSource,
        request_policy: SourceRequestsConfig,
    ) -> "VeridianSourceItemProvider":
        return cls(source, http_client(request_policy))

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        yield from iter_source_items_from_veridian(self.source, self.http)

    def close(self) -> None:
        self.http.close()


@dataclass(frozen=True)
class WebPageSourceItemProvider(SourceItemProvider):
    source: WebPagePdfSource
    http: HttpClient

    @classmethod
    def open(
        cls,
        source: WebPagePdfSource,
        request_policy: SourceRequestsConfig,
    ) -> "WebPageSourceItemProvider":
        return cls(source, http_client(request_policy))

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
    request_policy = config.source_requests
    match config.source:
        case VeridianSource() as source:
            provider = VeridianSourceItemProvider.open(source, request_policy)
        case WebPagePdfSource() as source:
            provider = WebPageSourceItemProvider.open(source, request_policy)
        case UrlSequencePdfSource() as source:
            provider = UrlSequenceSourceItemProvider(source)
        case UrlListPdfSource() as source:
            provider = UrlListSourceItemProvider(source)
        case LocalPdfSource() as source:
            provider = LocalDirectorySourceItemProvider(source)
    try:
        yield provider
    finally:
        provider.close()
