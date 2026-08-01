"""Factory and unified interface for source-item enumeration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

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


class SourceItemProvider(Protocol):
    """One source-specific enumeration session."""

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]: ...


@dataclass(frozen=True)
class StaticSourceItemProvider:
    """Enumerates source types that do not need HTTP during discovery."""

    source: UrlSequencePdfSource | UrlListPdfSource | LocalPdfSource

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        match self.source:
            case UrlSequencePdfSource():
                yield from iter_source_items_from_url_sequence(
                    self.source.base_url,
                    self.source.pattern,
                    self.source.issue_range,
                    self.source.extra_urls,
                )
            case UrlListPdfSource():
                yield from iter_source_items_from_url_list(self.source.urls)
            case LocalPdfSource():
                yield from iter_source_items_from_local_directory(self.source.path)


@dataclass(frozen=True)
class HttpSourceItemProvider:
    """Enumerates source types that need the shared HTTP session."""

    source: VeridianSource | WebPagePdfSource
    http: HttpClient

    def iter_source_items(self) -> Iterator[DiscoveredSourceItem]:
        match self.source:
            case VeridianSource():
                yield from iter_source_items_from_veridian(self.source, self.http)
            case WebPagePdfSource():
                yield from iter_source_items_from_web_page(
                    self.source.page_url,
                    self.http.fetch_text(self.source.page_url),
                )


@contextmanager
def open_source_items(config: PipelineConfig) -> Iterator[SourceItemProvider]:
    """Open exactly the resources required to enumerate one configured source."""
    source = config.source
    if isinstance(source, (UrlSequencePdfSource, UrlListPdfSource, LocalPdfSource)):
        yield StaticSourceItemProvider(source)
        return

    client = http_client(config.acquisition)
    try:
        yield HttpSourceItemProvider(source, client)
    finally:
        client.close()
