"""Small, injectable boundary around HTTP and request pacing."""

from __future__ import annotations

import time
import urllib.parse
import urllib.request
from collections.abc import Callable


def fetch_bytes(url: str) -> bytes:
    """Fetch a URL with Unicode-safe encoding and a conservative timeout."""
    request = urllib.request.Request(encode_url(url), headers={"User-Agent": "vie-pipeline/1.0 (research ingestion)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_text(url: str) -> str:
    """Fetch and decode HTML, respecting a declared response charset."""
    request = urllib.request.Request(encode_url(url), headers={"User-Agent": "vie-pipeline/1.0 (research ingestion)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "latin-1"
    return raw.decode(charset, errors="replace")


def encode_url(url: str) -> str:
    """Percent-encode Unicode path/query text while preserving existing escapes."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/:@!$&'()*+,;=%-")
    query = urllib.parse.quote(parts.query, safe="/:@!$&'()*+,;=%-?&=")
    return urllib.parse.urlunsplit(parts._replace(path=path, query=query))


def rate_limited(fetch: Callable[[str], str], delay_seconds: float) -> Callable[[str], str]:
    """Return a paced fetch function; mutable timing stays inside this closure."""
    last_request_at: float | None = None

    def paced_fetch(url: str) -> str:
        nonlocal last_request_at
        if last_request_at is not None and delay_seconds:
            remaining = delay_seconds - (time.monotonic() - last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        result = fetch(url)
        last_request_at = time.monotonic()
        return result

    return paced_fetch
