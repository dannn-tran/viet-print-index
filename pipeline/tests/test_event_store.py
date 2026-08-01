import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.assets import ImageAsset
from vie_doc_pipeline.ledger.events import source_discovered
from vie_doc_pipeline.ledger.projection import apply_event
from vie_doc_pipeline.ledger.store import EventStore


class EventStoreTest(unittest.TestCase):
    def test_streams_events_and_replays_one_event_at_a_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore.open(Path(directory) / "state.jsonl")
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1.jpg", "pub/images/1.jpg")
            event = source_discovered(asset)
            store.append(event)

            state = {}
            for streamed_event in store.read_events():
                state = apply_event(state, streamed_event)

            self.assertEqual(state[asset.key].asset, asset)
