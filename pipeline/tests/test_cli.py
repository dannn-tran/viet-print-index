from pathlib import Path
import tempfile
import unittest

from vie_doc_pipeline.assets import ImageAsset
from vie_doc_pipeline.cli import _bind_configuration, _resolve_state_path
from vie_doc_pipeline.ledger.events import source_discovered
from vie_doc_pipeline.ledger.store import EventStore


class CliPathTest(unittest.TestCase):
    def test_explicit_state_path_is_preserved(self) -> None:
        config_path = Path("sources/cuu-quoc.toml")
        state_path = Path("tmp/custom-state.jsonl")

        self.assertEqual(_resolve_state_path(config_path, state_path), state_path)

    def test_default_state_path_is_derived_from_config_stem(self) -> None:
        config_path = Path("sources/cuu-quoc.toml")

        self.assertEqual(
            _resolve_state_path(config_path, None),
            Path(".pipeline-state/v2/cuu-quoc.jsonl"),
        )


class CliConfigurationTest(unittest.TestCase):
    def test_records_and_validates_config_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = EventStore.open(Path(temporary_directory) / "state.jsonl")
            _bind_configuration(store, "config-a")
            _bind_configuration(store, "config-a")

            events = list(store.iter_events())
            self.assertEqual(events[0].event, "configuration_bound")
            self.assertEqual(events[0].data["config_toml"], "config-a")
            self.assertEqual(len(events), 1)
            with self.assertRaisesRegex(ValueError, "different TOML"):
                _bind_configuration(store, "config-b")

    def test_refuses_to_mix_events_without_bound_config_toml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = EventStore.open(Path(temporary_directory) / "state.jsonl")
            store.append(source_discovered(ImageAsset(
                publication_id="pub",
                issue_id="issue",
                page_id="001",
                source_url="https://example.test/1",
                target_path="pub/images/1.jpg",
            )))

            with self.assertRaisesRegex(ValueError, "no bound TOML"):
                _bind_configuration(store, "config-a")
