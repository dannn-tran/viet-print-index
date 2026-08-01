"""File-locked JSONL persistence for ledger events."""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from vie_doc_pipeline.models import LedgerEvent


def append_event(path: Path, event: LedgerEvent) -> None:
    """Append one event while holding a process-wide advisory file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path.with_suffix(path.suffix + ".lock")):
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
                raw = json.loads(line)
                result.append(LedgerEvent(event=raw["event"], asset_key=raw["asset_key"], at=raw["at"], data=raw["data"]))  # type: ignore[arg-type]
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid ledger event at {path}:{line_number}") from error
    return result


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
