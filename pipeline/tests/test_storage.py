import tempfile
import unittest

from vie_doc_pipeline.config import LocalTarget
from vie_doc_pipeline.storage import LocalTargetStore


class LocalTargetStoreTest(unittest.TestCase):
    def test_reads_writes_and_inspects_target_relative_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalTargetStore(LocalTarget(root=directory))
            store.write_bytes("images/issue/001.jpg", b"image", content_type="image/jpeg")

            self.assertEqual(store.read_bytes("images/issue/001.jpg"), b"image")
            metadata = store.inspect("images/issue/001.jpg")
            self.assertIsNotNone(metadata)
            self.assertEqual(metadata.size_bytes if metadata else None, 5)
            store.close()

    def test_rejects_paths_outside_target_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalTargetStore(LocalTarget(root=directory))

            with self.assertRaises(ValueError):
                store.write_bytes("../outside", b"bad", content_type="application/octet-stream")
