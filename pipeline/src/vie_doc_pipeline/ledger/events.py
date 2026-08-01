"""Construct typed facts recorded by the pipeline ledger."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Literal

from vie_doc_pipeline.assets import SourceAsset

Asset = SourceAsset


@dataclass(frozen=True)
class LedgerEvent:
    """An append-only transition in the asset lifecycle."""

    event: Literal[
        "ledger_initialized", "source_discovered", "source_downloaded", "image_normalized",
        "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
    ]
    asset_key: str
    at: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"event": self.event, "asset_key": self.asset_key, "at": self.at, "data": self.data}

    @classmethod
    def from_dict(cls, raw: object) -> "LedgerEvent":
        if not isinstance(raw, dict):
            raise ValueError("ledger event must be an object")
        event = raw.get("event")
        asset_key = raw.get("asset_key")
        at = raw.get("at")
        data = raw.get("data")
        if event not in _EVENT_NAMES:
            raise ValueError(f"unknown ledger event {event!r}")
        if not isinstance(asset_key, str) or not isinstance(at, str) or not isinstance(data, dict):
            raise ValueError("ledger event has invalid fields")
        return cls(event=event, asset_key=asset_key, at=at, data=data)


_EVENT_NAMES = {
    "ledger_initialized", "source_discovered", "source_downloaded", "image_normalized",
    "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ledger_initialized(config_sha256: str, config_snapshot: str) -> LedgerEvent:
    return _event(
        "ledger_initialized",
        "__ledger__",
        {"config_sha256": config_sha256, "config_snapshot": config_snapshot},
    )


def source_discovered(asset: Asset) -> LedgerEvent:
    return _event("source_discovered", asset.key, {"asset": asset.to_dict()})


def source_fetched(asset: Asset, *, checksum: str, size_bytes: int) -> LedgerEvent:
    """Record a fetched source using the established serialized event name."""
    return _event("source_downloaded", asset.key, {"checksum": checksum, "size_bytes": size_bytes})


def source_downloaded(asset: Asset, *, checksum: str, size_bytes: int) -> LedgerEvent:
    """Backward-compatible constructor for the historical event name."""
    return source_fetched(asset, checksum=checksum, size_bytes=size_bytes)


def image_normalized(asset: Asset) -> LedgerEvent:
    return _event("image_normalized", asset.key, {"asset": asset.to_dict()})


def ocr_job_submitted(asset_keys: Iterable[str], *, job_id: str, output_prefix: str) -> list[LedgerEvent]:
    return [_event("ocr_job_submitted", key, {"job_id": job_id, "output_prefix": output_prefix}) for key in asset_keys]


def ocr_output_available(asset_keys: Iterable[str], *, output_uris: list[str]) -> list[LedgerEvent]:
    return [_event("ocr_output_available", key, {"output_uris": output_uris}) for key in asset_keys]


def failed(
    asset_key: str,
    *,
    stage: str,
    error: str,
    retryable: bool = True,
    attempts: int = 1,
    retry_not_before: float | None = None,
) -> LedgerEvent:
    data: dict[str, object] = {
        "stage": stage,
        "error": error,
        "retryable": retryable,
        "attempts": attempts,
    }
    if retry_not_before is not None:
        data["retry_not_before"] = retry_not_before
    return _event("failed", asset_key, data)


def source_inverted(source_id: str) -> LedgerEvent:
    return _event("source_inverted", source_id, {"inverted": True})


def image_inverted(image_key: str) -> LedgerEvent:
    return _event("image_inverted", image_key, {"inverted": True})


EventName = Literal[
    "ledger_initialized", "source_discovered", "source_downloaded", "image_normalized",
    "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
]


def _event(event: EventName, asset_key: str, data: dict[str, object]) -> LedgerEvent:
    return LedgerEvent(event=event, asset_key=asset_key, at=utc_now(), data=data)
