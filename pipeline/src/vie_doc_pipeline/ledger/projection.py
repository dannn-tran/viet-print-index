"""Pure projection and selection helpers over ledger history."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
import time

from vie_doc_pipeline.ledger.jsonl import read_events
from vie_doc_pipeline.ledger.events import LedgerEvent
from vie_doc_pipeline.assets import SourceAsset, source_asset_from_dict


@dataclass(frozen=True)
class FailureState:
    at: str
    stage: str
    error: str
    retryable: bool
    attempts: int
    retry_not_before: float | None


@dataclass(frozen=True)
class CurrentAssetState:
    event: str | None = None
    at: str | None = None
    asset: SourceAsset | None = None
    failure: FailureState | None = None
    inverted_override: bool = False
    job_id: str | None = None
    output_prefix: str | None = None
    output_uris: tuple[str, ...] = ()


CurrentState = dict[str, CurrentAssetState]


def apply_event(states: CurrentState, event: LedgerEvent) -> CurrentState:
    """Apply one event to a mutable projection and return that projection."""
    if event.event == "ledger_initialized":
        return states
    state = states.setdefault(event.asset_key, CurrentAssetState())
    if event.event == "failed":
        states[event.asset_key] = replace(state, failure=_failure_from_event(event))
        return states
    if event.event == "image_inverted":
        states[event.asset_key] = replace(state, inverted_override=True)
        return states
    if event.event == "source_inverted":
        return states
    states[event.asset_key] = replace(
        state,
        event=event.event,
        at=event.at,
        asset=_event_asset(event) or state.asset,
        failure=None,
        job_id=_string_data(event, "job_id") or state.job_id,
        output_prefix=_string_data(event, "output_prefix") or state.output_prefix,
        output_uris=_tuple_data(event, "output_uris") or state.output_uris,
    )
    return states


def project_current(events: Iterable[LedgerEvent]) -> CurrentState:
    """Replay events into the latest successful lifecycle state."""
    states: CurrentState = {}
    for event in events:
        apply_event(states, event)
    return states


def load_current(path: Path, expected_config_sha256: str | None = None) -> CurrentState:
    return project_current(read_events(path, expected_config_sha256))


def assets_at(current: CurrentState, event: str) -> list[CurrentAssetState]:
    return [state for state in current.values() if state.event == event and state.asset is not None]


def eligible_source_assets(current: CurrentState, now: float | None = None) -> list[CurrentAssetState]:
    """Select discovered source assets that are not permanently or temporarily deferred."""
    now = time.time() if now is None else now
    eligible: list[CurrentAssetState] = []
    for state in assets_at(current, "source_discovered"):
        failure = state.failure
        if failure is None:
            eligible.append(state)
            continue
        if not failure.retryable:
            continue
        if failure.retry_not_before is None or failure.retry_not_before <= now:
            eligible.append(state)
    return eligible


def _event_asset(event: LedgerEvent) -> SourceAsset | None:
    asset = event.data.get("asset")
    return source_asset_from_dict(asset) if isinstance(asset, dict) else None


def _failure_from_event(event: LedgerEvent) -> FailureState:
    return FailureState(
        at=event.at,
        stage=_string_data(event, "stage") or "unknown",
        error=_string_data(event, "error") or "unknown",
        retryable=bool(event.data.get("retryable", True)),
        attempts=int(event.data.get("attempts", 1)),
        retry_not_before=float(event.data["retry_not_before"]) if "retry_not_before" in event.data else None,
    )


def _string_data(event: LedgerEvent, field: str) -> str | None:
    value = event.data.get(field)
    return str(value) if value is not None else None


def _tuple_data(event: LedgerEvent, field: str) -> tuple[str, ...]:
    value = event.data.get(field)
    return tuple(str(item) for item in value) if isinstance(value, list) else ()
