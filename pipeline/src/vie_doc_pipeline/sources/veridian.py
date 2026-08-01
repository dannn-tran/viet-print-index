"""Veridian catalogue parsing and native-page URL construction.

All deployment-specific endpoints are supplied by ``SourceConfig``. Functions
accept a fetch callable, keeping HTML parsing and URL construction testable
without network state.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from vie_doc_pipeline.models import SourceItem
from vie_doc_pipeline.pipeline_config import SourceConfig

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


def discover_pages(
    config: SourceConfig,
    fetch_text: Callable[[str], str],
    limit: int | None = None,
) -> list[SourceItem]:
    """Discover native full-page images from a configured Veridian catalogue."""
    assert config.catalogue_url and config.image_server_url and config.title_id
    from_date = parse_date(config.from_date, "from_date") if config.from_date else None
    to_date = parse_date(config.to_date, "to_date") if config.to_date else None
    catalogue_url = config.catalogue_url.rstrip("/")
    title_html = fetch_text(catalogue_url_for(catalogue_url, a="cl", cl="CL1", sp=config.title_id))
    result: list[SourceItem] = []
    for year, month, month_url in month_urls(title_html, catalogue_url, config.title_id):
        if not month_overlaps(year, month, from_date, to_date):
            continue
        issues = sorted(issues_from_month_html(fetch_text(month_url), config.title_id), key=lambda item: item.published_on)
        for issue in issues:
            if not in_range(issue.published_on, from_date, to_date):
                continue
            issue_html = fetch_text(catalogue_url_for(catalogue_url, a="d", d=issue.oid))
            for page in parse_pages(issue_html, issue.oid):
                result.append(SourceItem(
                    kind="image",
                    source_url=page_image_url(config.image_server_url, page),
                    issue_id=issue.oid,
                    page_id=page.page_id,
                    width=page.width,
                    height=page.height,
                ))
                if limit is not None and len(result) >= limit:
                    return result
    return result


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


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from error


def month_overlaps(year: int, month: int, from_date: date | None, to_date: date | None) -> bool:
    first = date(year, month, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return (not to_date or first <= to_date) and (not from_date or next_month > from_date)


def in_range(value: date, from_date: date | None, to_date: date | None) -> bool:
    return (from_date is None or value >= from_date) and (to_date is None or value <= to_date)
