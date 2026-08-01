"""Construct typed facts recorded by the pipeline event store."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Literal

from vie_doc_pipeline.assets import SourceAsset

Asset = SourceAsset


@dataclass(frozen=True)
class EventRecord:
    """An append-only transition in the asset lifecycle."""

    event: Literal[
        "configuration_bound", "source_discovered", "source_fetched", "image_normalized",
        "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
    ]
    asset_key: str
    at: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"event": self.event, "asset_key": self.asset_key, "at": self.at, "data": self.data}

    @classmethod
    def from_dict(cls, raw: object) -> "EventRecord":
        if not isinstance(raw, dict):
            raise ValueError("event record must be an object")
        event = raw.get("event")
        asset_key = raw.get("asset_key")
        at = raw.get("at")
        data = raw.get("data")
        if event not in _EVENT_NAMES:
            raise ValueError(f"unknown event record {event!r}")
        if not isinstance(asset_key, str) or not isinstance(at, str) or not isinstance(data, dict):
            raise ValueError("event record has invalid fields")
        return cls(event=event, asset_key=asset_key, at=at, data=data)


_EVENT_NAMES = {
    "configuration_bound", "source_discovered", "source_fetched", "image_normalized",
    "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def configuration_bound(config_toml: str) -> EventRecord:
    return _event(
        "configuration_bound",
        "__configuration__",
        {"config_toml": config_toml},
    )


def source_discovered(asset: Asset) -> EventRecord:
    return _event("source_discovered", asset.key, {"asset": asset.to_dict()})


def source_fetched(asset: Asset, *, checksum: str, size_bytes: int) -> EventRecord:
    return _event("source_fetched", asset.key, {"checksum": checksum, "size_bytes": size_bytes})


def image_normalized(asset: Asset) -> EventRecord:
    return _event("image_normalized", asset.key, {"asset": asset.to_dict()})


def ocr_job_submitted(asset_keys: Iterable[str], *, job_id: str, output_prefix: str) -> list[EventRecord]:
    return [_event("ocr_job_submitted", key, {"job_id": job_id, "output_prefix": output_prefix}) for key in asset_keys]


def ocr_output_available(asset_keys: Iterable[str], *, output_uris: list[str]) -> list[EventRecord]:
    return [_event("ocr_output_available", key, {"output_uris": output_uris}) for key in asset_keys]


def failed(
    asset_key: str,
    *,
    stage: str,
    error: str,
    retryable: bool = True,
    attempts: int = 1,
    retry_not_before: float | None = None,
) -> EventRecord:
    data: dict[str, object] = {
        "stage": stage,
        "error": error,
        "retryable": retryable,
        "attempts": attempts,
    }
    if retry_not_before is not None:
        data["retry_not_before"] = retry_not_before
    return _event("failed", asset_key, data)


def source_inverted(source_id: str) -> EventRecord:
    return _event("source_inverted", source_id, {"inverted": True})


def image_inverted(image_key: str) -> EventRecord:
    return _event("image_inverted", image_key, {"inverted": True})


EventName = Literal[
    "configuration_bound", "source_discovered", "source_fetched", "image_normalized",
    "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
]


def _event(event: EventName, asset_key: str, data: dict[str, object]) -> EventRecord:
    return EventRecord(event=event, asset_key=asset_key, at=utc_now(), data=data)
