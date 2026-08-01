"""Pure-ish PDF source enumeration for simple web and local collections."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.sources.models import SourceItem


def discover_pdf_items(config: SourceConfig, fetch_text: Callable[[str], str]) -> list[SourceItem]:
    """Return PDF source items for the configured non-image source type."""
    match config.type:
        case "web_page":
            assert config.page_url, "page_url required for web_page source type"
            urls = _pdf_urls_from_page(config.page_url, fetch_text(config.page_url))
        case "url_sequence":
            base = (config.base_url or "").rstrip("/")
            pattern = config.pattern or "{}.pdf"
            start, end = config.range or (1, 1)
            urls = [f"{base}/{pattern.format(i)}" for i in range(start, end + 1)] + config.urls
        case "url_list":
            urls = config.urls
        case "local_dir":
            path = config.path or "."
            urls = [str(item) for item in sorted(Path(path).glob("*.pdf"))]
        case _:
            raise ValueError(f"Unknown PDF source type: {config.type!r}")
    return [SourceItem(kind="pdf", source_url=url) for url in dict.fromkeys(urls)]


def _pdf_urls_from_page(page_url: str, page_html: str) -> list[str]:
    links = re.findall(r'href="([^"]+\.pdf)"', page_html, re.IGNORECASE)
    return [urllib.parse.urljoin(page_url, link) for link in links]
