import unittest

from vie_doc_pipeline.source_adapter import _encode_url


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
