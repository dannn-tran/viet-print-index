"""Stable records shared by discovery, fetch, OCR, and indexing stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal


AssetKind = Literal["pdf", "image"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class DocumentAsset:
    """A fetched source document that may need to be materialised into pages."""

    publication_id: str
    document_id: str
    source_url: str
    object_name: str
    kind: Literal["pdf"] = "pdf"

    @property
    def key(self) -> str:
        return f"{self.publication_id}/document/{self.document_id}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "DocumentAsset":
        return cls(
            publication_id=str(raw["publication_id"]),
            document_id=str(raw["document_id"]),
            source_url=str(raw["source_url"]),
            object_name=str(raw["object_name"]),
        )


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

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "PageAsset":
        return cls(
            publication_id=str(raw["publication_id"]),
            issue_id=str(raw["issue_id"]),
            page_id=str(raw["page_id"]),
            source_url=str(raw["source_url"]),
            object_name=str(raw["object_name"]),
            kind=str(raw.get("kind", "image")),  # type: ignore[arg-type]
            width=int(raw["width"]) if raw.get("width") is not None else None,
            height=int(raw["height"]) if raw.get("height") is not None else None,
        )


@dataclass(frozen=True)
class StateEvent:
    """An append-only transition in the state ledger."""

    event: Literal["discovered", "fetched", "materialized", "ocr_submitted", "ocr_completed", "ocr_failed", "indexed", "failed"]
    asset_key: str
    at: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"event": self.event, "asset_key": self.asset_key, "at": self.at, "data": self.data}
