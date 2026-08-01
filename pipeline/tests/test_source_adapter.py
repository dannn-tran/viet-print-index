import unittest

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.sources.http import encode_url
from vie_doc_pipeline.sources.pdf import iter_pdf_items


class SourceAdapterTest(unittest.TestCase):
    def test_percent_encodes_unicode_path_and_query(self) -> None:
        url = "https://example.test/tư-liệu/Đời mới.pdf?q=văn nghệ&n=1"

        self.assertEqual(
            encode_url(url),
            "https://example.test/t%C6%B0-li%E1%BB%87u/%C4%90%E1%BB%9Di%20m%E1%BB%9Bi.pdf?q=v%C4%83n%20ngh%E1%BB%87&n=1",
        )

    def test_preserves_existing_percent_escapes(self) -> None:
        self.assertEqual(
            encode_url("https://example.test/Ngay%20Nay.pdf?q=%C4%91ời"),
            "https://example.test/Ngay%20Nay.pdf?q=%C4%91%E1%BB%9Di",
        )

    def test_sequence_source_includes_explicit_combined_issues(self) -> None:
        config = SourceConfig(
            type="url_sequence",
            base_url="https://example.test/issues",
            pattern="{:03d}.pdf",
            range=(1, 2),
            urls=["https://example.test/issues/001-002.pdf"],
        )

        self.assertEqual([item.source_url for item in iter_pdf_items(config, lambda _: "")], [
            "https://example.test/issues/001.pdf",
            "https://example.test/issues/002.pdf",
            "https://example.test/issues/001-002.pdf",
        ])
