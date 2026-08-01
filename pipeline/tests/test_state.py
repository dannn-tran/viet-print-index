import json
import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.ledger.events import image_normalized, ocr_job_submitted, source_discovered, source_downloaded
from vie_doc_pipeline.ledger.jsonl import append_event, read_events
from vie_doc_pipeline.ledger.projection import load_current
from vie_doc_pipeline.models import PageAsset


class JsonlLedgerTest(unittest.TestCase):
    def test_appends_inspectable_events_and_reconstructs_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            asset = PageAsset(
                publication_id="nlv-cuu-quoc",
                issue_id="WNyf19450905",
                page_id="001",
                source_url="https://example.test/page.jpg",
                object_name="nlv-cuu-quoc/images/WNyf19450905/001.jpg",
            )
            append_event(path, source_discovered(asset))
            append_event(path, source_downloaded(asset, checksum="abc123", size_bytes=100))
            append_event(path, image_normalized(asset))
            append_event(path, ocr_job_submitted([asset.key], job_id="operation-1", output_prefix="gs://bucket/ocr/batch-0")[0])

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(json.loads(lines[0])["event"], "source_discovered")
            self.assertEqual(load_current(path)[asset.key]["job_id"], "operation-1")
            self.assertEqual(len(read_events(path)), 4)
