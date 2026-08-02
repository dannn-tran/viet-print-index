"""Event-backed pipeline state and its asset lifecycle projection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import time

from vie_doc_pipeline.config import PipelineConfig
from vie_doc_pipeline.ledger.events import EventRecord, configuration_bound
from vie_doc_pipeline.ledger.store import EventStore
from vie_doc_pipeline.assets import SourceAsset, _source_asset_from_dict


@dataclass(frozen=True)
class FailureState:
    at: str
    stage: str
    error: str
    retryable: bool
    attempts: int
    retry_not_before: float | None


@dataclass(frozen=True)
class AssetState:
    event: str | None = None
    at: str | None = None
    asset: SourceAsset | None = None
    failure: FailureState | None = None
    inverted_override: bool = False
    job_id: str | None = None
    output_prefix: str | None = None
    output_uris: tuple[str, ...] = ()


@dataclass(frozen=True)
class InversionOverrides:
    source_ids: frozenset[str]
    image_keys: frozenset[str]


class ConfigurationMismatchError(ValueError):
    """Raised when an event store belongs to another configuration."""


@dataclass
class PipelineState:
    """Event-backed pipeline state and its private asset projection."""

    _event_store: EventStore
    _assets: dict[str, AssetState]
    _config: PipelineConfig
    _source_inversion_overrides: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self._config.config_toml is None:
            raise ValueError("PipelineState requires a configuration loaded from TOML")

    @property
    def inversion_overrides(self) -> InversionOverrides:
        """Return explicit inversion decisions projected from the event history."""
        return InversionOverrides(
            source_ids=self._source_inversion_overrides,
            image_keys=frozenset(
                key for key, state in self._assets.items() if state.inverted_override
            ),
        )

    @property
    def configuration(self) -> PipelineConfig:
        """Return the immutable configuration for this job run."""
        return self._config

    def asset_keys(self) -> tuple[str, ...]:
        """Return the keys of all assets currently known to the projection."""
        return tuple(self._assets)

    def asset_states(self) -> tuple[AssetState, ...]:
        """Return a stable snapshot of all projected asset states."""
        return tuple(self._assets.values())

    def asset_state(self, asset_key: str) -> AssetState | None:
        """Return the projected state for one asset, if known."""
        return self._assets.get(asset_key)

    def asset_states_with_event(self, event: str) -> tuple[AssetState, ...]:
        """Return asset states whose latest lifecycle event matches."""
        return tuple(
            state
            for state in self._assets.values()
            if state.event == event and state.asset is not None
        )

    def eligible_source_assets(self, now: float | None = None) -> tuple[SourceAsset, ...]:
        """Return discovered source assets eligible for another fetch attempt."""
        current_time = time.time() if now is None else now
        eligible: list[SourceAsset] = []
        for state in self.asset_states_with_event("source_discovered"):
            failure = state.failure
            if failure is None:
                eligible.append(state.asset)
                continue
            if failure.retryable and (
                failure.retry_not_before is None or failure.retry_not_before <= current_time
            ):
                eligible.append(state.asset)
        return tuple(eligible)

    def reprocessable_assets(self) -> tuple[tuple[str, SourceAsset], ...]:
        """Return source and image assets eligible for explicit reprocessing."""
        return tuple(
            (key, state.asset)
            for key, state in self._assets.items()
            if state.asset is not None and state.event in {"source_fetched", "image_normalized"}
        )

    @classmethod
    def open(cls, state_path: Path, config: PipelineConfig) -> "PipelineState":
        """Open, replay, and register one pipeline state configuration."""
        if config.config_toml is None:
            raise ValueError("PipelineState requires a configuration loaded from TOML")
        event_store = EventStore.open(state_path)
        state = cls(event_store, {}, config)
        state._register_configuration()
        for event in event_store.iter_events():
            state._apply(event)
        return state

    def _register_configuration(self) -> None:
        """Record this run's configuration or validate the existing first event."""
        config_toml = self._config.config_toml
        if config_toml is None:
            raise ValueError("PipelineState requires a configuration loaded from TOML")
        first = self._event_store.first_event()
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
        self._event_store.append(event)
        self._apply(event)

    def _apply(self, event: EventRecord) -> None:
        if event.event == "configuration_bound":
            return
        if event.event == "source_inverted":
            self._source_inversion_overrides = self._source_inversion_overrides | {event.asset_key}
            return
        current = self._assets.get(event.asset_key, AssetState())
        self._assets[event.asset_key] = _asset_state_after_event(current, event)


def _asset_state_after_event(state: AssetState, event: EventRecord) -> AssetState:
    """Apply one lifecycle event to one asset state."""
    if event.event == "failed":
        return replace(state, failure=_failure_from_event(event))
    if event.event == "image_inverted":
        return replace(state, inverted_override=True)
    return replace(
        state,
        event=event.event,
        at=event.at,
        asset=_event_asset(event) or state.asset,
        failure=None,
        job_id=_string_data(event, "job_id") or state.job_id,
        output_prefix=_string_data(event, "output_prefix") or state.output_prefix,
        output_uris=_tuple_data(event, "output_uris") or state.output_uris,
    )


def _event_asset(event: EventRecord) -> SourceAsset | None:
    asset = event.data.get("asset")
    return _source_asset_from_dict(asset) if isinstance(asset, dict) else None


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
