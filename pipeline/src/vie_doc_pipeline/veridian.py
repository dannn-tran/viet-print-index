"""Discovery and full-page image retrieval for Veridian newspaper viewers.

The National Library of Vietnam's newspaper collection uses Veridian. Its
viewer displays page images as tiles, but the same public image server accepts
a full-page crop at the page's native dimensions. This module deliberately
uses those complete page requests rather than attempting to stitch viewer
tiles or article crops.
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

from vie_doc_pipeline.pipeline_config import SourceConfig


DEFAULT_BASE_URL = "http://baochi.nlv.gov.vn/baochi/cgi-bin/baochi"
DEFAULT_IMAGE_SERVER_URL = (
    "http://baochi.nlv.gov.vn/baochi/cgi-bin/imageserver/imageserver.pl"
)
_MONTH_LINK_RE = re.compile(r'href="([^"]*a=cl[^" ]*cl=CL2\.(\d{4})\.(\d{2})[^" ]*)"')
_ISSUE_RE = re.compile(r"[?&]d=([A-Za-z0-9]+\d{8})")
_DOCUMENT_OID_RE = re.compile(r"var documentOID = '([^']+)'\s*;")
_PAGE_SIZE_RE = re.compile(r"'([0-9]+\.[0-9]+)':\{'w':(\d+),'h':(\d+)\}")


@dataclass(frozen=True)
class VeridianIssue:
    oid: str
    published_on: date


@dataclass(frozen=True)
class VeridianPage:
    issue_oid: str
    page_oid: str
    width: int
    height: int

    @property
    def filename(self) -> str:
        return f"{int(self.page_oid.split('.')[-1]):03d}.jpg"


class VeridianClient:
    def __init__(self, config: SourceConfig) -> None:
        if not config.title_id:
            raise ValueError("veridian source requires title_id")
        self.title_id = config.title_id
        self.base_url = (config.base_url or DEFAULT_BASE_URL).rstrip("/")
        self.image_server_url = self._image_server_url(self.base_url)
        self.from_date = _parse_date(config.from_date, "from_date") if config.from_date else None
        self.to_date = _parse_date(config.to_date, "to_date") if config.to_date else None
        self.delay_seconds = max(config.delay_seconds, 0.0)
        self._last_request_at: float | None = None

    def list_issues(self, limit: int | None = None) -> list[VeridianIssue]:
        """Discover dated issues by following the title calendar then month lists."""
        title_html = self._fetch(self._catalogue_url(a="cl", cl="CL1", sp=self.title_id))
        month_urls = _month_urls(title_html, self.base_url, self.title_id)
        issues: dict[str, VeridianIssue] = {}
        for year, month, url in month_urls:
            if not _month_overlaps(year, month, self.from_date, self.to_date):
                continue
            for issue in _issues_from_month_html(self._fetch(url), self.title_id):
                if _in_range(issue.published_on, self.from_date, self.to_date):
                    issues[issue.oid] = issue
            if limit is not None and len(issues) >= limit:
                return sorted(issues.values(), key=lambda issue: issue.published_on)[:limit]
        return sorted(issues.values(), key=lambda issue: issue.published_on)

    def list_pages(self, issue: VeridianIssue) -> list[VeridianPage]:
        issue_html = self._fetch(self._catalogue_url(a="d", d=issue.oid))
        return parse_pages(issue_html, issue.oid)

    def page_image_url(self, page: VeridianPage) -> str:
        return self.image_server_url + "?" + urllib.parse.urlencode(
            {
                "color": "all",
                "ext": "jpg",
                "oid": f"{page.issue_oid}.{page.page_oid}",
                "key": "",
                "width": page.width,
                "crop": f"0,0,{page.width},{page.height}",
            }
        )

    def fetch_page_image(self, page: VeridianPage) -> bytes:
        return self._fetch_bytes(self.page_image_url(page))

    def _catalogue_url(self, **query: str) -> str:
        return self.base_url + "?" + urllib.parse.urlencode(query)

    def _fetch(self, url: str) -> str:
        return self._fetch_bytes(url).decode("utf-8", errors="replace")

    def _fetch_bytes(self, url: str) -> bytes:
        if self._last_request_at is not None and self.delay_seconds:
            remaining = self.delay_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        request = urllib.request.Request(url, headers={"User-Agent": "vie-pipeline/1.0 (research ingestion)"})
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
        self._last_request_at = time.monotonic()
        return body

    @staticmethod
    def _image_server_url(base_url: str) -> str:
        if base_url.endswith("/cgi-bin/baochi"):
            return base_url.removesuffix("/baochi") + "/imageserver/imageserver.pl"
        return DEFAULT_IMAGE_SERVER_URL


def parse_pages(issue_html: str, expected_issue_oid: str) -> list[VeridianPage]:
    """Parse native full-page dimensions embedded by the public viewer."""
    document_oid = _DOCUMENT_OID_RE.search(issue_html)
    if not document_oid:
        raise ValueError(f"Could not find documentOID for {expected_issue_oid}")
    if document_oid.group(1) != expected_issue_oid:
        raise ValueError(f"Viewer documentOID {document_oid.group(1)!r} does not match {expected_issue_oid!r}")
    pages = [
        VeridianPage(expected_issue_oid, page_oid, int(width), int(height))
        for page_oid, width, height in _PAGE_SIZE_RE.findall(issue_html)
    ]
    if not pages:
        raise ValueError(f"Could not find pageImageSizes for {expected_issue_oid}")
    return pages


def _month_urls(title_html: str, base_url: str, title_id: str) -> list[tuple[int, int, str]]:
    result: dict[tuple[int, int], str] = {}
    for href, year, month in _MONTH_LINK_RE.findall(html.unescape(title_html)):
        if f"sp={title_id}" not in href:
            continue
        result[(int(year), int(month))] = urllib.parse.urljoin(base_url, href)
    return [(year, month, url) for (year, month), url in sorted(result.items())]


def _issues_from_month_html(month_html: str, title_id: str) -> list[VeridianIssue]:
    issues: dict[str, VeridianIssue] = {}
    for oid in _ISSUE_RE.findall(html.unescape(month_html)):
        if not oid.startswith(title_id):
            continue
        try:
            issues[oid] = VeridianIssue(oid=oid, published_on=date.fromisoformat(
                f"{oid[-8:-4]}-{oid[-4:-2]}-{oid[-2:]}"
            ))
        except ValueError:
            continue
    return list(issues.values())


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from error


def _month_overlaps(year: int, month: int, from_date: date | None, to_date: date | None) -> bool:
    first = date(year, month, 1)
    last = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    if to_date and first > to_date:
        return False
    return not from_date or last > from_date


def _in_range(value: date, from_date: date | None, to_date: date | None) -> bool:
    return (from_date is None or value >= from_date) and (to_date is None or value <= to_date)
