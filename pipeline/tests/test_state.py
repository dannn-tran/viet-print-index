import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from vie_doc_pipeline.ledger.events import (
    failed,
    image_inverted,
    image_normalized,
    ocr_job_submitted,
    source_discovered,
    source_fetched,
    source_inverted,
)
from vie_doc_pipeline.ledger.projection import ConfigurationMismatchError, PipelineState
from vie_doc_pipeline.ledger.store import EventStore
from vie_doc_pipeline.assets import ImageAsset
from support import sample_pipeline_config


class PipelineStateTest(unittest.TestCase):
    def test_open_records_and_validates_config_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            state = PipelineState.open(path, sample_pipeline_config("config-a"))

            events = list(EventStore.open(path).iter_events())
            self.assertEqual(state.configuration.config_toml, "config-a")
            self.assertEqual(events[0].event, "configuration_bound")
            self.assertEqual(events[0].data["config_toml"], "config-a")
            self.assertEqual(len(events), 1)
            with self.assertRaises(ConfigurationMismatchError):
                PipelineState.open(path, sample_pipeline_config("config-b"))

    def test_open_requires_a_configuration_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            config = replace(sample_pipeline_config(), config_toml=None)

            with self.assertRaisesRegex(ValueError, "configuration loaded from TOML"):
                PipelineState.open(path, config)

    def test_open_rejects_unbound_event_store(self) -> None:
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

            with self.assertRaisesRegex(ConfigurationMismatchError, "no bound TOML"):
                PipelineState.open(path, sample_pipeline_config("config-a"))

    def test_replay_projects_inversion_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            config = sample_pipeline_config()
            PipelineState.open(path, config)
            store = EventStore.open(path)
            store.append(source_inverted("issue-001"))
            store.append(image_inverted("pub/issue-001/001"))

            state = PipelineState.open(path, config)

            self.assertEqual(state.inversion_overrides.source_ids, frozenset({"issue-001"}))
            self.assertEqual(state.inversion_overrides.image_keys, frozenset({"pub/issue-001/001"}))

    def test_source_override_does_not_create_an_asset_lifecycle_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            config = sample_pipeline_config()
            PipelineState.open(path, config)
            store = EventStore.open(path)
            store.append(source_inverted("issue-001"))

            state = PipelineState.open(path, config)

            self.assertEqual(state.asset_keys(), ())
            self.assertEqual(state.inversion_overrides.source_ids, frozenset({"issue-001"}))

    def test_appends_inspectable_events_and_reconstructs_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            config = sample_pipeline_config()
            asset = ImageAsset(
                publication_id="nlv-cuu-quoc",
                issue_id="WNyf19450905",
                page_id="001",
                source_url="https://example.test/page.jpg",
                target_path="nlv-cuu-quoc/images/WNyf19450905/001.jpg",
            )
            PipelineState.open(path, config)
            store = EventStore.open(path)
            store.append(source_discovered(asset))
            store.append(source_fetched(asset, checksum="abc123", size_bytes=100))
            store.append(image_normalized(asset))
            store.append(ocr_job_submitted([asset.key], job_id="operation-1", output_prefix="gs://bucket/ocr/batch-0")[0])

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 5)
            self.assertEqual(json.loads(lines[0])["event"], "configuration_bound")
            projected = PipelineState.open(path, config).asset_state(asset.key)
            self.assertIsNotNone(projected)
            self.assertEqual(projected.job_id if projected else None, "operation-1")
            state = PipelineState.open(path, config)
            self.assertEqual(state.asset_keys(), (asset.key,))
            self.assertEqual(state.asset_states()[0].asset, asset)
            self.assertEqual(len(list(store.iter_events())), 5)

    def test_failure_keeps_last_successful_lifecycle_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            config = sample_pipeline_config()
            PipelineState.open(path, config)
            store = EventStore.open(path)
            store.append(source_discovered(ImageAsset(
                publication_id="pub", issue_id="issue", page_id="001", source_url="https://example.test/1", target_path="pub/images/1.jpg"
            )))
            asset_key = "pub/issue/001"
            store.append(failed(asset_key, stage="fetch", error="temporary failure"))
            projected = PipelineState.open(path, config).asset_state(asset_key)
            self.assertIsNotNone(projected)
            self.assertEqual(projected.event, "source_discovered")
            self.assertIsNotNone(projected.failure)
            self.assertEqual(projected.failure.stage if projected.failure else None, "fetch")

    def test_permanent_failure_is_not_eligible_for_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            config = sample_pipeline_config()
            PipelineState.open(path, config)
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1", "pub/images/1.jpg")
            store = EventStore.open(path)
            store.append(source_discovered(asset))
            store.append(failed(asset.key, stage="fetch", error="HTTP 404", retryable=False))
            self.assertEqual(PipelineState.open(path, config).eligible_source_assets(), ())

    def test_successful_retry_clears_prior_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            config = sample_pipeline_config()
            PipelineState.open(path, config)
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1", "pub/images/1.jpg")
            store = EventStore.open(path)
            store.append(source_discovered(asset))
            store.append(failed(asset.key, stage="fetch", error="timeout"))
            store.append(source_fetched(asset, checksum="checksum", size_bytes=10))
            projected = PipelineState.open(path, config).asset_state(asset.key)
            self.assertIsNotNone(projected)
            self.assertIsNone(projected.failure if projected else None)

    def test_rejects_unknown_event_shape_at_event_store_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.jsonl"
            path.write_text('{"event":"future_event","asset_key":"asset","at":"now","data":{}}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid event record"):
                list(EventStore.open(path).iter_events())
