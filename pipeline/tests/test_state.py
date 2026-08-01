import json
import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.models import PageAsset
from vie_doc_pipeline.state import JsonlStateStore


class JsonlStateStoreTest(unittest.TestCase):
    def test_appends_inspectable_events_and_reconstructs_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            store = JsonlStateStore(path)
            asset = PageAsset(
                publication_id="nlv-cuu-quoc",
                issue_id="WNyf19450905",
                page_id="001",
                source_url="https://example.test/page.jpg",
                object_name="nlv-cuu-quoc/images/WNyf19450905/001.jpg",
            )
            store.record_discovered(asset)
            store.record_fetched(asset, checksum="abc123", size_bytes=100)
            store.record_materialized(asset)
            store.record_ocr_submitted([asset.key], job_id="operation-1", output_prefix="gs://bucket/ocr/batch-0")

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(json.loads(lines[0])["event"], "discovered")
            self.assertEqual(store.current()[asset.key]["job_id"], "operation-1")
