"""Function-oriented source discovery adapters.

Adapters return immutable source records. Pipeline stages own GCS and ledger
effects; source modules only enumerate source documents or native page images.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from itertools import islice

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.models import DiscoveredSourceItem
from vie_doc_pipeline.sources.pdf import (
    iter_local_pdf_items,
    iter_url_list_pdf_items,
    iter_url_sequence_pdf_items,
    iter_web_page_pdf_items,
)
from vie_doc_pipeline.sources.veridian import iter_pages


def iter_source_items(
    config: SourceConfig, fetch_text: Callable[[str], str], limit: int | None = None
) -> Iterator[DiscoveredSourceItem]:
    """Yield source items using the adapter selected by ``config.type``."""
    match config.type:
        case "veridian":
            yield from iter_pages(config, fetch_text, limit)
            return
        case "web_page":
            assert config.page_url, "page_url required for web_page source type"
            items = iter_web_page_pdf_items(config.page_url, fetch_text(config.page_url))
        case "url_sequence":
            items = iter_url_sequence_pdf_items(
                config.base_url or "",
                config.pattern or "{}.pdf",
                config.range or (1, 1),
                config.urls,
            )
        case "url_list":
            items = iter_url_list_pdf_items(config.urls)
        case "local_dir":
            items = iter_local_pdf_items(config.path or ".")
        case source_type:
            raise ValueError(f"Unknown source type: {source_type!r}")
    yield from islice(items, limit)
