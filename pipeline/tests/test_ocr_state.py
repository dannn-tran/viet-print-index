import unittest

from vie_doc_pipeline.workflow.ocr import _parse_gs_uri


class OcrStateTest(unittest.TestCase):
    def test_parses_output_prefix(self) -> None:
        self.assertEqual(
            _parse_gs_uri("gs://vie-doc/nlv-cuu-quoc/ocr/jobs/job-1/batch_0/"),
            ("vie-doc", "nlv-cuu-quoc/ocr/jobs/job-1/batch_0/"),
        )
