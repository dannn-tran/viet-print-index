"""Typed records persisted by the workflow ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LedgerEvent:
    """An append-only transition in the asset lifecycle."""

    event: Literal[
        "source_discovered", "source_downloaded", "image_normalized",
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
    "source_discovered", "source_downloaded", "image_normalized",
    "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
}
