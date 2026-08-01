import json
import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.ledger.events import failed, image_normalized, ocr_job_submitted, source_discovered, source_fetched
from vie_doc_pipeline.ledger.jsonl import LedgerConfigMismatchError, append_event, ensure_ledger_config, read_events
from vie_doc_pipeline.ledger.projection import eligible_source_assets, load_current
from vie_doc_pipeline.assets import ImageAsset


class JsonlLedgerTest(unittest.TestCase):
    def test_records_and_validates_config_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            ensure_ledger_config(path, "a" * 64)
            ensure_ledger_config(path, "a" * 64)

            self.assertEqual(list(read_events(path, "a" * 64))[0].event, "ledger_initialized")
            self.assertEqual(len(list(read_events(path))), 1)
            with self.assertRaises(LedgerConfigMismatchError):
                ensure_ledger_config(path, "b" * 64)

            with self.assertRaises(LedgerConfigMismatchError):
                list(read_events(path, "b" * 64))

    def test_refuses_to_mix_legacy_events_with_a_fingerprinted_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            append_event(path, source_discovered(ImageAsset(
                publication_id="pub",
                issue_id="issue",
                page_id="001",
                source_url="https://example.test/1",
                target_path="pub/images/1.jpg",
            )))

            with self.assertRaises(LedgerConfigMismatchError):
                ensure_ledger_config(path, "a" * 64)

    def test_appends_inspectable_events_and_reconstructs_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            asset = ImageAsset(
                publication_id="nlv-cuu-quoc",
                issue_id="WNyf19450905",
                page_id="001",
                source_url="https://example.test/page.jpg",
                target_path="nlv-cuu-quoc/images/WNyf19450905/001.jpg",
            )
            append_event(path, source_discovered(asset))
            append_event(path, source_fetched(asset, checksum="abc123", size_bytes=100))
            append_event(path, image_normalized(asset))
            append_event(path, ocr_job_submitted([asset.key], job_id="operation-1", output_prefix="gs://bucket/ocr/batch-0")[0])

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(json.loads(lines[0])["event"], "source_discovered")
            self.assertEqual(load_current(path)[asset.key].job_id, "operation-1")
            self.assertEqual(len(list(read_events(path))), 4)

    def test_failure_keeps_last_successful_lifecycle_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            append_event(path, source_discovered(ImageAsset(
                publication_id="pub", issue_id="issue", page_id="001", source_url="https://example.test/1", target_path="pub/images/1.jpg"
            )))
            asset_key = "pub/issue/001"
            append_event(path, failed(asset_key, stage="fetch", error="temporary failure"))
            current = load_current(path)[asset_key]
            self.assertEqual(current.event, "source_discovered")
            self.assertIsNotNone(current.failure)
            self.assertEqual(current.failure.stage if current.failure else None, "fetch")

    def test_permanent_failure_is_not_eligible_for_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1", "pub/images/1.jpg")
            append_event(path, source_discovered(asset))
            append_event(path, failed(asset.key, stage="fetch", error="HTTP 404", retryable=False))
            self.assertEqual(eligible_source_assets(load_current(path)), [])

    def test_successful_retry_clears_prior_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1", "pub/images/1.jpg")
            append_event(path, source_discovered(asset))
            append_event(path, failed(asset.key, stage="fetch", error="timeout"))
            append_event(path, source_fetched(asset, checksum="checksum", size_bytes=10))
            self.assertIsNone(load_current(path)[asset.key].failure)

    def test_rejects_unknown_event_shape_at_jsonl_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            path.write_text('{"event":"future_event","asset_key":"asset","at":"now","data":{}}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid ledger event"):
                list(read_events(path))
