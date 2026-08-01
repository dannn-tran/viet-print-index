"""Validated configuration values used by the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TypeAlias



@dataclass(frozen=True)
class ExplodeParams:
    negate_png: bool = False
    preserve_crop: bool = False
    preserve_orientation: bool = False
    no_annotations: bool = False
    no_text: bool = False
    dpi: int = 300


@dataclass(frozen=True)
class PublicationConfig:
    id: str
    name: str


@dataclass(frozen=True)
class GcsConfig:
    project: str
    bucket: str
    pdf_prefix: str
    images_prefix: str
    ocr_output_prefix: str


@dataclass(frozen=True)
class VeridianSource:
    catalogue_url: str
    image_server_url: str
    title_id: str
    from_date: date
    to_date: date


@dataclass(frozen=True)
class WebPagePdfSource:
    page_url: str


@dataclass(frozen=True)
class UrlSequencePdfSource:
    base_url: str
    pattern: str
    issue_range: tuple[int, int]
    extra_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class UrlListPdfSource:
    urls: tuple[str, ...]


@dataclass(frozen=True)
class LocalPdfSource:
    path: str


SourceConfig: TypeAlias = (
    VeridianSource | WebPagePdfSource | UrlSequencePdfSource | UrlListPdfSource | LocalPdfSource
)


@dataclass(frozen=True)
class AcquisitionConfig:
    max_workers: int = 4
    min_request_interval_seconds: float = 0.0
    max_attempts: int = 5
    backoff_factor: float = 1.0
    backoff_max_seconds: float = 30.0
    backoff_jitter_seconds: float = 0.5


@dataclass(frozen=True)
class OcrConfig:
    language_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineConfig:
    publication: PublicationConfig
    gcs: GcsConfig
    source: SourceConfig
    explode: ExplodeParams
    ocr: OcrConfig
    acquisition: AcquisitionConfig = AcquisitionConfig()
