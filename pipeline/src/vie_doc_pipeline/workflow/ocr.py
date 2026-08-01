"""Submit and check asynchronous OCR jobs for image assets."""

from pathlib import Path

from google.cloud import storage

from gc_vision_adapter.ocr.run import RunBatchOcrCommand, submit_ocr_batches
from vie_doc_pipeline.ledger.events import ocr_job_submitted, ocr_output_available
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.projection import assets_at, load_current
from vie_doc_pipeline.models import ImageAsset
from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.workflow.results import OcrStatusSummary


def submit_ocr_jobs(config: PipelineConfig, ledger_path: Path, limit: int | None = None) -> int:
    assets = [
        ImageAsset.from_dict(raw["asset"])
        for raw in assets_at(load_current(ledger_path), "image_normalized")
        if isinstance(raw.get("asset"), dict)
        and raw["asset"].get("kind", "image") == "image"
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
    uri_to_asset = {f"gs://{config.gcs.bucket}/{asset.gcs_object}": asset for asset in assets}
    jobs = submit_ocr_batches(config.gcs.project, command, list(uri_to_asset))
    for job in jobs:
        for event in ocr_job_submitted([uri_to_asset[uri].key for uri in job.input_uris], job_id=job.job_id, output_prefix=job.output_prefix):
            append_event(ledger_path, event)
    return len(assets)


def check_ocr_status(config: PipelineConfig, ledger_path: Path) -> OcrStatusSummary:
    """Check for OCR results in GCS and return completed and pending image counts."""
    current = load_current(ledger_path)
    by_job: dict[tuple[str, str], list[str]] = {}
    for asset_key, raw in current.items():
        if raw.get("event") == "ocr_job_submitted":
            by_job.setdefault((str(raw["job_id"]), str(raw["output_prefix"])), []).append(asset_key)

    client = storage.Client(project=config.gcs.project)
    completed = 0
    pending = 0
    for (_, output_prefix), asset_keys in by_job.items():
        bucket_name, object_prefix = _parse_gs_uri(output_prefix)
        output_uris = [f"gs://{bucket_name}/{blob.name}" for blob in client.list_blobs(bucket_name, prefix=object_prefix)]
        if output_uris:
            for event in ocr_output_available(asset_keys, output_uris=output_uris):
                append_event(ledger_path, event)
            completed += len(asset_keys)
        else:
            pending += len(asset_keys)
    return OcrStatusSummary(completed, pending)


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Expected GCS URI, got {uri!r}")
    bucket, _, prefix = uri[5:].partition("/")
    return bucket, prefix
