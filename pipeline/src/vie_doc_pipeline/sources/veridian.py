"""Veridian catalogue parsing and native-page URL construction.

All deployment-specific endpoints are supplied by ``VeridianSource``. Functions
accept a fetch callable, keeping HTML parsing and URL construction testable
without network state.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from itertools import chain

from vie_doc_pipeline.models import DiscoveredSourceItem
from vie_doc_pipeline.pipeline_config import VeridianSource

_MONTH_LINK_RE = re.compile(r'href="([^"]*a=cl[^" ]*cl=CL2\.(\d{4})\.(\d{2})[^" ]*)"')
_ISSUE_RE = re.compile(r"[?&]d=([A-Za-z0-9]+\d{8})")
_DOCUMENT_OID_RE = re.compile(r"var documentOID = '([^']+)'\s*;")
_PAGE_SIZE_RE = re.compile(r"'([0-9]+\.[0-9]+)':\{'w':(\d+),'h':(\d+)\}")


@dataclass(frozen=True)
class Issue:
    oid: str
    published_on: date


@dataclass(frozen=True)
class Page:
    issue_oid: str
    page_oid: str
    width: int
    height: int

    @property
    def page_id(self) -> str:
        return f"{int(self.page_oid.split('.')[-1]):03d}"

    @property
    def filename(self) -> str:
        return self.page_id + ".jpg"


def iter_source_items_from_veridian(
    config: VeridianSource,
    fetch_text: Callable[[str], str],
) -> Iterator[DiscoveredSourceItem]:
    """Discover native full-page images from a configured Veridian catalogue."""
    catalogue_url = config.catalogue_url.rstrip("/")
    title_html = fetch_text(catalogue_url_for(catalogue_url, a="cl", cl="CL1", sp=config.title_id))
    month_htmls = (
        fetch_text(month_url)
        for year, month, month_url in month_urls(title_html, catalogue_url, config.title_id)
        if month_overlaps(year, month, config.from_date, config.to_date)
    )
    issues = iter_catalogue_issues(month_htmls, config.title_id, config.from_date, config.to_date)
    issue_htmls = (
        (issue, fetch_text(catalogue_url_for(catalogue_url, a="d", d=issue.oid)))
        for issue in issues
    )
    pages = chain.from_iterable(
        iter_issue_pages(config, issue, issue_html)
        for issue, issue_html in issue_htmls
    )
    yield from pages


def iter_catalogue_issues(
    month_htmls: Iterable[str],
    title_id: str,
    from_date: date | None,
    to_date: date | None,
) -> Iterator[Issue]:
    """Yield in-range issues parsed from the supplied monthly catalogue HTML."""
    for month_html in month_htmls:
        issues = sorted(issues_from_month_html(month_html, title_id), key=lambda issue: issue.published_on)
        yield from filter(lambda issue: in_range(issue.published_on, from_date, to_date), issues)


def iter_issue_pages(
    config: VeridianSource,
    issue: Issue,
    issue_html: str,
) -> Iterator[DiscoveredSourceItem]:
    """Yield native full-page images parsed from one already-fetched viewer page."""
    for page in parse_pages(issue_html, issue.oid):
        yield DiscoveredSourceItem(
            kind="image",
            source_url=page_image_url(config.image_server_url, page),
            issue_id=issue.oid,
            issue_label=f"{issue.published_on.isoformat()}_{issue.oid}",
            page_id=page.page_id,
            width=page.width,
            height=page.height,
        )


def catalogue_url_for(catalogue_url: str, **query: str) -> str:
    return catalogue_url + "?" + urllib.parse.urlencode(query)


def page_image_url(image_server_url: str, page: Page) -> str:
    return image_server_url + "?" + urllib.parse.urlencode({
        "color": "all", "ext": "jpg", "oid": f"{page.issue_oid}.{page.page_oid}", "key": "",
        "width": page.width, "crop": f"0,0,{page.width},{page.height}",
    })


def parse_pages(issue_html: str, expected_issue_oid: str) -> list[Page]:
    document_oid = _DOCUMENT_OID_RE.search(issue_html)
    if not document_oid:
        raise ValueError(f"Could not find documentOID for {expected_issue_oid}")
    if document_oid.group(1) != expected_issue_oid:
        raise ValueError(f"Viewer documentOID {document_oid.group(1)!r} does not match {expected_issue_oid!r}")
    pages = [Page(expected_issue_oid, page_oid, int(width), int(height)) for page_oid, width, height in _PAGE_SIZE_RE.findall(issue_html)]
    if not pages:
        raise ValueError(f"Could not find pageImageSizes for {expected_issue_oid}")
    return pages


def month_urls(title_html: str, catalogue_url: str, title_id: str) -> list[tuple[int, int, str]]:
    result: dict[tuple[int, int], str] = {}
    for href, year, month in _MONTH_LINK_RE.findall(html.unescape(title_html)):
        if f"sp={title_id}" in href:
            result[(int(year), int(month))] = urllib.parse.urljoin(catalogue_url, href)
    return [(year, month, url) for (year, month), url in sorted(result.items())]


def issues_from_month_html(month_html: str, title_id: str) -> list[Issue]:
    issues: dict[str, Issue] = {}
    for oid in _ISSUE_RE.findall(html.unescape(month_html)):
        if oid.startswith(title_id):
            try:
                issues[oid] = Issue(oid, date.fromisoformat(f"{oid[-8:-4]}-{oid[-4:-2]}-{oid[-2:]}"))
            except ValueError:
                pass
    return list(issues.values())


def month_overlaps(year: int, month: int, from_date: date | None, to_date: date | None) -> bool:
    first = date(year, month, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return (not to_date or first <= to_date) and (not from_date or next_month > from_date)


def in_range(value: date, from_date: date | None, to_date: date | None) -> bool:
    return (from_date is None or value >= from_date) and (to_date is None or value <= to_date)
