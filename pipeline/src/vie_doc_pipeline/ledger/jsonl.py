"""File-locked JSONL persistence for ledger events."""

from __future__ import annotations

import json
from pathlib import Path

from vie_doc_pipeline.ledger.locking import ledger_write_lock
from vie_doc_pipeline.ledger.models import LedgerEvent


def append_event(path: Path, event: LedgerEvent) -> None:
    """Append one event while holding a process-wide advisory file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_write_lock(path.with_suffix(path.suffix + ".lock")):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()


def read_events(path: Path) -> list[LedgerEvent]:
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
    return result
