from datetime import date
import unittest

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.sources.veridian import iter_pages, issues_from_month_html, month_urls, page_image_url, parse_pages


class VeridianParsingTest(unittest.TestCase):
    def test_parses_full_native_pages(self) -> None:
        html = """
        <script>
        var documentOID = 'WNyf19510101';
        var pageImageSizes = { '1.1':{'w':1890,'h':2602}, '1.2':{'w':1890,'h':2602} };
        </script>
        """
        pages = parse_pages(html, "WNyf19510101")
        self.assertEqual([page.filename for page in pages], ["001.jpg", "002.jpg"])
        self.assertEqual((pages[0].width, pages[0].height), (1890, 2602))

    def test_month_and_issue_discovery(self) -> None:
        title_html = (
            '<a href="/baochi/cgi-bin/baochi?a=cl&amp;cl=CL2.1951.01&amp;sp=WNyf&amp;e=x">T01</a>'
        )
        months = month_urls(title_html, "http://example.test/baochi/cgi-bin/baochi", "WNyf")
        self.assertEqual(months, [(1951, 1, "http://example.test/baochi/cgi-bin/baochi?a=cl&cl=CL2.1951.01&sp=WNyf&e=x")])
        month_html = '<a href="?a=d&amp;d=WNyf19510101&amp;e=x">1 Tháng Một</a>'
        issues = issues_from_month_html(month_html, "WNyf")
        self.assertEqual(issues[0].published_on, date(1951, 1, 1))

    def test_full_page_url_uses_native_crop(self) -> None:
        page = parse_pages("var documentOID = 'WNyf19510101'; var pageImageSizes = { '1.1':{'w':1890,'h':2602} };", "WNyf19510101")[0]
        url = page_image_url("http://example.test/imageserver.pl", page)
        self.assertIn("oid=WNyf19510101.1.1", url)
        self.assertIn("width=1890", url)
        self.assertIn("crop=0%2C0%2C1890%2C2602", url)

    def test_discovery_limit_stops_before_later_issue_requests(self) -> None:
        config = SourceConfig(
            type="veridian",
            catalogue_url="https://example.test/catalogue",
            image_server_url="https://example.test/images",
            title_id="WNyf",
            from_date="1951-01-01",
            to_date="1951-01-31",
        )
        requested: list[str] = []

        def fetch(url: str) -> str:
            requested.append(url)
            if "cl=CL1" in url:
                return '<a href="?a=cl&amp;cl=CL2.1951.01&amp;sp=WNyf">Jan</a>'
            if "cl=CL2.1951.01" in url:
                return '<a href="?a=d&amp;d=WNyf19510101">1</a><a href="?a=d&amp;d=WNyf19510102">2</a>'
            return "var documentOID = 'WNyf19510101'; var pageImageSizes = { '1.1':{'w':10,'h':20} };"

        pages = list(iter_pages(config, fetch, limit=1))

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].issue_label, "1951-01-01_WNyf19510101")
        self.assertEqual(sum("a=d" in url for url in requested), 1)


if __name__ == "__main__":
    unittest.main()
