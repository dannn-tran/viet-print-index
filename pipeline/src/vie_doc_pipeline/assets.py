"""Immutable asset records shared across workflow stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


AssetKind = Literal["pdf", "image"]


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
            publication_id=_required_string(raw, "publication_id"),
            document_id=_required_string(raw, "document_id"),
            source_url=_required_string(raw, "source_url"),
            gcs_object=_required_string(raw, "gcs_object"),
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
    issue_label: str | None = None
    inverted: bool = False
    needs_review: bool = False

    @property
    def key(self) -> str:
        return f"{self.publication_id}/{self.issue_id}/{self.page_id}"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "ImageAsset":
        kind = raw.get("kind", "image")
        if kind != "image":
            raise ValueError(f"Invalid image asset kind: {kind!r}")
        return cls(
            publication_id=_required_string(raw, "publication_id"),
            issue_id=_required_string(raw, "issue_id"),
            page_id=_required_string(raw, "page_id"),
            source_url=_required_string(raw, "source_url"),
            gcs_object=_required_string(raw, "gcs_object"),
            width=_optional_int(raw, "width"),
            height=_optional_int(raw, "height"),
            issue_label=_optional_string(raw, "issue_label"),
            inverted=_optional_bool(raw, "inverted", False),
            needs_review=_optional_bool(raw, "needs_review", False),
        )


# A native image is both the original source object and, when unchanged, its
# own presentation/OCR image asset. PDFs become image assets during normalization.
SourceAsset = PdfAsset | ImageAsset


def source_asset_from_dict(raw: dict[str, object]) -> SourceAsset:
    """Decode one JSONL asset payload at the persistence boundary."""
    kind = raw.get("kind")
    if kind == "pdf":
        return PdfAsset.from_dict(raw)
    if kind in (None, "image"):
        return ImageAsset.from_dict(raw)
    raise ValueError(f"Unknown source asset kind: {kind!r}")


def _required_string(raw: dict[str, object], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Asset field {field!r} must be a non-empty string")
    return value


def _optional_string(raw: dict[str, object], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Asset field {field!r} must be a string")
    return value


def _optional_int(raw: dict[str, object], field: str) -> int | None:
    value = raw.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Asset field {field!r} must be an integer")
    return value


def _optional_bool(raw: dict[str, object], field: str, default: bool) -> bool:
    value = raw.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"Asset field {field!r} must be true or false")
    return value
