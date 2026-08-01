import tempfile
import unittest
from pathlib import Path

from vie_doc_pipeline.pipeline_config import load_config


class PipelineConfigTest(unittest.TestCase):
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
