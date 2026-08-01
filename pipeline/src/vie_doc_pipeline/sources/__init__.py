"""Function-oriented source discovery adapters.

Adapters return immutable source records. Pipeline stages own GCS and ledger
effects; source modules only enumerate source documents or native page images.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.models import DiscoveredSourceItem
from vie_doc_pipeline.sources.pdf import discover_pdf_items
from vie_doc_pipeline.sources.veridian import iter_pages


def discover_source_items(
    config: SourceConfig, fetch_text: Callable[[str], str], limit: int | None = None
) -> Iterable[DiscoveredSourceItem]:
    """Discover source items using the adapter selected by ``config.type``."""
    if config.type == "veridian":
        return iter_pages(config, fetch_text, limit)
    else:
        items = discover_pdf_items(config, fetch_text)
    return items[:limit] if limit is not None else items
