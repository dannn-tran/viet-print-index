"""Private advisory file-lock primitives used by the event store."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockUnavailableError(RuntimeError):
    """Raised when a non-blocking advisory lock is already held."""


@contextmanager
def _advisory_file_lock(path: Path, *, non_blocking: bool = False) -> Iterator[None]:
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
