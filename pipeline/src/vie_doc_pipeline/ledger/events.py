"""Construct typed facts recorded by the pipeline ledger."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from vie_doc_pipeline.models import LedgerEvent, SourceAsset, utc_now

Asset = SourceAsset


def source_discovered(asset: Asset) -> LedgerEvent:
    return _event("source_discovered", asset.key, {"asset": asset.to_dict()})


def source_downloaded(asset: Asset, *, checksum: str, size_bytes: int) -> LedgerEvent:
    return _event("source_downloaded", asset.key, {"checksum": checksum, "size_bytes": size_bytes})


def image_normalized(asset: Asset) -> LedgerEvent:
    return _event("image_normalized", asset.key, {"asset": asset.to_dict()})


def ocr_job_submitted(asset_keys: Iterable[str], *, job_id: str, output_prefix: str) -> list[LedgerEvent]:
    return [_event("ocr_job_submitted", key, {"job_id": job_id, "output_prefix": output_prefix}) for key in asset_keys]


def ocr_output_available(asset_keys: Iterable[str], *, output_uris: list[str]) -> list[LedgerEvent]:
    return [_event("ocr_output_available", key, {"output_uris": output_uris}) for key in asset_keys]


def failed(asset_key: str, *, stage: str, error: str) -> LedgerEvent:
    return _event("failed", asset_key, {"stage": stage, "error": error})


def source_inverted(source_id: str) -> LedgerEvent:
    return _event("source_inverted", source_id, {"inverted": True})


def image_inverted(image_key: str) -> LedgerEvent:
    return _event("image_inverted", image_key, {"inverted": True})


EventName = Literal[
    "source_discovered", "source_downloaded", "image_normalized",
    "ocr_job_submitted", "ocr_output_available", "source_inverted", "image_inverted", "failed",
]


def _event(event: EventName, asset_key: str, data: dict[str, object]) -> LedgerEvent:
    return LedgerEvent(event=event, asset_key=asset_key, at=utc_now(), data=data)
