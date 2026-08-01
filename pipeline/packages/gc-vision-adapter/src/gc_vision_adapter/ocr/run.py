import itertools
import logging
import uuid
from dataclasses import dataclass
from typing import Sequence

from google.api_core.client_options import ClientOptions
from google.api_core import exceptions as google_exceptions
from google.api_core import operation
from google.cloud import storage
from google.cloud import vision


logger = logging.getLogger(__name__)


DEFAULT_OCR_INPUT_EXTS = ('png', 'jpg', 'jpeg', 'tiff', 'tif')
DEFAULT_OCR_INPUT_BATCHSIZE = 100
DEFAULT_OCR_OUTPUT_BATCHSIZE = 20
DEFAULT_OCR_BATCH_PROCESS_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class RunBatchOcrCommand:
    input_bucket: str = ""
    input_file_prefix: str = ""
    input_file_exts: tuple[str, ...] = DEFAULT_OCR_INPUT_EXTS
    input_batchsize: int = DEFAULT_OCR_INPUT_BATCHSIZE
    output_bucket: str = ""
    output_dir: str = ""
    output_batchsize: int = DEFAULT_OCR_OUTPUT_BATCHSIZE
    language_hints: tuple[str, ...] = ()
    batch_process_timeout_seconds: int = DEFAULT_OCR_BATCH_PROCESS_TIMEOUT_SECONDS


@dataclass(frozen=True)
class SubmittedOcrBatch:
    job_id: str
    input_uris: tuple[str, ...]
    output_prefix: str


def batch_ocr(project_id: str, cmd: RunBatchOcrCommand):
    storage_client = storage.Client(project=project_id)
    try:
        image_uris = tuple(
            f"gs://{cmd.input_bucket}/{blob.name}"
            for blob in storage_client.list_blobs(cmd.input_bucket, prefix=cmd.input_file_prefix)
            if not cmd.input_file_exts or blob.name.lower().endswith(cmd.input_file_exts)
        )
    finally:
        storage_client.close()

    vision_client = vision.ImageAnnotatorClient(client_options=ClientOptions(quota_project_id=project_id))
    try:
        output_uri = f"gs://{cmd.output_bucket}/{cmd.output_dir}".rstrip("/")
        ocr_ops: list[tuple[int, operation.Operation]] = [
            (i, _submit_ocr_batch(vision_client, i, chunk, output_uri, cmd.output_batchsize, cmd.language_hints))
            for i, chunk in enumerate(itertools.batched(image_uris, cmd.input_batchsize))
        ]
        logger.info("All %s batches submitted (%s images total). Waiting...", len(ocr_ops), len(image_uris))

        failed_batches: list[int] = []
        for i, ocr_op in ocr_ops:
            try:
                ocr_op.result(timeout=cmd.batch_process_timeout_seconds)
                logger.info("Batch %s completed", i)
            except (google_exceptions.GoogleAPIError, TimeoutError) as error:
                logger.error("Batch %s failed: %s", i, error)
                failed_batches.append(i)

        if failed_batches:
            logger.warning("Done with errors. Failed batches: %s", failed_batches)
        else:
            logger.info("All batches completed successfully.")
    finally:
        vision_client.close()


def submit_ocr_batches(
    project_id: str,
    cmd: RunBatchOcrCommand,
    image_uris: Sequence[str],
) -> list[SubmittedOcrBatch]:
    """Submit OCR operations without blocking for completion.

    Callers persist the returned job IDs and output prefixes, then reconcile
    completion later. A unique output directory prevents concurrent runs from
    overwriting or confusing each other's results.
    """
    vision_client = vision.ImageAnnotatorClient(client_options=ClientOptions(quota_project_id=project_id))
    try:
        base_output_uri = f"gs://{cmd.output_bucket}/{cmd.output_dir}".rstrip("/")
        submitted: list[SubmittedOcrBatch] = []
        for batch_id, chunk in enumerate(itertools.batched(tuple(image_uris), cmd.input_batchsize)):
            job_id = uuid.uuid4().hex
            output_prefix = f"{base_output_uri}/jobs/{job_id}/batch_{batch_id}/"
            _submit_ocr_batch(
                vision_client,
                batch_id,
                chunk,
                output_prefix.removesuffix(f"/batch_{batch_id}/"),
                cmd.output_batchsize,
                cmd.language_hints,
            )
            logger.info("Submitted OCR job %s (%s images) → %s", job_id, len(chunk), output_prefix)
            submitted.append(SubmittedOcrBatch(job_id, chunk, output_prefix))
        return submitted
    finally:
        vision_client.close()

def _submit_ocr_batch(
    vision_client: vision.ImageAnnotatorClient,
    batch_id: int,
    input_uris: tuple[str, ...],
    output_uri: str,
    output_batchsize: int,
    language_hints: tuple[str, ...],
):
    batch_output_uri = f"{output_uri}/batch_{batch_id}/"
    op = vision_client.async_batch_annotate_images(
        requests=[
            vision.AnnotateImageRequest(
                image=vision.Image(source=vision.ImageSource(image_uri=uri)),
                features=[vision.Feature(type=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)],
                image_context=vision.ImageContext(language_hints=language_hints),
            )
            for uri in input_uris
        ],
        output_config=vision.OutputConfig(
            gcs_destination=vision.GcsDestination(uri=batch_output_uri),
            batch_size=output_batchsize,
        ),
    )

    logger.info("Submitted batch %s (%s images) → %s", batch_id, len(input_uris), batch_output_uri)

    return op
