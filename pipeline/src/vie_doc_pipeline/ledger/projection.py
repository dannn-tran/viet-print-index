"""Current application state and projection helpers over event history."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import time

from vie_doc_pipeline.ledger.events import EventRecord, configuration_bound
from vie_doc_pipeline.ledger.store import EventStore
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


@dataclass(frozen=True)
class InversionOverrides:
    source_ids: frozenset[str]
    image_keys: frozenset[str]


class ConfigurationMismatchError(ValueError):
    """Raised when an event store belongs to another configuration."""


@dataclass
class AppState:
    """Current projection coupled to the event store that records it."""

    event_store: EventStore
    current: CurrentState
    source_inversion_overrides: frozenset[str] = frozenset()

    @property
    def inversion_overrides(self) -> InversionOverrides:
        """Return explicit inversion decisions projected from the event history."""
        return InversionOverrides(
            source_ids=self.source_inversion_overrides,
            image_keys=frozenset(
                key for key, state in self.current.items() if state.inverted_override
            ),
        )

    @classmethod
    def replay(cls, event_store: EventStore) -> "AppState":
        """Rebuild current state by applying persisted events in order."""
        state = cls(event_store, {})
        for event in event_store.iter_events():
            state._apply(event)
        return state

    @classmethod
    def open(cls, state_path: Path, config_toml: str | None) -> "AppState":
        """Open, replay, and bind one application state to its configuration."""
        state = cls.replay(EventStore.open(state_path))
        state.bind_configuration(config_toml)
        return state

    def bind_configuration(self, config_toml: str | None) -> None:
        """Record the initial TOML configuration or reject a mismatch."""
        if config_toml is None:
            return

        first = self.event_store.first_event()
        if first is None:
            self.record(configuration_bound(config_toml))
            return
        if first.event != "configuration_bound":
            raise ConfigurationMismatchError(
                "Event store has no bound TOML configuration as its first event",
            )
        recorded = first.data.get("config_toml")
        if not isinstance(recorded, str):
            raise ConfigurationMismatchError("Event store contains no TOML configuration")
        if recorded != config_toml:
            raise ConfigurationMismatchError(
                "Event store belongs to a different TOML configuration",
            )

    def record(self, event: EventRecord) -> None:
        """Append an event, then apply it to the live projection."""
        self.event_store.append(event)
        self._apply(event)

    def _apply(self, event: EventRecord) -> None:
        self.current = apply_event(self.current, event)
        if event.event == "source_inverted":
            self.source_inversion_overrides = self.source_inversion_overrides | {event.asset_key}


def apply_event(states: CurrentState, event: EventRecord) -> CurrentState:
    """Apply one event to a mutable projection and return that projection."""
    if event.event == "configuration_bound":
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


def _event_asset(event: EventRecord) -> SourceAsset | None:
    asset = event.data.get("asset")
    return source_asset_from_dict(asset) if isinstance(asset, dict) else None


def _failure_from_event(event: EventRecord) -> FailureState:
    return FailureState(
        at=event.at,
        stage=_string_data(event, "stage") or "unknown",
        error=_string_data(event, "error") or "unknown",
        retryable=bool(event.data.get("retryable", True)),
        attempts=int(event.data.get("attempts", 1)),
        retry_not_before=float(event.data["retry_not_before"]) if "retry_not_before" in event.data else None,
    )


def _string_data(event: EventRecord, field: str) -> str | None:
    value = event.data.get(field)
    return str(value) if value is not None else None


def _tuple_data(event: EventRecord, field: str) -> tuple[str, ...]:
    value = event.data.get(field)
    return tuple(str(item) for item in value) if isinstance(value, list) else ()
