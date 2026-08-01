"""Bind one pipeline run's configuration to its event-store history."""

from __future__ import annotations

from vie_doc_pipeline.ledger.events import EventRecord, configuration_bound
from vie_doc_pipeline.ledger.store import EventStore


class ConfigMismatchError(ValueError):
    """Raised when an event store belongs to another configuration."""


def bind_configuration(event_store: EventStore, config_toml: str | None) -> None:
    """Record the run's exact TOML once and reject incompatible future runs."""
    if config_toml is None:
        return

    event_store.repair_trailing_record()
    has_events = False
    records: set[str] = set()
    for event in event_store.iter_events():
        has_events = True
        record = _recorded_config_toml(event)
        if record is not None:
            records.add(record)
    if len(records) > 1:
        raise ConfigMismatchError("Event store contains multiple TOML configurations")

    recorded = next(iter(records), None)
    if recorded is None:
        if has_events:
            raise ConfigMismatchError(
                "Event store has no bound TOML configuration; refusing to mix it with the current configuration",
            )
        event_store.append(configuration_bound(config_toml))
        return

    if recorded != config_toml:
        raise ConfigMismatchError(
            "Event store belongs to a different TOML configuration",
        )


def _recorded_config_toml(event: EventRecord) -> str | None:
    if event.event != "configuration_bound":
        return None
    config_toml = event.data.get("config_toml")
    if not isinstance(config_toml, str):
        raise ConfigMismatchError("Event store contains no TOML configuration")
    return config_toml
