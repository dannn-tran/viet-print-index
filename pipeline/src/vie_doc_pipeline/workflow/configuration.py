"""Bind one pipeline run's configuration to its event-store history."""

from __future__ import annotations

from vie_doc_pipeline.ledger.events import configuration_bound
from vie_doc_pipeline.ledger.store import EventStore


class ConfigMismatchError(ValueError):
    """Raised when an event store belongs to another configuration."""


def bind_configuration(event_store: EventStore, config_toml: str | None) -> None:
    """Record the run's exact TOML once and reject incompatible future runs."""
    if config_toml is None:
        return

    first = event_store.first_event()
    if first is None:
        event_store.append(configuration_bound(config_toml))
        return

    if first.event != "configuration_bound":
        raise ConfigMismatchError(
            "Event store has no bound TOML configuration as its first event",
        )
    recorded = first.data.get("config_toml")
    if not isinstance(recorded, str):
        raise ConfigMismatchError("Event store contains no TOML configuration")
    if recorded != config_toml:
        raise ConfigMismatchError(
            "Event store belongs to a different TOML configuration",
        )
