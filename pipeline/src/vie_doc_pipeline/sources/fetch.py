"""Fetch discovered original source assets into the configured target."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice

from google.api_core import exceptions as google_exceptions

from vie_doc_pipeline.ledger.events import EventRecord, failed, source_fetched
from vie_doc_pipeline.state import PipelineState
from vie_doc_pipeline.sources.http import HttpClient, SourceHttpError, TransientSourceError, http_client
from vie_doc_pipeline.common.assets import SourceAsset
from vie_doc_pipeline.common.storage import TargetStore, open_target_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchSummary:
    fetched: int = 0
    already_present: int = 0
    failed: int = 0


@dataclass(frozen=True)
class Fetched:
    asset: SourceAsset
    event: EventRecord


@dataclass(frozen=True)
class AlreadyPresent:
    asset: SourceAsset
    event: EventRecord


@dataclass(frozen=True)
class FetchFailed:
    asset: SourceAsset
    event: EventRecord


FetchOutcome = Fetched | AlreadyPresent | FetchFailed


@dataclass(frozen=True)
class _FetchContext:
    """External capabilities and policy fixed for one source-fetch run."""

    store: TargetStore
    http: HttpClient
    retry_delay: float

    def _fetch(self, asset: SourceAsset) -> FetchOutcome:
        """Fetch one asset and return the event that records its outcome."""
        try:
            existing = self.store.inspect(asset.target_path)
            if existing is not None:
                return AlreadyPresent(
                    asset,
                    source_fetched(asset, checksum=existing.checksum, size_bytes=existing.size_bytes),
                )
            data = self.http.fetch_bytes(asset.source_url)
            self.store.write_bytes(asset.target_path, data, content_type=_content_type(asset))
            return Fetched(
                asset,
                source_fetched(asset, checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data)),
            )
        except (SourceHttpError, TransientSourceError, google_exceptions.GoogleAPIError, OSError) as error:
            return self._record_failure(asset, error)

    def _record_failure(self, asset: SourceAsset, error: Exception) -> FetchFailed:
        """Build retry metadata for one failed source fetch."""
        retryable, attempts = _failure_details(error)
        result = FetchFailed(
            asset,
            failed(
                asset.key,
                stage="fetch",
                error=str(error),
                retryable=retryable,
                attempts=attempts,
                retry_not_before=time.time() + self.retry_delay if retryable else None,
            ),
        )
        logger.warning("Failed to fetch %s: %s", asset.key, error)
        return result


@dataclass
class SourceAssetFetchService:
    """Fetch discovered source assets and persist the outcomes."""

    state: PipelineState

    def execute(self, max_items: int | None = None) -> FetchSummary:
        """Fetch discovered source assets into the configured target."""
        config = self.state.configuration
        with open_target_store(config.target) as store:
            assets = islice(self.state.eligible_source_assets(), max_items)
            client = http_client(config.source_requests)
            try:
                context = _FetchContext(
                    store=store,
                    http=client,
                    retry_delay=config.source_requests.backoff_max_seconds,
                )
                outcomes = _run_fetches(context, assets, config.source_requests.max_concurrent_requests)
                recorded: list[FetchOutcome] = []
                for outcome in outcomes:
                    self.state.record(outcome.event)
                    recorded.append(outcome)
                return _summarize_fetches(recorded)
            finally:
                client.close()


def _run_fetches(
    context: _FetchContext,
    assets: Iterable[SourceAsset],
    max_concurrent_requests: int,
) -> Iterator[FetchOutcome]:
    """Apply one fetch function concurrently while retaining input ordering."""
    with ThreadPoolExecutor(max_workers=max_concurrent_requests) as executor:
        yield from executor.map(context._fetch, assets)


def _summarize_fetches(outcomes: Iterable[FetchOutcome]) -> FetchSummary:
    """Reduce individual source-fetch outcomes into a typed stage summary."""
    fetched = 0
    already_present = 0
    failed = 0
    for outcome in outcomes:
        match outcome:
            case Fetched():
                fetched += 1
            case AlreadyPresent():
                already_present += 1
            case FetchFailed():
                failed += 1
    return FetchSummary(fetched, already_present, failed)


def _content_type(asset: SourceAsset) -> str:
    return "application/pdf" if asset.kind == "pdf" else "image/jpeg"


def _failure_details(error: Exception) -> tuple[bool, int]:
    if isinstance(error, SourceHttpError):
        return False, 1
    if isinstance(error, TransientSourceError):
        return True, error.attempts
    if isinstance(
        error,
        (
            google_exceptions.DeadlineExceeded,
            google_exceptions.GatewayTimeout,
            google_exceptions.InternalServerError,
            google_exceptions.ServiceUnavailable,
            google_exceptions.TooManyRequests,
        ),
    ):
        return True, 1
    return False, 1
