"""Path-bound event-store interface for the append-only ledger."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from vie_doc_pipeline.ledger.events import LedgerEvent
from vie_doc_pipeline.ledger.jsonl import append_event, read_events


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
        yield from read_events(self._path)

    def append(self, event: LedgerEvent) -> None:
        """Append one event atomically with the store's file lock."""
        append_event(self._path, event)
