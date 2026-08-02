from datetime import date
from itertools import islice
import unittest
from unittest.mock import patch

from vie_doc_pipeline.config import VeridianSource
from vie_doc_pipeline.sources.veridian import Issue, iter_source_items_from_veridian, _issues_from_catalogue_html, _page_image_url, _parse_pages


class VeridianParsingTest(unittest.TestCase):
    def test_parses_full_native_pages(self) -> None:
        html = """
        <script>
        var documentOID = 'WNyf19510101';
        var pageImageSizes = { '1.1':{'w':1890,'h':2602}, '1.2':{'w':1890,'h':2602} };
        </script>
        """
        pages = _parse_pages(html, "WNyf19510101")
        self.assertEqual([page.filename for page in pages], ["001.jpg", "002.jpg"])
        self.assertEqual((pages[0].width, pages[0].height), (1890, 2602))

    def test_parses_issue_links_from_complete_catalogue(self) -> None:
        catalogue_html = """
        <a href="?a=d&amp;d=WNyf19510101&amp;e=x">1 Tháng Một</a>
        <a href="?a=d&amp;d=WNyf19510101&amp;e=x">duplicate</a>
        <a href="?a=d&amp;d=Other19510101&amp;e=x">other title</a>
        <a href="?a=d&amp;d=WNyf19511301&amp;e=x">invalid date</a>
        """
        with patch("vie_doc_pipeline.sources.veridian.logger.warning") as warning:
            issues = _issues_from_catalogue_html(catalogue_html, "WNyf")

        self.assertEqual(issues, [Issue("WNyf19510101", date(1951, 1, 1))])
        warning.assert_called_once_with(
            "Ignoring Veridian issue ID with an invalid encoded date: %s",
            "WNyf19511301",
        )

    def test_full_page_url_uses_native_crop(self) -> None:
        page = _parse_pages("var documentOID = 'WNyf19510101'; var pageImageSizes = { '1.1':{'w':1890,'h':2602} };", "WNyf19510101")[0]
        url = _page_image_url("http://example.test/imageserver.pl", page)
        self.assertIn("oid=WNyf19510101.1.1", url)
        self.assertIn("width=1890", url)
        self.assertIn("crop=0%2C0%2C1890%2C2602", url)

    def test_discovery_limit_stops_before_later_issue_requests(self) -> None:
        config = VeridianSource(
            catalogue_url="https://example.test/catalogue",
            image_server_url="https://example.test/images",
            title_id="WNyf",
            from_date=date(1951, 1, 1),
            to_date=date(1951, 1, 31),
        )
        requested: list[str] = []

        http = _FakeHttp(requested)

        pages = list(islice(iter_source_items_from_veridian(config, http), 1))

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].issue_label, "1951-01-01_WNyf19510101")
        self.assertTrue(any("ai=1" in url for url in requested))
        self.assertEqual(sum("a=d" in url for url in requested), 1)


if __name__ == "__main__":
    unittest.main()


class _FakeHttp:
    def __init__(self, requested: list[str]) -> None:
        self.requested = requested

    def fetch_text(self, url: str) -> str:
        self.requested.append(url)
        if "cl=CL1" in url:
            return '<a href="?a=d&amp;d=WNyf19510101">1</a><a href="?a=d&amp;d=WNyf19510102">2</a>'
        return "var documentOID = 'WNyf19510101'; var pageImageSizes = { '1.1':{'w':10,'h':20} };"
