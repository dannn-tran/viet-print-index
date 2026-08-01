"""Inspectable append-only JSONL ledger for pipeline state.

Each line records one state transition. The current state is reconstructed by
folding the log, so a failed or interrupted command never needs a separate
database migration or opaque checkpoint format.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from vie_doc_pipeline.models import DocumentAsset, PageAsset, StateEvent, utc_now


class JsonlStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record_discovered(self, asset: DocumentAsset | PageAsset) -> None:
        self.append("discovered", asset.key, {"asset": asset.to_dict()})

    def record_fetched(self, asset: DocumentAsset | PageAsset, *, checksum: str, size_bytes: int) -> None:
        self.append("fetched", asset.key, {"checksum": checksum, "size_bytes": size_bytes})

    def record_materialized(self, asset: DocumentAsset | PageAsset) -> None:
        self.append("materialized", asset.key, {"asset": asset.to_dict()})

    def record_ocr_submitted(self, asset_keys: Iterable[str], *, job_id: str, output_prefix: str) -> None:
        for asset_key in asset_keys:
            self.append("ocr_submitted", asset_key, {"job_id": job_id, "output_prefix": output_prefix})

    def record_ocr_completed(self, asset_keys: Iterable[str], *, output_uris: list[str]) -> None:
        for asset_key in asset_keys:
            self.append("ocr_completed", asset_key, {"output_uris": output_uris})

    def record_failure(self, asset_key: str, *, stage: str, error: str) -> None:
        self.append("failed", asset_key, {"stage": stage, "error": error})

    def append(self, event: str, asset_key: str, data: dict[str, object]) -> None:
        record = StateEvent(event=event, asset_key=asset_key, at=utc_now(), data=data)  # type: ignore[arg-type]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    def current(self) -> dict[str, dict[str, object]]:
        states: dict[str, dict[str, object]] = {}
        for event in self.events():
            state = states.setdefault(event.asset_key, {})
            state["event"] = event.event
            state["at"] = event.at
            state.update(event.data)
        return states

    def events(self) -> list[StateEvent]:
        if not self.path.exists():
            return []
        result: list[StateEvent] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                result.append(StateEvent(
                    event=raw["event"], asset_key=raw["asset_key"], at=raw["at"], data=raw["data"]
                ))
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid state event at {self.path}:{line_number}") from error
        return result


def default_state_path(publication_id: str, state_dir: Path = Path(".pipeline-state")) -> Path:
    return state_dir / f"{publication_id}.jsonl"
