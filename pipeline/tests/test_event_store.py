import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.assets import ImageAsset
from vie_doc_pipeline.ledger.events import image_normalized, source_discovered
from vie_doc_pipeline.ledger.projection import AppState
from vie_doc_pipeline.ledger.store import EventStore


class EventStoreTest(unittest.TestCase):
    def test_replay_streams_events_and_record_updates_store_and_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore.open(Path(directory) / "state.jsonl")
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1.jpg", "pub/images/1.jpg")
            store.append(source_discovered(asset))

            state = AppState.replay(store)
            self.assertEqual(state.current[asset.key].asset, asset)

            state.record(image_normalized(asset))
            self.assertEqual(state.current[asset.key].event, "image_normalized")
            self.assertEqual(len(list(store.read_events())), 2)
