from pathlib import Path
import tempfile
import unittest

from vie_doc_pipeline.config import UrlSequencePdfSource, parse_explode, parse_ocr, parse_source, load_config


class PipelineConfigTest(unittest.TestCase):
    def test_parse_source_constructs_a_typed_sequence_source(self) -> None:
        source = parse_source({
            "type": "url_sequence",
            "range": [1, 2],
            "urls": ["extra.pdf"],
            "base_url": "https://example.test/issues",
        })

        self.assertEqual(
            source,
            UrlSequencePdfSource(
                base_url="https://example.test/issues",
                pattern="{}.pdf",
                issue_range=(1, 2),
                extra_urls=("extra.pdf",),
            ),
        )

    def test_rejects_invalid_source_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "source.from_date"):
            parse_source({
                "type": "veridian",
                "catalogue_url": "https://example.test/catalogue",
                "image_server_url": "https://example.test/images",
                "title_id": "WNyf",
                "from_date": "not-a-date",
                "to_date": "1951-01-31",
            })

    def test_rejects_coercible_but_invalid_config_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "explode.negate_png"):
            parse_explode({"negate_png": "false"})
        with self.assertRaisesRegex(ValueError, "ocr.language_hints"):
            parse_ocr({"language_hints": "vi"})
        with self.assertRaisesRegex(ValueError, "source.type"):
            parse_source({"type": 1})

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
