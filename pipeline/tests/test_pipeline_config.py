import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.pipeline_config import parse_source, load_config


class PipelineConfigTest(unittest.TestCase):
    def test_parse_source_normalizes_optional_values(self) -> None:
        source = parse_source({"type": "url_sequence", "range": [1, 2], "urls": ["extra.pdf"]})

        self.assertEqual(source.range, (1, 2))
        self.assertEqual(source.urls, ["extra.pdf"])
        self.assertIsNone(source.page_url)

    def test_rejects_incomplete_veridian_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.toml"
            path.write_text("""
[publication]
id = "example"
name = "Example"
[gcs]
project = "project"
bucket = "bucket"
pdf_prefix = "pdf"
images_prefix = "images"
ocr_output_prefix = "ocr"
[source]
type = "veridian"
catalogue_url = "https://example.test/catalogue"
image_server_url = "https://example.test/images"
title_id = "WNyf"
""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "from_date"):
                load_config("example", directory)
