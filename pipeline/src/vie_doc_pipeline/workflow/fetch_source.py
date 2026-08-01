"""Fetch discovered original source assets into the configured target."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from google.api_core import exceptions as google_exceptions

from vie_doc_pipeline.ledger.events import failed, source_fetched
from vie_doc_pipeline.ledger.configuration import ensure_config_compatible
from vie_doc_pipeline.ledger.locking import source_fetch_lock
from vie_doc_pipeline.ledger.projection import AppState, CurrentState, eligible_source_assets
from vie_doc_pipeline.ledger.store import EventStore
from vie_doc_pipeline.config import PipelineConfig
from vie_doc_pipeline.sources.http import HttpClient, SourceHttpError, TransientSourceError, http_client
from vie_doc_pipeline.assets import SourceAsset
from vie_doc_pipeline.storage import TargetStore, open_target_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchSummary:
    fetched: int = 0
    already_present: int = 0
    failed: int = 0


@dataclass(frozen=True)
class Fetched:
    asset: SourceAsset


@dataclass(frozen=True)
class AlreadyPresent:
    asset: SourceAsset


@dataclass(frozen=True)
class FetchFailed:
    asset: SourceAsset


FetchOutcome = Fetched | AlreadyPresent | FetchFailed


@dataclass(frozen=True)
class FetchContext:
    """External capabilities and policy fixed for one source-fetch run."""

    store: TargetStore
    http: HttpClient
    event_store: EventStore
    retry_delay: float

    def fetch(self, asset: SourceAsset) -> FetchOutcome:
        """Store one asset and persist its outcome in this stage session."""
        try:
            existing = self.store.inspect(asset.target_path)
            if existing is not None:
                self.event_store.append(source_fetched(asset, checksum=existing.checksum, size_bytes=existing.size_bytes))
                return AlreadyPresent(asset)
            data = self.http.fetch_bytes(asset.source_url)
            self.store.write_bytes(asset.target_path, data, content_type=_content_type(asset))
            self.event_store.append(source_fetched(asset, checksum=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))
            return Fetched(asset)
        except (SourceHttpError, TransientSourceError, google_exceptions.GoogleAPIError, OSError) as error:
            self.record_failure(asset, error)
            return FetchFailed(asset)

    def record_failure(self, asset: SourceAsset, error: Exception) -> None:
        """Persist retry metadata for one failed source fetch."""
        retryable, attempts = _failure_details(error)
        self.event_store.append(
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


def fetch_source_assets(config: PipelineConfig, ledger_path: Path, limit: int | None = None) -> FetchSummary:
    """Fetch discovered source assets into the configured target."""
    with source_fetch_lock(ledger_path):
        event_store = EventStore.open(ledger_path)
        ensure_config_compatible(event_store, config.config_snapshot)
        with open_target_store(config.target) as store:
            current = AppState.replay(event_store).current
            assets = iter_fetch_candidates(current, limit)
            client = http_client(config.source_requests)
            try:
                context = FetchContext(
                    store=store,
                    http=client,
                    event_store=event_store,
                    retry_delay=config.source_requests.backoff_max_seconds,
                )
                outcomes = run_fetches(context, assets, config.source_requests.max_concurrent_requests)
                return summarize_fetches(outcomes)
            finally:
                client.close()


def iter_fetch_candidates(
    current: CurrentState,
    limit: int | None,
) -> Iterator[SourceAsset]:
    """Yield source assets eligible for another fetch attempt."""
    assets = (state.asset for state in eligible_source_assets(current) if state.asset is not None)
    yield from islice(assets, limit)


def run_fetches(
    context: FetchContext,
    assets: Iterable[SourceAsset],
    max_concurrent_requests: int,
) -> Iterator[FetchOutcome]:
    """Apply one fetch function concurrently while retaining input ordering."""
    with ThreadPoolExecutor(max_workers=max_concurrent_requests) as executor:
        yield from executor.map(context.fetch, assets)


def summarize_fetches(outcomes: Iterable[FetchOutcome]) -> FetchSummary:
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
