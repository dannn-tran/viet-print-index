"""Stable records shared by discovery, fetch, OCR, and indexing stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal


AssetKind = Literal["pdf", "image"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class PageAsset:
    """One source page that can be fetched, OCRed, and indexed independently."""

    publication_id: str
    issue_id: str
    page_id: str
    source_url: str
    object_name: str
    kind: AssetKind = "image"
    width: int | None = None
    height: int | None = None

    @property
    def key(self) -> str:
        return f"{self.publication_id}/{self.issue_id}/{self.page_id}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StateEvent:
    """An append-only transition in the state ledger."""

    event: Literal["discovered", "fetched", "ocr_submitted", "ocr_completed", "ocr_failed", "indexed", "failed"]
    asset_key: str
    at: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"event": self.event, "asset_key": self.asset_key, "at": self.at, "data": self.data}
