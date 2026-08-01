"""Immutable records shared across source discovery and pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal


AssetKind = Literal["pdf", "image"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class DiscoveredSourceItem:
    """One source document or native image discovered by an adapter."""

    kind: AssetKind
    source_url: str
    issue_id: str | None = None
    page_id: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class PdfAsset:
    """A fetched source document that may need to be materialised into pages."""

    publication_id: str
    document_id: str
    source_url: str
    gcs_object: str
    kind: Literal["pdf"] = "pdf"

    @property
    def key(self) -> str:
        return f"{self.publication_id}/document/{self.document_id}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "PdfAsset":
        return cls(
            publication_id=str(raw["publication_id"]),
            document_id=str(raw["document_id"]),
            source_url=str(raw["source_url"]),
            gcs_object=str(raw["gcs_object"]),
        )


@dataclass(frozen=True)
class ImageAsset:
    """One image asset for presentation and OCR, including spreads or covers."""

    publication_id: str
    issue_id: str
    page_id: str
    source_url: str
    gcs_object: str
    kind: AssetKind = "image"
    width: int | None = None
    height: int | None = None

    @property
    def key(self) -> str:
        return f"{self.publication_id}/{self.issue_id}/{self.page_id}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "ImageAsset":
        return cls(
            publication_id=str(raw["publication_id"]),
            issue_id=str(raw["issue_id"]),
            page_id=str(raw["page_id"]),
            source_url=str(raw["source_url"]),
            gcs_object=str(raw["gcs_object"]),
            kind=str(raw.get("kind", "image")),  # type: ignore[arg-type]
            width=int(raw["width"]) if raw.get("width") is not None else None,
            height=int(raw["height"]) if raw.get("height") is not None else None,
        )


# A native image is both the original source object and, when unchanged, its
# own presentation/OCR image asset. PDFs become image assets during normalization.
SourceAsset = PdfAsset | ImageAsset


@dataclass(frozen=True)
class LedgerEvent:
    """An append-only transition in the state ledger."""

    event: Literal[
        "source_discovered", "source_downloaded", "image_normalized",
        "ocr_job_submitted", "ocr_output_available", "failed",
    ]
    asset_key: str
    at: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"event": self.event, "asset_key": self.asset_key, "at": self.at, "data": self.data}
