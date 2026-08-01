"""Submit and check asynchronous OCR jobs for image assets."""

from itertools import islice
from contextlib import contextmanager
from dataclasses import dataclass

from google.cloud import storage

from gc_vision_adapter.ocr.run import RunBatchOcrCommand, submit_ocr_batches
from vie_doc_pipeline.ledger.events import ocr_job_submitted, ocr_output_available
from vie_doc_pipeline.ledger.projection import AppState, assets_at
from vie_doc_pipeline.assets import ImageAsset
from vie_doc_pipeline.config import GcsTarget, PipelineConfig


@dataclass(frozen=True)
class OcrStatusSummary:
    completed: int = 0
    pending: int = 0


@dataclass(frozen=True)
class OcrSubmissionSummary:
    submitted: int = 0


def submit_ocr_jobs(config: PipelineConfig, state: AppState, limit: int | None = None) -> OcrSubmissionSummary:
    target = _require_gcs_target(config.target)
    assets = list(islice((
        item.asset
        for item in assets_at(state.current, "image_normalized")
        if isinstance(item.asset, ImageAsset)
    ), limit))
    if not assets:
        return OcrSubmissionSummary()

    command = RunBatchOcrCommand(
        input_bucket=target.bucket,
        output_bucket=target.bucket,
        output_dir=target.ocr_output_prefix,
        language_hints=config.ocr.language_hints,
    )
    uri_to_asset = {f"gs://{target.bucket}/{asset.target_path}": asset for asset in assets}
    jobs = submit_ocr_batches(target.project, command, list(uri_to_asset))
    for job in jobs:
        for event in ocr_job_submitted([uri_to_asset[uri].key for uri in job.input_uris], job_id=job.job_id, output_prefix=job.output_prefix):
            state.record(event)
    return OcrSubmissionSummary(submitted=len(assets))


def check_ocr_status(config: PipelineConfig, state: AppState) -> OcrStatusSummary:
    """Check for OCR results in GCS and return completed and pending image counts."""
    _require_gcs_target(config.target)
    with open_ocr_status_session(config, state) as session:
        return session.check()


@dataclass
class OcrStatusSession:
    state: AppState
    client: storage.Client

    def check(self) -> OcrStatusSummary:
        current = self.state.current
        by_job: dict[tuple[str, str], list[str]] = {}
        for asset_key, state in current.items():
            if state.event == "ocr_job_submitted" and state.job_id and state.output_prefix:
                by_job.setdefault((state.job_id, state.output_prefix), []).append(asset_key)
        completed = pending = 0
        for (_, output_prefix), asset_keys in by_job.items():
            output_uris = self.output_uris(output_prefix)
            if output_uris:
                for event in ocr_output_available(asset_keys, output_uris=output_uris):
                    self.state.record(event)
                completed += len(asset_keys)
            else:
                pending += len(asset_keys)
        return OcrStatusSummary(completed, pending)

    def output_uris(self, output_prefix: str) -> list[str]:
        bucket_name, object_prefix = _parse_gs_uri(output_prefix)
        return [f"gs://{bucket_name}/{blob.name}" for blob in self.client.list_blobs(bucket_name, prefix=object_prefix)]


@contextmanager
def open_ocr_status_session(config: PipelineConfig, state: AppState):
    target = _require_gcs_target(config.target)
    client = storage.Client(project=target.project)
    try:
        yield OcrStatusSession(state, client)
    finally:
        client.close()


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Expected GCS URI, got {uri!r}")
    bucket, _, prefix = uri[5:].partition("/")
    return bucket, prefix


def _require_gcs_target(target: object) -> GcsTarget:
    if not isinstance(target, GcsTarget):
        raise ValueError("OCR requires target.type = 'gcs'")
    return target
