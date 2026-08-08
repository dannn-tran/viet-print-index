import unittest
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from vie_doc_pipeline.ledger.events import source_discovered, source_fetched
from vie_doc_pipeline.state import PipelineState
from vie_doc_pipeline.common.assets import ImageAsset
from vie_doc_pipeline.common.config import (
    GcsTarget,
    OcrConfig,
    PipelineConfig,
    PublicationConfig,
    UrlListPdfSource,
    VeridianSource,
    WebPagePdfSource,
)
from vie_doc_pipeline.images.pdf import ExplodeParams
from vie_doc_pipeline.sources.discover import SourceAssetDiscoveryService, _asset_from_source_item
from vie_doc_pipeline.images.normalize import ImageNormalizationService


class AssetDiscoveryTest(unittest.TestCase):
    def test_pdf_document_identity_uses_decoded_file_stem(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            target=GcsTarget("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=WebPagePdfSource(page_url="https://example.test/index"),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
            config_toml="pdf-identity-test",
        )

        source_item = Mock(kind="pdf", source_url="https://example.test/Tu%E1%BA%A7n%20b%C3%A1o%20001.pdf")
        asset = _asset_from_source_item(config, source_item)

        self.assertEqual(asset.document_id, "Tuần báo 001")
        self.assertEqual(asset.target_path, "doi-moi/pdf/Tu%E1%BA%A7n%20b%C3%A1o%20001.pdf")

    def test_native_image_materialization_never_writes_another_object(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="cuu-quoc", name="Cứu Quốc"),
            target=GcsTarget("project", "bucket", "cuu-quoc/pdf", "cuu-quoc/images", "cuu-quoc/ocr"),
            source=VeridianSource("https://example.test/catalogue", "https://example.test/images", "WNyf", date(1945, 9, 1), date(1955, 4, 30)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
            config_toml="native-image-test",
        )
        asset = ImageAsset("cuu-quoc", "issue-001", "001", "https://example.test/001.jpg", "cuu-quoc/images/issue-001/001.jpg")
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.jsonl"
            state = PipelineState.open(state_path, config)
            state.record(source_discovered(asset))
            state.record(source_fetched(asset, checksum="checksum", size_bytes=10))
            store = _FakeTargetStore()

            with patch("vie_doc_pipeline.images.normalize.open_target_store", return_value=nullcontext(store)), \
                 patch("vie_doc_pipeline.images.normalize.check_inversion") as check:
                check.return_value = Mock(inverted=False, needs_review=False)
                summary = ImageNormalizationService(state).execute()

            self.assertEqual(summary.created, 0)
            self.assertEqual(summary.native_registered, 1)
            self.assertEqual(store.uploads, [])
            projected = state.asset_state(asset.key)
            self.assertIsNotNone(projected)
            self.assertEqual(projected.event if projected else None, "image_normalized")
            self.assertFalse(store.closed)

    def test_native_image_path_prefers_human_issue_label(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="cuu-quoc", name="Cứu Quốc"),
            target=GcsTarget("project", "bucket", "cuu-quoc/pdf", "cuu-quoc/images", "cuu-quoc/ocr"),
            source=VeridianSource("https://example.test/catalogue", "https://example.test/images", "WNyf", date(1945, 9, 1), date(1955, 4, 30)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
            config_toml="issue-label-test",
        )
        item = Mock(kind="image", issue_id="WNyf19450905", issue_label="1945-09-05_WNyf19450905", page_id="001", source_url="https://example.test/001.jpg", width=10, height=20)

        asset = _asset_from_source_item(config, item)

        self.assertEqual(asset.target_path, "cuu-quoc/images/1945-09-05_WNyf19450905/001.jpg")

    def test_discovery_does_not_overwrite_existing_event_state(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            target=GcsTarget("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=UrlListPdfSource(urls=("https://example.test/001.pdf",)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
            config_toml="discovery-dedupe-test",
        )
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.jsonl"
            state = PipelineState.open(state_path, config)
            source_item = Mock(kind="pdf", source_url="https://example.test/001.pdf")
            with patch(
                "vie_doc_pipeline.sources.discover.open_source_items",
                return_value=nullcontext(_FakeSourceItemProvider([source_item])),
            ):
                self.assertEqual(len(SourceAssetDiscoveryService(state).execute()), 1)
                self.assertEqual(SourceAssetDiscoveryService(state).execute(), [])

    def test_discovery_applies_limit_after_source_dispatch(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig(id="doi-moi", name="Đời Mới"),
            target=GcsTarget("project", "bucket", "doi-moi/pdf", "doi-moi/images", "doi-moi/ocr"),
            source=UrlListPdfSource(urls=("https://example.test/001.pdf",)),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
            config_toml="discovery-max-items-test",
        )
        source_items = [
            Mock(kind="pdf", source_url="https://example.test/001.pdf"),
            Mock(kind="pdf", source_url="https://example.test/002.pdf"),
        ]
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.jsonl"
            state = PipelineState.open(state_path, config)
            with patch(
                "vie_doc_pipeline.sources.discover.open_source_items",
                return_value=nullcontext(_FakeSourceItemProvider(source_items)),
            ):
                self.assertEqual(len(SourceAssetDiscoveryService(state).execute(max_items=1)), 1)


class _FakeTargetStore:
    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.closed = False

    def read_bytes(self, path: str) -> bytes:
        return b"source image is inspected but never copied"

    def write_bytes(self, path: str, data: bytes, *, content_type: str) -> None:
        self.uploads.append(path)

    def inspect(self, path: str):
        return None

    def close(self) -> None:
        self.closed = True


class _FakeSourceItemProvider:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def iter_source_items(self):
        return iter(self.items)
