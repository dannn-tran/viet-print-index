"""Path-bound event-store interface for append-only event records."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from vie_doc_pipeline.ledger.events import EventRecord
from vie_doc_pipeline.ledger.locking import _advisory_file_lock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventStore:
    """Persist and stream events without applying domain projections."""

    _path: Path

    @classmethod
    def open(cls, path: Path) -> "EventStore":
        """Bind an event store to one append-only event file."""
        store = cls(path)
        store._repair_trailing_record()
        return store

    def iter_events(self) -> Iterator[EventRecord]:
        """Stream events in their persisted order."""
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    event = EventRecord.from_dict(json.loads(line))
                except (ValueError, json.JSONDecodeError) as error:
                    raise ValueError(f"Invalid event record at {self._path}:{line_number}") from error
                yield event

    def first_event(self) -> EventRecord | None:
        """Return the initial event, or ``None`` when the store is empty."""
        return next(self.iter_events(), None)

    def append(self, event: EventRecord) -> None:
        """Append one event atomically with the store's file lock."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _advisory_file_lock(self._path.with_suffix(self._path.suffix + ".lock")):
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _repair_trailing_record(self) -> bool:
        """Discard an incomplete final record left by an interrupted append."""
        if not self._path.exists():
            return False
        with _advisory_file_lock(self._path.with_suffix(self._path.suffix + ".lock")):
            with self._path.open("rb+") as handle:
                handle.seek(0, os.SEEK_END)
                end = handle.tell()
                if not end:
                    return False
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) == b"\n":
                    return False

                start = end - 1
                while start > 0:
                    start -= 1
                    handle.seek(start)
                    if handle.read(1) == b"\n":
                        start += 1
                        break
                handle.seek(start)
                tail = handle.read()
                try:
                    event = json.loads(tail.decode("utf-8"))
                    EventRecord.from_dict(event)
                except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                    handle.truncate(start)
                    handle.flush()
                    os.fsync(handle.fileno())
                    logger.warning("Removed incomplete final event record from %s", self._path)
                    return True
                return False
