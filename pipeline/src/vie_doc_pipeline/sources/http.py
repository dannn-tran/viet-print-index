"""Thread-safe HTTP acquisition backed by urllib3 resilience primitives."""

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

from vie_doc_pipeline.pipeline_config import AcquisitionConfig

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

    def __init__(self, policy: AcquisitionConfig) -> None:
        self.policy = policy
        self.gate = RequestGate(policy.min_request_interval_seconds)
        self.pool = urllib3.PoolManager(
            maxsize=policy.max_workers,
            num_pools=policy.max_workers,
            timeout=Timeout(connect=10, read=60),
            headers={"User-Agent": "vie-pipeline/1.0 (research ingestion)"},
        )

    def fetch_bytes(self, url: str) -> bytes:
        encoded_url = encode_url(url)
        retry = Retry(
            total=self.policy.max_attempts - 1,
            connect=self.policy.max_attempts - 1,
            read=self.policy.max_attempts - 1,
            status=self.policy.max_attempts - 1,
            other=0,
            allowed_methods=frozenset({"GET"}),
            status_forcelist=_RETRY_STATUSES,
            backoff_factor=self.policy.backoff_factor,
            backoff_max=self.policy.backoff_max_seconds,
            backoff_jitter=self.policy.backoff_jitter_seconds,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        while True:
            self.gate.wait_for_turn()
            try:
                response = self.pool.request("GET", encoded_url, retries=False, preload_content=True)
            except HTTPError as error:
                retry = self._next_retry(retry, encoded_url, error=error)
                retry.sleep()
                continue
            if retry.is_retry("GET", response.status, "retry-after" in response.headers):
                try:
                    retry = self._next_retry(retry, encoded_url, response=response)
                finally:
                    response.release_conn()
                retry.sleep(response)
                continue
            try:
                if response.status >= 400:
                    raise SourceHttpError(url, response.status)
                return response.data
            finally:
                response.release_conn()

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


def http_client(policy: AcquisitionConfig) -> HttpClient:
    return HttpClient(policy)


def encode_url(url: str) -> str:
    """Percent-encode Unicode path/query text while preserving existing escapes."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/:@!$&'()*+,;=%-")
    query = urllib.parse.quote(parts.query, safe="/:@!$&'()*+,;=%-?&=")
    return urllib.parse.urlunsplit(parts._replace(path=path, query=query))
