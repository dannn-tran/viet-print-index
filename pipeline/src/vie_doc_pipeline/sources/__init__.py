"""Function-oriented source discovery adapters.

Adapters return immutable source records. Pipeline stages own GCS and ledger
effects; source modules only enumerate source documents or native page images.
"""

from __future__ import annotations

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.models import SourceItem
from vie_doc_pipeline.sources.http import fetch_text, rate_limited
from vie_doc_pipeline.sources.pdf import discover_pdf_items
from vie_doc_pipeline.sources.veridian import discover_pages


def discover_source_items(config: SourceConfig, limit: int | None = None) -> list[SourceItem]:
    """Discover source items using the adapter selected by ``config.type``."""
    if config.type == "veridian":
        fetch = rate_limited(fetch_text, config.delay_seconds)
        items = discover_pages(config, fetch)
    else:
        items = discover_pdf_items(config, fetch_text)
    return items[:limit] if limit is not None else items
