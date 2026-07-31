import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from google.cloud import storage

from vie_doc_pipeline.explode_mem import explode_pdf_bytes
from vie_doc_pipeline.pipeline_config import PipelineConfig

logger = logging.getLogger(__name__)


def run_explode(config: PipelineConfig, limit: int | None = None, workers: int = 4) -> None:
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)

    pdf_blobs = [
        b for b in client.list_blobs(config.gcs.bucket, prefix=config.gcs.pdf_prefix + "/")
        if b.name.endswith(".pdf")
    ]
    if limit is not None:
        pdf_blobs = pdf_blobs[:limit]

    pending = [b for b in pdf_blobs if not _already_exploded(client, config, b.name)]
    skipped = len(pdf_blobs) - len(pending)
    if skipped:
        print(f"{len(pending)} pending, {skipped} already exploded")
    if not pending:
        return

    def _explode_one(blob: storage.Blob) -> tuple[str, int]:
        stem = blob.name.rsplit("/", 1)[-1].removesuffix(".pdf")
        pdf_bytes = blob.download_as_bytes(timeout=600)
        images = explode_pdf_bytes(pdf_bytes, config.explode)
        for filename, image_bytes in images:
            img_blob_name = f"{config.gcs.images_prefix}/{stem}/{filename}"
            ctype = "image/png" if filename.endswith(".png") else "image/jpeg"
            bucket.blob(img_blob_name).upload_from_string(image_bytes, content_type=ctype, timeout=600)
        return stem, len(images)

    if workers < 2:
        for blob in pending:
            stem, n = _explode_one(blob)
            print(f"Exploded: {stem} ({n} images)")
        return

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_explode_one, blob): blob for blob in pending}
        for fut in as_completed(futures):
            try:
                stem, n = fut.result()
                print(f"Exploded: {stem} ({n} images)")
            except Exception as e:
                logger.error(f"Failed: {futures[fut].name}: {e}")


def _already_exploded(client: storage.Client, config: PipelineConfig, pdf_blob_name: str) -> bool:
    stem = pdf_blob_name.rsplit("/", 1)[-1].removesuffix(".pdf")
    prefix = f"{config.gcs.images_prefix}/{stem}/"
    blobs = client.list_blobs(config.gcs.bucket, prefix=prefix, max_results=1)
    return any(True for _ in blobs)
