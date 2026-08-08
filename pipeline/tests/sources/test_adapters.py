from datetime import date
from itertools import islice
import unittest
from unittest.mock import patch

from vie_doc_pipeline.common.config import GcsTarget, OcrConfig, PipelineConfig, PublicationConfig, UrlSequencePdfSource, VeridianSource
from vie_doc_pipeline.images.pdf import ExplodeParams
from vie_doc_pipeline.sources.http import _encode_url
from vie_doc_pipeline.sources.factory import open_source_item_provider


class SourceAdapterTest(unittest.TestCase):
    def test_percent_encodes_unicode_path_and_query(self) -> None:
        url = "https://example.test/tư-liệu/Đời mới.pdf?q=văn nghệ&n=1"

        self.assertEqual(
            _encode_url(url),
            "https://example.test/t%C6%B0-li%E1%BB%87u/%C4%90%E1%BB%9Di%20m%E1%BB%9Bi.pdf?q=v%C4%83n%20ngh%E1%BB%87&n=1",
        )

    def test_preserves_existing_percent_escapes(self) -> None:
        self.assertEqual(
            _encode_url("https://example.test/Ngay%20Nay.pdf?q=%C4%91ời"),
            "https://example.test/Ngay%20Nay.pdf?q=%C4%91%E1%BB%9Di",
        )

    def test_sequence_source_includes_explicit_combined_issues(self) -> None:
        config = UrlSequencePdfSource(
            base_url="https://example.test/issues",
            pattern="{:03d}.pdf",
            issue_range=(1, 2),
            extra_urls=("https://example.test/issues/001-002.pdf",),
        )

        pipeline_config = PipelineConfig(
            publication=PublicationConfig("pub", "Publication"),
            target=GcsTarget("project", "bucket", "pub/pdf", "pub/images", "pub/ocr"),
            source=config,
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )

        with patch("vie_doc_pipeline.sources.factory.http_client") as open_http:
            with open_source_item_provider(pipeline_config) as source_item_provider:
                urls = [item.source_url for item in source_item_provider.iter_source_items()]

        open_http.assert_not_called()

        self.assertEqual(urls, [
            "https://example.test/issues/001.pdf",
            "https://example.test/issues/002.pdf",
            "https://example.test/issues/001-002.pdf",
        ])

    def test_factory_opens_and_closes_http_only_for_network_discovery(self) -> None:
        config = PipelineConfig(
            publication=PublicationConfig("pub", "Publication"),
            target=GcsTarget("project", "bucket", "pub/pdf", "pub/images", "pub/ocr"),
            source=VeridianSource(
                "https://example.test/catalogue",
                "https://example.test/images",
                "WNyf",
                date(1951, 1, 1),
                date(1951, 1, 31),
            ),
            explode=ExplodeParams(),
            ocr=OcrConfig(),
        )
        http = _FakeHttpClient()

        with patch("vie_doc_pipeline.sources.factory.http_client", return_value=http) as open_http:
            with open_source_item_provider(config) as source_item_provider:
                self.assertEqual(len(list(islice(source_item_provider.iter_source_items(), 1))), 1)

        open_http.assert_called_once_with(config.source_requests)
        self.assertTrue(http.closed)


class _FakeHttpClient:
    def __init__(self) -> None:
        self.closed = False

    def fetch_text(self, url: str) -> str:
        if "cl=CL1" in url:
            return '<a href="?a=d&amp;d=WNyf19510101">1</a>'
        return "var documentOID = 'WNyf19510101'; var pageImageSizes = { '1.1':{'w':10,'h':20} };"

    def close(self) -> None:
        self.closed = True
