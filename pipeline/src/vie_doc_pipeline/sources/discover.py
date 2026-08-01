"""One dispatch boundary for typed source configurations."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from vie_doc_pipeline.models import DiscoveredSourceItem
from vie_doc_pipeline.pipeline_config import (
    LocalPdfSource,
    SourceConfig,
    UrlListPdfSource,
    UrlSequencePdfSource,
    VeridianSource,
    WebPagePdfSource,
)
from vie_doc_pipeline.sources.pdf import (
    iter_local_pdf_items,
    iter_url_list_pdf_items,
    iter_url_sequence_pdf_items,
    iter_web_page_pdf_items,
)
from vie_doc_pipeline.sources.veridian import iter_pages


def iter_source_items(
    config: SourceConfig, fetch_text: Callable[[str], str]
) -> Iterator[DiscoveredSourceItem]:
    """Yield all source items for one already-validated source configuration."""
    match config:
        case VeridianSource():
            yield from iter_pages(config, fetch_text)
        case WebPagePdfSource():
            yield from iter_web_page_pdf_items(config.page_url, fetch_text(config.page_url))
        case UrlSequencePdfSource():
            yield from iter_url_sequence_pdf_items(
                config.base_url,
                config.pattern,
                config.issue_range,
                config.extra_urls,
            )
        case UrlListPdfSource():
            yield from iter_url_list_pdf_items(config.urls)
        case LocalPdfSource():
            yield from iter_local_pdf_items(config.path)
