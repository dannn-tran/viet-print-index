import logging

from google.cloud import storage

from vie_doc_pipeline.pipeline_config import PipelineConfig
from vie_doc_pipeline.veridian import VeridianClient

logger = logging.getLogger(__name__)


def run_veridian_ingest(config: PipelineConfig, limit: int | None = None) -> None:
    """Upload full native page images from a Veridian source directly to GCS.

    Veridian source pages are already images, so they bypass the PDF and
    explode stages. The source is read sequentially to honour its configured
    delay and avoid aggressive crawling.
    """
    source = VeridianClient(config.source)
    client = storage.Client(project=config.gcs.project)
    bucket = client.bucket(config.gcs.bucket)

    issues = source.list_issues(limit=limit)
    print(f"Discovered {len(issues)} issues")

    for issue in issues:
        pages = source.list_pages(issue)
        for page in pages:
            blob_name = f"{config.gcs.images_prefix}/{issue.oid}/{page.filename}"
            blob = bucket.blob(blob_name)
            if blob.exists(client):
                continue
            data = source.fetch_page_image(page)
            blob.upload_from_string(data, content_type="image/jpeg")
            print(f"Ingested: {issue.oid}/{page.filename}")
