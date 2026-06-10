import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath

from google.cloud import storage

from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.source_adapter import fetch_bytes, make_adapter

logger = logging.getLogger(__name__)


def run_ingest(config: PipelineConfig, limit: int | None = None, workers: int = 4) -> None:
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)

    items = make_adapter(config.source).list_pdf_items()
    if limit is not None:
        items = items[:limit]

    # Determine which are already in GCS
    existing = {
        b.name
        for b in client.list_blobs(config.gcs.bucket, prefix=config.gcs.pdf_prefix + "/")
        if b.name.endswith(".pdf")
    }

    pending = [item for item in items if _blob_name(config, item) not in existing]
    skipped = len(items) - len(pending)
    if skipped:
        print(f"{len(pending)} pending, {skipped} already in GCS")
    if not pending:
        return

    def _upload_one(item: str) -> str:
        blob_name = _blob_name(config, item)
        data = fetch_bytes(item)
        bucket.blob(blob_name).upload_from_string(data, content_type="application/pdf")
        return blob_name

    if workers < 2:
        for item in pending:
            blob_name = _upload_one(item)
            print(f"Ingested: {PurePosixPath(blob_name).name}")
        return

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_upload_one, item): item for item in pending}
        for fut in as_completed(futures):
            try:
                blob_name = fut.result()
                print(f"Ingested: {PurePosixPath(blob_name).name}")
            except Exception as e:
                logger.error(f"Failed: {futures[fut]}: {e}")


def _blob_name(config: PipelineConfig, item: str) -> str:
    filename = PurePosixPath(item).name
    return f"{config.gcs.pdf_prefix}/{filename}"
