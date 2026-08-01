"""Private JSONL persistence for the event store."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from vie_doc_pipeline.ledger.events import EventRecord
from vie_doc_pipeline.ledger.locking import _advisory_file_lock


def _append_event(path: Path, event: EventRecord) -> None:
    """Append one event while holding a process-wide advisory file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _advisory_file_lock(path.with_suffix(path.suffix + ".lock")):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _read_events(path: Path) -> Iterator[EventRecord]:
    """Stream valid events from ``path`` in append order.

    Configuration compatibility is checked by the caller before replay.
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                event = EventRecord.from_dict(json.loads(line))
            except (ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid event record at {path}:{line_number}") from error
            yield event
