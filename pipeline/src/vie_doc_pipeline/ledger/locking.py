"""Process-scoped locks for commands that contact one external collection."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def source_download_lock(ledger_path: Path) -> Iterator[None]:
    """Allow only one source-download command per publication ledger."""
    path = ledger_path.with_suffix(ledger_path.suffix + ".source-download.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"Another source-download command is already running for {ledger_path.stem}") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def ledger_write_lock(path: Path) -> Iterator[None]:
    """Hold the advisory lock used while appending one ledger event."""
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
