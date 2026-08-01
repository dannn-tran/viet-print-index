"""Process-scoped locks for commands that contact one external collection."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from vie_doc_pipeline.ledger.store import EventStore


class LockUnavailableError(RuntimeError):
    """Raised when a non-blocking advisory lock is already held."""


@contextmanager
def source_fetch_lock(event_store: "EventStore") -> Iterator[None]:
    """Allow only one source-fetch command per event store."""
    try:
        with event_store.lock(".source-fetch.lock", non_blocking=True):
            yield
    except LockUnavailableError as error:
        raise RuntimeError("Another source-fetch command is already running") from error


@contextmanager
def event_store_write_lock(path: Path) -> Iterator[None]:
    """Hold the advisory lock used while appending one event record."""
    with advisory_file_lock(path):
        yield


@contextmanager
def advisory_file_lock(path: Path, *, non_blocking: bool = False) -> Iterator[None]:
    """Hold an advisory exclusive lock for one file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        operation = fcntl.LOCK_EX | (fcntl.LOCK_NB if non_blocking else 0)
        try:
            fcntl.flock(handle.fileno(), operation)
        except BlockingIOError as error:
            if non_blocking:
                raise LockUnavailableError from error
            raise
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
