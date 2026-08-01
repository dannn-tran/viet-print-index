"""Immutable records exchanged between source discovery and pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SourceItem:
    kind: Literal["pdf", "image"]
    source_url: str
    issue_id: str | None = None
    page_id: str | None = None
    width: int | None = None
    height: int | None = None
