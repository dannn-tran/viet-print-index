import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from vie_doc_pipeline.ledger.events import source_discovered, source_downloaded
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.projection import load_current
from vie_doc_pipeline.models import ImageAsset
from vie_doc_pipeline.explode_mem import ExplodeParams
from vie_doc_pipeline.pipeline_config import (
    GcsConfig,
    OcrConfig,
    PipelineConfig,
    PublicationConfig,
    UrlListPdfSource,
    VeridianSource,
    WebPagePdfSource,
)
from vie_doc_pipeline.workflow.assets import asset_from_source_item
from vie_doc_pipeline.workflow.discover_source import discover_source_assets
from vie_doc_pipeline.workflow.normalize_images import normalize_images


class AssetDiscoveryTest(unittest.TestCase):
    def test_pdf_document_identity_uses_decoded_file_stem(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            gcs=GcsConfig("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=WebPagePdfSource(page_url="https://example.test/index"),
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
            source=VeridianSource("https://example.test/catalogue", "https://example.test/images", "WNyf", date(1945, 9, 1), date(1955, 4, 30)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        asset = ImageAsset("cuu-quoc", "issue-001", "001", "https://example.test/001.jpg", "cuu-quoc/images/issue-001/001.jpg")
        with TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "state.jsonl"
            append_event(ledger_path, source_discovered(asset))
            append_event(ledger_path, source_downloaded(asset, checksum="checksum", size_bytes=10))
            client = _FakeStorageClient()

            with patch("vie_doc_pipeline.workflow.normalize_images.storage.Client", return_value=client), \
                 patch("vie_doc_pipeline.workflow.normalize_images.check_inversion") as check:
                check.return_value = Mock(inverted=False, needs_review=False)
                pages, passthrough = normalize_images(config, ledger_path)

            self.assertEqual((pages, passthrough), (0, 1))
            self.assertEqual(client.bucket_instance.uploads, [])
            self.assertEqual(load_current(ledger_path)[asset.key]["event"], "image_normalized")

    def test_native_image_path_prefers_human_issue_label(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="cuu-quoc", name="Cứu Quốc"),
            gcs=GcsConfig("project", "bucket", "cuu-quoc/pdf", "cuu-quoc/images", "cuu-quoc/ocr"),
            source=VeridianSource("https://example.test/catalogue", "https://example.test/images", "WNyf", date(1945, 9, 1), date(1955, 4, 30)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        item = Mock(kind="image", issue_id="WNyf19450905", issue_label="1945-09-05_WNyf19450905", page_id="001", source_url="https://example.test/001.jpg", width=10, height=20)

        asset = asset_from_source_item(config, item)

        self.assertEqual(asset.gcs_object, "cuu-quoc/images/1945-09-05_WNyf19450905/001.jpg")

    def test_discovery_does_not_overwrite_existing_ledger_state(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            gcs=GcsConfig("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=UrlListPdfSource(urls=("https://example.test/001.pdf",)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        with TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "state.jsonl"
            source_item = Mock(kind="pdf", source_url="https://example.test/001.pdf")
            with patch("vie_doc_pipeline.workflow.discover_source.iter_source_items", return_value=[source_item]):
                self.assertEqual(len(discover_source_assets(config, ledger_path)), 1)
                self.assertEqual(discover_source_assets(config, ledger_path), [])

    def test_discovery_applies_limit_after_source_dispatch(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            gcs=GcsConfig("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=UrlListPdfSource(urls=("https://example.test/001.pdf",)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        source_items = [
            Mock(kind="pdf", source_url="https://example.test/001.pdf"),
            Mock(kind="pdf", source_url="https://example.test/002.pdf"),
        ]
        with TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "state.jsonl"
            with patch("vie_doc_pipeline.workflow.discover_source.iter_source_items", return_value=source_items):
                self.assertEqual(len(discover_source_assets(config, ledger_path, limit=1)), 1)


class _FakeBucket:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    def blob(self, name: str) -> "_FakeBlob":
        return _FakeBlob(name, self.uploads)


class _FakeBlob:
    def __init__(self, name: str, uploads: list[str]) -> None:
        self.name = name
        self.uploads = uploads

    def download_as_bytes(self, timeout: int) -> bytes:
        return b"source image is inspected but never copied"

    def upload_from_string(self, data: bytes, **kwargs: object) -> None:
        self.uploads.append(self.name)


class _FakeStorageClient:
    def __init__(self) -> None:
        self.bucket_instance = _FakeBucket()

    def bucket(self, name: str) -> _FakeBucket:
        return self.bucket_instance
