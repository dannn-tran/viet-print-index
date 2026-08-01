import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from vie_doc_pipeline.ledger.events import source_discovered, source_downloaded
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.projection import load_current
from vie_doc_pipeline.models import ImageAsset
from vie_doc_pipeline.explode_mem import ExplodeParams
from vie_doc_pipeline.pipeline_config import GcsConfig, OcrConfig, PipelineConfig, PublicationConfig, SourceConfig
from vie_doc_pipeline.workflow.assets import asset_from_source_item
from vie_doc_pipeline.workflow.discover_source import discover_source_assets
from vie_doc_pipeline.workflow.normalize_images import normalize_images


class AssetDiscoveryTest(unittest.TestCase):
    def test_pdf_document_identity_uses_decoded_file_stem(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            gcs=GcsConfig("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=SourceConfig(type="web_page"),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )

        source_item = Mock(kind="pdf", source_url="https://example.test/Tu%E1%BA%A7n%20b%C3%A1o%20001.pdf")
        asset = asset_from_source_item(config, source_item)

        self.assertEqual(asset.document_id, "Tuần báo 001")
        self.assertEqual(asset.gcs_object, "doi-moi/pdf/Tu%E1%BA%A7n%20b%C3%A1o%20001.pdf")

    def test_native_image_materialization_never_writes_another_object(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="cuu-quoc", name="Cứu Quốc"),
            gcs=GcsConfig("project", "bucket", "cuu-quoc/pdf", "cuu-quoc/images", "cuu-quoc/ocr"),
            source=SourceConfig(type="veridian"),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        asset = ImageAsset("cuu-quoc", "issue-001", "001", "https://example.test/001.jpg", "cuu-quoc/images/issue-001/001.jpg")
        with TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "state.jsonl"
            append_event(ledger_path, source_discovered(asset))
            append_event(ledger_path, source_downloaded(asset, checksum="checksum", size_bytes=10))
            client = _FakeStorageClient()

            with patch("vie_doc_pipeline.workflow.normalize_images.storage.Client", return_value=client):
                pages, passthrough = normalize_images(config, ledger_path)

            self.assertEqual((pages, passthrough), (0, 1))
            self.assertEqual(client.bucket_instance.blob_names, [])
            self.assertEqual(load_current(ledger_path)[asset.key]["event"], "image_normalized")

    def test_discovery_does_not_overwrite_existing_ledger_state(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            gcs=GcsConfig("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=SourceConfig(type="url_list", urls=["https://example.test/001.pdf"]),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        with TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "state.jsonl"
            source_item = Mock(kind="pdf", source_url="https://example.test/001.pdf")
            with patch("vie_doc_pipeline.workflow.discover_source.discover_source_items", return_value=[source_item]):
                self.assertEqual(len(discover_source_assets(config, ledger_path)), 1)
                self.assertEqual(discover_source_assets(config, ledger_path), [])


class _FakeBucket:
    def __init__(self) -> None:
        self.blob_names: list[str] = []

    def blob(self, name: str) -> object:
        self.blob_names.append(name)
        raise AssertionError("native image materialization must not access a blob")


class _FakeStorageClient:
    def __init__(self) -> None:
        self.bucket_instance = _FakeBucket()

    def bucket(self, name: str) -> _FakeBucket:
        return self.bucket_instance
