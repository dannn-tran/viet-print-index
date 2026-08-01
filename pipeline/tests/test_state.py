import json
import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.ledger.events import failed, image_normalized, ocr_job_submitted, source_discovered, source_fetched
from vie_doc_pipeline.ledger.projection import AppState, eligible_source_assets
from vie_doc_pipeline.ledger.store import EventStore
from vie_doc_pipeline.assets import ImageAsset
from vie_doc_pipeline.workflow.configuration import ConfigMismatchError, bind_configuration


class EventStoreConfigTest(unittest.TestCase):
    def test_records_and_validates_config_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            store = EventStore.open(path)
            bind_configuration(store, "config-a")
            bind_configuration(store, "config-a")

            events = list(store.iter_events())
            self.assertEqual(events[0].event, "configuration_bound")
            self.assertEqual(events[0].data["config_toml"], "config-a")
            self.assertEqual(len(events), 1)
            with self.assertRaises(ConfigMismatchError):
                bind_configuration(store, "config-b")

    def test_refuses_to_mix_events_without_bound_config_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            store = EventStore.open(path)
            store.append(source_discovered(ImageAsset(
                publication_id="pub",
                issue_id="issue",
                page_id="001",
                source_url="https://example.test/1",
                target_path="pub/images/1.jpg",
            )))

            with self.assertRaises(ConfigMismatchError):
                bind_configuration(store, "config-a")

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
            store = EventStore.open(path)
            store.append(source_discovered(asset))
            store.append(source_fetched(asset, checksum="abc123", size_bytes=100))
            store.append(image_normalized(asset))
            store.append(ocr_job_submitted([asset.key], job_id="operation-1", output_prefix="gs://bucket/ocr/batch-0")[0])

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(json.loads(lines[0])["event"], "source_discovered")
            self.assertEqual(AppState.replay(store).current[asset.key].job_id, "operation-1")
            self.assertEqual(len(list(store.iter_events())), 4)

    def test_failure_keeps_last_successful_lifecycle_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            store = EventStore.open(path)
            store.append(source_discovered(ImageAsset(
                publication_id="pub", issue_id="issue", page_id="001", source_url="https://example.test/1", target_path="pub/images/1.jpg"
            )))
            asset_key = "pub/issue/001"
            store.append(failed(asset_key, stage="fetch", error="temporary failure"))
            current = AppState.replay(store).current[asset_key]
            self.assertEqual(current.event, "source_discovered")
            self.assertIsNotNone(current.failure)
            self.assertEqual(current.failure.stage if current.failure else None, "fetch")

    def test_permanent_failure_is_not_eligible_for_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1", "pub/images/1.jpg")
            store = EventStore.open(path)
            store.append(source_discovered(asset))
            store.append(failed(asset.key, stage="fetch", error="HTTP 404", retryable=False))
            self.assertEqual(eligible_source_assets(AppState.replay(store).current), [])

    def test_successful_retry_clears_prior_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1", "pub/images/1.jpg")
            store = EventStore.open(path)
            store.append(source_discovered(asset))
            store.append(failed(asset.key, stage="fetch", error="timeout"))
            store.append(source_fetched(asset, checksum="checksum", size_bytes=10))
            self.assertIsNone(AppState.replay(store).current[asset.key].failure)

    def test_rejects_unknown_event_shape_at_event_store_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            path.write_text('{"event":"future_event","asset_key":"asset","at":"now","data":{}}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid event record"):
                list(EventStore.open(path).iter_events())
