"""Persistent OCR submission and reconciliation backed by the JSONL ledger."""

from __future__ import annotations

from google.cloud import storage

from gc_vision_adapter.ocr.run import RunBatchOcrCommand, submit_ocr_batches
from vie_doc_pipeline.domain import PageAsset
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.state import JsonlStateStore


def submit_ocr(config: PipelineConfig, state: JsonlStateStore, limit: int | None = None) -> int:
    current = state.current()
    assets = [
        PageAsset.from_dict(raw["asset"])
        for raw in current.values()
        if raw.get("event") == "fetched" and "asset" in raw
    ]
    if limit is not None:
        assets = assets[:limit]
    if not assets:
        return 0

    command = RunBatchOcrCommand(
        input_bucket=config.gcs.bucket,
        output_bucket=config.gcs.bucket,
        output_dir=config.gcs.ocr_output_prefix,
        language_hints=config.ocr.language_hints,
    )
    uri_to_asset = {f"gs://{config.gcs.bucket}/{asset.object_name}": asset for asset in assets}
    jobs = submit_ocr_batches(config.gcs.project, command, list(uri_to_asset))
    for job in jobs:
        state.record_ocr_submitted(
            [uri_to_asset[uri].key for uri in job.input_uris],
            job_id=job.job_id,
            output_prefix=job.output_prefix,
        )
    return len(assets)


def reconcile_ocr(config: PipelineConfig, state: JsonlStateStore) -> tuple[int, int]:
    """Mark submitted jobs complete once their expected output appears in GCS."""
    current = state.current()
    by_job: dict[tuple[str, str], list[str]] = {}
    for asset_key, raw in current.items():
        if raw.get("event") == "ocr_submitted":
            by_job.setdefault((str(raw["job_id"]), str(raw["output_prefix"])), []).append(asset_key)

    client = storage.Client(project=config.gcs.project)
    completed = 0
    pending = 0
    for (_, output_prefix), asset_keys in by_job.items():
        bucket_name, object_prefix = _parse_gs_uri(output_prefix)
        output_uris = [f"gs://{bucket_name}/{blob.name}" for blob in client.list_blobs(bucket_name, prefix=object_prefix)]
        if output_uris:
            state.record_ocr_completed(asset_keys, output_uris=output_uris)
            completed += len(asset_keys)
        else:
            pending += len(asset_keys)
    return completed, pending


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Expected GCS URI, got {uri!r}")
    bucket, _, prefix = uri[5:].partition("/")
    return bucket, prefix
