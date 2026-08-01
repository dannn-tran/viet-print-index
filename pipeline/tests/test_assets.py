import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from vie_doc_pipeline.domain import PageAsset
from vie_doc_pipeline.explode_mem import ExplodeParams
from vie_doc_pipeline.pipeline_config import GcsConfig, OcrConfig, PipelineConfig, PublicationConfig, SourceConfig
from vie_doc_pipeline.stages.assets import _document_from_url, discover_assets, materialize_pages
from vie_doc_pipeline.state import JsonlStateStore


class AssetDiscoveryTest(unittest.TestCase):
    def test_pdf_document_identity_uses_decoded_file_stem(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            gcs=GcsConfig("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=SourceConfig(type="web_page"),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )

        asset = _document_from_url(config, "https://example.test/Tu%E1%BA%A7n%20b%C3%A1o%20001.pdf")

        self.assertEqual(asset.document_id, "Tuần báo 001")
        self.assertEqual(asset.object_name, "doi-moi/pdf/Tu%E1%BA%A7n%20b%C3%A1o%20001.pdf")

    def test_native_image_materialization_never_writes_another_object(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="cuu-quoc", name="Cứu Quốc"),
            gcs=GcsConfig("project", "bucket", "cuu-quoc/pdf", "cuu-quoc/images", "cuu-quoc/ocr"),
            source=SourceConfig(type="veridian"),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        asset = PageAsset("cuu-quoc", "issue-001", "001", "https://example.test/001.jpg", "cuu-quoc/images/issue-001/001.jpg")
        with TemporaryDirectory() as directory:
            state = JsonlStateStore(Path(directory) / "state.jsonl")
            state.record_discovered(asset)
            state.record_fetched(asset, checksum="checksum", size_bytes=10)
            client = _FakeStorageClient()

            with patch("vie_doc_pipeline.stages.assets.storage.Client", return_value=client):
                pages, passthrough = materialize_pages(config, state)

            self.assertEqual((pages, passthrough), (0, 1))
            self.assertEqual(client.bucket_instance.blob_names, [])
            self.assertEqual(state.current()[asset.key]["event"], "materialized")

    def test_discovery_does_not_overwrite_existing_ledger_state(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            gcs=GcsConfig("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=SourceConfig(type="url_list", urls=["https://example.test/001.pdf"]),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        with TemporaryDirectory() as directory:
            state = JsonlStateStore(Path(directory) / "state.jsonl")
            source_item = Mock(kind="pdf", source_url="https://example.test/001.pdf")
            with patch("vie_doc_pipeline.stages.assets.discover_source_items", return_value=[source_item]):
                self.assertEqual(len(discover_assets(config, state)), 1)
                self.assertEqual(discover_assets(config, state), [])


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
