"""Pure projection and selection helpers over ledger history."""

from __future__ import annotations

from pathlib import Path

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
        state["event"] = event.event
        state["at"] = event.at
        state.update(event.data)
    return states


def load_current(path: Path) -> CurrentState:
    return project_current(read_events(path))


def assets_at(current: CurrentState, event: str) -> list[dict[str, object]]:
    return [state for state in current.values() if state.get("event") == event and "asset" in state]
