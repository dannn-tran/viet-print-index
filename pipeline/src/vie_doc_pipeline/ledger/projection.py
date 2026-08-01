"""Pure projection and selection helpers over ledger history."""

from __future__ import annotations

from pathlib import Path
import time

from vie_doc_pipeline.ledger.jsonl import read_events
from vie_doc_pipeline.models import LedgerEvent

CurrentState = dict[str, dict[str, object]]


def project_current(events: list[LedgerEvent]) -> CurrentState:
    """Project latest successful lifecycle state while retaining last failures."""
    states: CurrentState = {}
    for event in events:
        state = states.setdefault(event.asset_key, {})
        if event.event == "failed":
            state["failure"] = {"at": event.at, **event.data}
            continue
        if event.event == "image_inverted":
            state["inverted_override"] = True
            continue
        if event.event == "source_inverted":
            continue
        state["event"] = event.event
        state["at"] = event.at
        state.update(event.data)
    return states


def load_current(path: Path) -> CurrentState:
    return project_current(read_events(path))


def assets_at(current: CurrentState, event: str) -> list[dict[str, object]]:
    return [state for state in current.values() if state.get("event") == event and "asset" in state]


def eligible_source_assets(current: CurrentState, now: float | None = None) -> list[dict[str, object]]:
    """Select discovered source assets that are not permanently or temporarily deferred."""
    now = time.time() if now is None else now
    eligible: list[dict[str, object]] = []
    for state in assets_at(current, "source_discovered"):
        failure = state.get("failure")
        if not isinstance(failure, dict):
            eligible.append(state)
            continue
        if not failure.get("retryable", True):
            continue
        retry_not_before = failure.get("retry_not_before")
        if retry_not_before is None or float(retry_not_before) <= now:
            eligible.append(state)
    return eligible
