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
    iter_source_items_from_local_directory,
    iter_source_items_from_url_list,
    iter_source_items_from_url_sequence,
    iter_source_items_from_web_page,
)
from vie_doc_pipeline.sources.veridian import iter_source_items_from_veridian


def iter_source_items(
    config: SourceConfig, fetch_text: Callable[[str], str]
) -> Iterator[DiscoveredSourceItem]:
    """Yield all source items for one already-validated source configuration."""
    match config:
        case VeridianSource():
            yield from iter_source_items_from_veridian(config, fetch_text)
        case WebPagePdfSource():
            yield from iter_source_items_from_web_page(config.page_url, fetch_text(config.page_url))
        case UrlSequencePdfSource():
            yield from iter_source_items_from_url_sequence(
                config.base_url,
                config.pattern,
                config.issue_range,
                config.extra_urls,
            )
        case UrlListPdfSource():
            yield from iter_source_items_from_url_list(config.urls)
        case LocalPdfSource():
            yield from iter_source_items_from_local_directory(config.path)
