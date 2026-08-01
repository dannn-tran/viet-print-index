"""Function-oriented source discovery adapters.

Adapters return immutable source records. Pipeline stages own GCS and ledger
effects; source modules only enumerate source documents or native page images.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from itertools import islice

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.models import DiscoveredSourceItem
from vie_doc_pipeline.sources.pdf import iter_pdf_items
from vie_doc_pipeline.sources.veridian import iter_pages


def iter_source_items(
    config: SourceConfig, fetch_text: Callable[[str], str], limit: int | None = None
) -> Iterator[DiscoveredSourceItem]:
    """Yield source items using the adapter selected by ``config.type``."""
    if config.type == "veridian":
        yield from iter_pages(config, fetch_text, limit)
        return

    items = iter_pdf_items(config, fetch_text)
    yield from islice(items, limit)
