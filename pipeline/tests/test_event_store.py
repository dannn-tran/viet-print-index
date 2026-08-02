from concurrent.futures import ThreadPoolExecutor
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
            path = Path(directory) / "state.jsonl"
            store = EventStore.open(path)
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1.jpg", "pub/images/1.jpg")
            store.append(source_discovered(asset))

            state = AppState.open(path, None)
            projected = state.asset_state(asset.key)
            self.assertIsNotNone(projected)
            self.assertEqual(projected.asset if projected else None, asset)

            state.record(image_normalized(asset))
            projected = state.asset_state(asset.key)
            self.assertIsNotNone(projected)
            self.assertEqual(projected.event if projected else None, "image_normalized")
            self.assertEqual(len(list(store.iter_events())), 2)

    def test_concurrent_appends_remain_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore.open(Path(directory) / "state.jsonl")
            events = [
                source_discovered(ImageAsset("pub", "issue", str(index), f"https://example.test/{index}.jpg", f"pub/{index}.jpg"))
                for index in range(40)
            ]
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(store.append, events))

            self.assertEqual(len(list(store.iter_events())), len(events))

    def test_replay_repairs_an_incomplete_final_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.jsonl"
            store = EventStore.open(path)
            asset = ImageAsset("pub", "issue", "001", "https://example.test/1.jpg", "pub/1.jpg")
            store.append(source_discovered(asset))
            with path.open("ab") as handle:
                handle.write(b'{"event":"source_discovered"')

            state = AppState.open(path, None)

            projected = state.asset_state(asset.key)
            self.assertIsNotNone(projected)
            self.assertTrue(projected.asset if projected else None)
            self.assertEqual(len(list(store.iter_events())), 1)

    def test_first_event_reads_only_the_initial_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.jsonl"
            path.write_text(
                '{"event":"source_discovered","asset_key":"first","at":"now","data":{}}\n'
                '{"event":"not_a_real_event","asset_key":"second","at":"now","data":{}}\n',
                encoding="utf-8",
            )

            first = EventStore.open(path).first_event()

            self.assertIsNotNone(first)
            self.assertEqual(first.asset_key if first else None, "first")
