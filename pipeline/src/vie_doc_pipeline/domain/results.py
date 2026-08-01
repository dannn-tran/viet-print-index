"""Typed summaries returned by workflow stages; presentation is handled by the CLI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DownloadSummary:
    downloaded: int = 0
    already_present: int = 0
    failed: int = 0


@dataclass(frozen=True)
class NormalizationSummary:
    created: int = 0
    native_registered: int = 0
    failed: int = 0


@dataclass(frozen=True)
class OcrStatusSummary:
    completed: int = 0
    pending: int = 0


@dataclass(frozen=True)
class OcrSubmissionSummary:
    submitted: int = 0
