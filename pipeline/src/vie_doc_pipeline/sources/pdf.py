"""Pure-ish PDF source enumeration for simple web and local collections."""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable, Iterator
from pathlib import Path

from vie_doc_pipeline.models import DiscoveredSourceItem


def iter_source_items_from_web_page(page_url: str, page_html: str) -> Iterator[DiscoveredSourceItem]:
    """Yield PDFs linked by one already-fetched index page."""
    yield from pdf_items(_pdf_urls_from_page(page_url, page_html))


def iter_source_items_from_url_sequence(
    base_url: str,
    pattern: str,
    issue_range: tuple[int, int],
    extra_urls: Iterable[str],
) -> Iterator[DiscoveredSourceItem]:
    """Yield PDFs named by a numeric URL sequence plus any explicit exceptions."""
    start, end = issue_range
    sequence = (f"{base_url.rstrip('/')}/{pattern.format(number)}" for number in range(start, end + 1))
    yield from pdf_items((*sequence, *extra_urls))


def iter_source_items_from_url_list(urls: Iterable[str]) -> Iterator[DiscoveredSourceItem]:
    """Yield the configured explicit PDF URLs."""
    yield from pdf_items(urls)


def iter_source_items_from_local_directory(path: str) -> Iterator[DiscoveredSourceItem]:
    """Yield PDFs in a local source directory."""
    yield from pdf_items(str(item) for item in sorted(Path(path).glob("*.pdf")))


def pdf_items(urls: Iterable[str]) -> Iterator[DiscoveredSourceItem]:
    """Deduplicate source URLs while retaining first-seen ordering."""
    yield from (DiscoveredSourceItem(kind="pdf", source_url=url) for url in dict.fromkeys(urls))


def _pdf_urls_from_page(page_url: str, page_html: str) -> list[str]:
    links = re.findall(r'href="([^"]+\.pdf)"', page_html, re.IGNORECASE)
    return [urllib.parse.urljoin(page_url, link) for link in links]
