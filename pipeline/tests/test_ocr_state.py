import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from vie_doc_pipeline.config import GcsTarget, LocalPdfSource, OcrConfig, PipelineConfig, PublicationConfig
from vie_doc_pipeline.images.pdf import ExplodeParams
from vie_doc_pipeline.ledger.events import ocr_job_submitted, source_discovered
from vie_doc_pipeline.ledger.projection import PipelineState
from vie_doc_pipeline.assets import ImageAsset
from vie_doc_pipeline.workflow.ocr import _parse_gs_uri
from vie_doc_pipeline.workflow.ocr import OcrStatusService
from support import sample_pipeline_config


class OcrStateTest(unittest.TestCase):
    def test_parses_output_prefix(self) -> None:
        self.assertEqual(
            _parse_gs_uri("gs://vie-doc/nlv-cuu-quoc/ocr/jobs/job-1/batch_0/"),
            ("vie-doc", "nlv-cuu-quoc/ocr/jobs/job-1/batch_0/"),
        )

    def test_status_session_closes_storage_client(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig("pub", "Publication"),
            target=GcsTarget("project", "bucket", "pub/pdf", "pub/images", "pub/ocr"),
            source=LocalPdfSource("."),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
            config_toml="ocr-status-test",
        )
        asset = ImageAsset("pub", "issue", "001", "https://example.test/001.jpg", "pub/images/001.jpg")
        client = _FakeStorageClient()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.jsonl"
            state = PipelineState.open(path, config)
            state.record(source_discovered(asset))
            state.record(ocr_job_submitted([asset.key], job_id="job-1", output_prefix="gs://bucket/pub/ocr/job-1")[0])
            with patch("vie_doc_pipeline.workflow.ocr.storage.Client", return_value=client):
                summary = OcrStatusService(state).execute()

        self.assertEqual((summary.completed, summary.pending), (0, 1))
        self.assertTrue(client.closed)


class _FakeStorageClient:
    def __init__(self) -> None:
        self.closed = False

    def list_blobs(self, bucket: str, prefix: str) -> list[object]:
        return []

    def close(self) -> None:
        self.closed = True
