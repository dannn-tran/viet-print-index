"""Bind a pipeline configuration to an append-only event store."""

from __future__ import annotations

import hashlib

from vie_doc_pipeline.config import ConfigSnapshot
from vie_doc_pipeline.ledger.events import LedgerEvent, ledger_initialized
from vie_doc_pipeline.ledger.store import EventStore


class ConfigMismatchError(ValueError):
    """Raised when an event store belongs to another configuration."""


def ensure_config_compatible(event_store: EventStore, snapshot: ConfigSnapshot | None) -> None:
    """Record the config snapshot once and reject incompatible future runs."""
    if snapshot is None:
        return
    if hashlib.sha256(snapshot.toml.encode("utf-8")).hexdigest() != snapshot.sha256:
        raise ConfigMismatchError("Current TOML configuration does not match its SHA-256")

    event_store.repair_trailing_record()
    has_events = False
    records: set[tuple[str, str]] = set()
    for event in event_store.read_events():
        has_events = True
        record = _config_record(event)
        if record is not None:
            records.add(record)
    if len(records) > 1:
        raise ConfigMismatchError("Event store contains multiple configuration snapshots")

    recorded = next(iter(records), None)
    if recorded is None:
        if has_events:
            raise ConfigMismatchError(
                "Event store has no configuration snapshot; refusing to mix it with the current configuration"
            )
        event_store.append(ledger_initialized(snapshot.sha256, snapshot.toml))
        return

    expected = (snapshot.sha256, snapshot.toml)
    if recorded != expected:
        raise ConfigMismatchError(
            f"Event store belongs to TOML SHA-256 {recorded[0]}, not {snapshot.sha256}"
        )


def _config_record(event: LedgerEvent) -> tuple[str, str] | None:
    if event.event != "ledger_initialized":
        return None
    sha256 = event.data.get("config_sha256")
    snapshot = event.data.get("config_snapshot")
    if not isinstance(sha256, str) or not _is_sha256(sha256):
        raise ConfigMismatchError("Event store contains an invalid TOML SHA-256")
    if not isinstance(snapshot, str):
        raise ConfigMismatchError("Event store contains no TOML configuration snapshot")
    if hashlib.sha256(snapshot.encode("utf-8")).hexdigest() != sha256:
        raise ConfigMismatchError("Event store configuration snapshot does not match its SHA-256")
    return sha256, snapshot


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
