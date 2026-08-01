"""Path-bound event-store interface for the append-only ledger."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from vie_doc_pipeline.ledger.events import LedgerEvent
from vie_doc_pipeline.ledger.jsonl import _append_event, _read_events
from vie_doc_pipeline.ledger.locking import advisory_file_lock


@dataclass(frozen=True)
class EventStore:
    """Persist and stream events without applying domain projections."""

    _path: Path

    @classmethod
    def open(cls, path: Path) -> "EventStore":
        """Bind an event store to one append-only event file."""
        return cls(path)

    def read_events(self) -> Iterator[LedgerEvent]:
        """Stream events in their persisted order."""
        yield from _read_events(self._path)

    def append(self, event: LedgerEvent) -> None:
        """Append one event atomically with the store's file lock."""
        _append_event(self._path, event)

    @contextmanager
    def lock(self, suffix: str, *, non_blocking: bool = False) -> Iterator[None]:
        """Hold a named exclusive lock owned by this event store."""
        with advisory_file_lock(
            self._path.with_suffix(self._path.suffix + suffix),
            non_blocking=non_blocking,
        ):
            yield
