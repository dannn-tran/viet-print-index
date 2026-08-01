import unittest

from google.api_core import exceptions as google_exceptions
from vie_doc_pipeline.models import PdfAsset
from vie_doc_pipeline.sources.http import SourceHttpError, TransientSourceError
from vie_doc_pipeline.workflow.download_source import AlreadyDownloaded, DownloadFailed, Downloaded, _failure_details, summarize_downloads
from vie_doc_pipeline.workflow.normalize_images import summarize_normalization
from vie_doc_pipeline.workflow.results import NormalizationSummary


class WorkflowResultTest(unittest.TestCase):
    def test_download_summary_includes_all_outcome_kinds(self) -> None:
        asset = PdfAsset("pub", "issue", "https://example.test/issue.pdf", "pub/pdf/issue.pdf")

        summary = summarize_downloads([Downloaded(asset), AlreadyDownloaded(asset), DownloadFailed(asset)])

        self.assertEqual((summary.downloaded, summary.already_present, summary.failed), (1, 1, 1))

    def test_normalization_summary_reduces_each_field_in_one_pass(self) -> None:
        results = iter([NormalizationSummary(created=1), NormalizationSummary(native_registered=2, failed=1)])

        self.assertEqual(summarize_normalization(results), NormalizationSummary(created=1, native_registered=2, failed=1))

    def test_retry_classification_only_retries_known_transient_errors(self) -> None:
        self.assertEqual(_failure_details(TransientSourceError("url", 3, OSError())), (True, 3))
        self.assertEqual(_failure_details(google_exceptions.ServiceUnavailable("temporary")), (True, 1))
        self.assertEqual(_failure_details(SourceHttpError("url", 404)), (False, 1))
        self.assertEqual(_failure_details(ValueError("bug")), (False, 1))
