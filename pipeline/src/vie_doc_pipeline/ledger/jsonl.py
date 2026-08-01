"""File-locked JSONL persistence for ledger events."""

from __future__ import annotations

import json
from pathlib import Path

from vie_doc_pipeline.ledger.events import LedgerEvent, ledger_initialized
from vie_doc_pipeline.ledger.locking import ledger_write_lock


class LedgerConfigMismatchError(ValueError):
    """Raised when a ledger is used with a different TOML configuration."""


def append_event(path: Path, event: LedgerEvent) -> None:
    """Append one event while holding a process-wide advisory file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_write_lock(path.with_suffix(path.suffix + ".lock")):
        _append_event(path, event)


def ensure_ledger_config(path: Path, config_sha256: str | None) -> None:
    """Record and validate the exact TOML fingerprint associated with a ledger."""
    if config_sha256 is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_write_lock(path.with_suffix(path.suffix + ".lock")):
        events = read_events(path)
        recorded = _recorded_config_hash(events)
        if recorded is not None and recorded != config_sha256:
            raise LedgerConfigMismatchError(
                f"Ledger {path} belongs to TOML SHA-256 {recorded}, not {config_sha256}"
            )
        if recorded is None and events:
            raise LedgerConfigMismatchError(
                f"Ledger {path} has no TOML fingerprint; refusing to mix it with the current configuration"
            )
        if recorded is None:
            _append_event(path, ledger_initialized(config_sha256))


def read_events(path: Path, expected_config_sha256: str | None = None) -> list[LedgerEvent]:
    if not path.exists():
        return []
    result: list[LedgerEvent] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                result.append(LedgerEvent.from_dict(json.loads(line)))
            except (ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid ledger event at {path}:{line_number}") from error
    if expected_config_sha256 is not None:
        _validate_config_hash(path, result, expected_config_sha256)
    return result


def _append_event(path: Path, event: LedgerEvent) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def _recorded_config_hash(events: list[LedgerEvent]) -> str | None:
    hashes: set[str] = set()
    for event in events:
        if event.event != "ledger_initialized":
            continue
        value = event.data.get("config_sha256")
        if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise LedgerConfigMismatchError("Ledger contains an invalid TOML SHA-256 fingerprint")
        hashes.add(value)
    if len(hashes) > 1:
        raise LedgerConfigMismatchError("Ledger contains multiple TOML fingerprints")
    return next(iter(hashes), None)


def _validate_config_hash(path: Path, events: list[LedgerEvent], expected: str) -> None:
    recorded = _recorded_config_hash(events)
    if recorded != expected:
        if recorded is None:
            raise LedgerConfigMismatchError(f"Ledger {path} has no TOML fingerprint")
        raise LedgerConfigMismatchError(
            f"Ledger {path} belongs to TOML SHA-256 {recorded}, not {expected}"
        )
