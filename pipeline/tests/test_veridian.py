from datetime import date
import unittest

from vie_doc_pipeline.pipeline_config import SourceConfig
from vie_doc_pipeline.veridian import VeridianClient, _issues_from_month_html, _month_urls, parse_pages


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
        months = _month_urls(title_html, "http://example.test/baochi/cgi-bin/baochi", "WNyf")
        self.assertEqual(months, [(1951, 1, "http://example.test/baochi/cgi-bin/baochi?a=cl&cl=CL2.1951.01&sp=WNyf&e=x")])
        month_html = '<a href="?a=d&amp;d=WNyf19510101&amp;e=x">1 Tháng Một</a>'
        issues = _issues_from_month_html(month_html, "WNyf")
        self.assertEqual(issues[0].published_on, date(1951, 1, 1))

    def test_full_page_url_uses_native_crop(self) -> None:
        config = SourceConfig(type="veridian", title_id="WNyf")
        page = parse_pages("var documentOID = 'WNyf19510101'; var pageImageSizes = { '1.1':{'w':1890,'h':2602} };", "WNyf19510101")[0]
        url = VeridianClient(config).page_image_url(page)
        self.assertIn("oid=WNyf19510101.1.1", url)
        self.assertIn("width=1890", url)
        self.assertIn("crop=0%2C0%2C1890%2C2602", url)


if __name__ == "__main__":
    unittest.main()
