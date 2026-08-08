"""Private advisory file-lock primitive used for atomic event appends."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Generator


@contextmanager
def _advisory_file_lock(path: Path) -> Generator[None, None, None]:
    """Hold an advisory exclusive lock for one atomic file operation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
