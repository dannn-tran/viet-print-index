import unittest

from google.api_core import exceptions as google_exceptions
import typer
from vie_doc_pipeline.cli import _normalization_selection
from vie_doc_pipeline.assets import PdfAsset
from vie_doc_pipeline.ledger.events import failed, source_fetched
from vie_doc_pipeline.sources.http import SourceHttpError, TransientSourceError
from vie_doc_pipeline.workflow.fetch_source import AlreadyPresent, Fetched, FetchFailed, _failure_details, _summarize_fetches
from vie_doc_pipeline.workflow.normalize_images import _summarize_normalization
from vie_doc_pipeline.workflow.normalize_images import AllNormalizationCandidates, ImageNormalizationCandidates, NormalizationSummary, SourceNormalizationCandidates


class WorkflowResultTest(unittest.TestCase):
    def test_fetch_summary_includes_all_outcome_kinds(self) -> None:
        asset = PdfAsset("pub", "issue", "https://example.test/issue.pdf", "pub/pdf/issue.pdf")

        summary = _summarize_fetches([
            Fetched(asset, source_fetched(asset, checksum="", size_bytes=0)),
            AlreadyPresent(asset, source_fetched(asset, checksum="", size_bytes=0)),
            FetchFailed(asset, failed(asset.key, stage="fetch", error="failed")),
        ])

        self.assertEqual((summary.fetched, summary.already_present, summary.failed), (1, 1, 1))

    def test_normalization_summary_reduces_each_field_in_one_pass(self) -> None:
        results = iter([NormalizationSummary(created=1), NormalizationSummary(native_registered=2, failed=1)])

        self.assertEqual(_summarize_normalization(results), NormalizationSummary(created=1, native_registered=2, failed=1))

    def test_retry_classification_only_retries_known_transient_errors(self) -> None:
        self.assertEqual(_failure_details(TransientSourceError("url", 3, OSError())), (True, 3))
        self.assertEqual(_failure_details(google_exceptions.ServiceUnavailable("temporary")), (True, 1))
        self.assertEqual(_failure_details(SourceHttpError("url", 404)), (False, 1))
        self.assertEqual(_failure_details(ValueError("bug")), (False, 1))

    def test_normalization_selection_has_one_explicit_mode(self) -> None:
        self.assertEqual(_normalization_selection(None, None), AllNormalizationCandidates())
        self.assertEqual(_normalization_selection("issue", None), SourceNormalizationCandidates("issue"))
        self.assertEqual(_normalization_selection(None, "pub/issue/001"), ImageNormalizationCandidates("pub/issue/001"))
        with self.assertRaises(typer.BadParameter):
            _normalization_selection("issue", "pub/issue/001")
