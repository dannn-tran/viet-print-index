"""Thread-safe source HTTP requests backed by urllib3 resilience primitives."""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable

import urllib3
from urllib3.exceptions import HTTPError, MaxRetryError
from urllib3.util import Retry, Timeout

from vie_doc_pipeline.config import SourceRequestsConfig

_CHARSET_RE = re.compile(r"charset=([^; ]+)", re.IGNORECASE)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class SourceHttpError(RuntimeError):
    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"GET {url} returned HTTP {status}")
        self.url = url
        self.status = status


class TransientSourceError(RuntimeError):
    def __init__(self, url: str, attempts: int, cause: Exception) -> None:
        super().__init__(f"GET {url} failed after {attempts} attempts: {cause}")
        self.url = url
        self.attempts = attempts


@dataclass
class RequestGate:
    """Reserve evenly-spaced request starts across a worker pool."""

    min_interval_seconds: float
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._next_start = 0.0

    def wait_for_turn(self) -> None:
        if not self.min_interval_seconds:
            return
        with self._lock:
            now = self.clock()
            start = max(now, self._next_start)
            self._next_start = start + self.min_interval_seconds
        if delay := start - now:
            self.sleep(delay)


class HttpClient:
    """Shared GET client: rate-gated attempts plus urllib3 retry semantics."""

    def __init__(self, policy: SourceRequestsConfig) -> None:
        self.policy = policy
        self.gate = RequestGate(policy.min_interval_seconds)
        self.pool = urllib3.PoolManager(
            maxsize=policy.max_concurrent_requests,
            num_pools=policy.max_concurrent_requests,
            timeout=Timeout(connect=10, read=60),
            headers={"User-Agent": "vie-pipeline/1.0 (research ingestion)"},
        )

    def fetch_bytes(self, url: str) -> bytes:
        encoded_url = encode_url(url)
        retry = retry_policy(self.policy)
        while True:
            try:
                response = self.request_once(encoded_url)
            except HTTPError as error:
                retry = self.retry_after_error(retry, encoded_url, error)
                continue
            if retry.is_retry("GET", response.status, "retry-after" in response.headers):
                retry = self.retry_after_response(retry, encoded_url, response)
                continue
            return response_data(url, response)

    def request_once(self, url: str) -> urllib3.BaseHTTPResponse:
        """Make one rate-gated GET attempt; retry policy remains explicit above."""
        self.gate.wait_for_turn()
        return self.pool.request("GET", url, retries=False, preload_content=True)

    def retry_after_error(self, retry: Retry, url: str, error: HTTPError) -> Retry:
        """Advance retry state and pause after a transport failure."""
        next_retry = self._next_retry(retry, url, error=error)
        next_retry.sleep()
        return next_retry

    def retry_after_response(
        self, retry: Retry, url: str, response: urllib3.BaseHTTPResponse
    ) -> Retry:
        """Advance retry state, release the response, and honour its retry delay."""
        try:
            next_retry = self._next_retry(retry, url, response=response)
        finally:
            response.release_conn()
        next_retry.sleep(response)
        return next_retry

    def fetch_text(self, url: str) -> str:
        data = self.fetch_bytes(url)
        # NLV HTML frequently omits a charset; Latin-1 preserves byte values
        # better than a lossy UTF-8 guess for its legacy markup.
        return data.decode("latin-1", errors="replace")

    def close(self) -> None:
        self.pool.clear()

    @staticmethod
    def _next_retry(retry: Retry, url: str, *, response: urllib3.BaseHTTPResponse | None = None, error: Exception | None = None) -> Retry:
        try:
            return retry.increment(method="GET", url=url, response=response, error=error)
        except MaxRetryError as exhausted:
            raise TransientSourceError(url, len(retry.history) + 1, exhausted.reason) from exhausted


def http_client(policy: SourceRequestsConfig) -> HttpClient:
    return HttpClient(policy)


def retry_policy(policy: SourceRequestsConfig) -> Retry:
    """Build the immutable urllib3 retry policy used for every request."""
    retries = policy.max_attempts - 1
    return Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        other=0,
        allowed_methods=frozenset({"GET"}),
        status_forcelist=_RETRY_STATUSES,
        backoff_factor=policy.backoff_factor,
        backoff_max=policy.backoff_max_seconds,
        backoff_jitter=policy.backoff_jitter_seconds,
        respect_retry_after_header=True,
        raise_on_status=False,
    )


def response_data(url: str, response: urllib3.BaseHTTPResponse) -> bytes:
    """Return a successful response body while always releasing its connection."""
    try:
        if response.status >= 400:
            raise SourceHttpError(url, response.status)
        return response.data
    finally:
        response.release_conn()


def encode_url(url: str) -> str:
    """Percent-encode Unicode path/query text while preserving existing escapes."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/:@!$&'()*+,;=%-")
    query = urllib.parse.quote(parts.query, safe="/:@!$&'()*+,;=%-?&=")
    return urllib.parse.urlunsplit(parts._replace(path=path, query=query))
