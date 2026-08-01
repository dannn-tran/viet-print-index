from pathlib import Path
import unittest

from vie_doc_pipeline.cli import _resolve_state_path


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
