import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, TypeAlias

from vie_doc_pipeline.images.pdf import ExplodeParams


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


def load_config(pub_id: str, config_dir: str = "sources") -> PipelineConfig:
    path = Path(config_dir) / f"{pub_id}.toml"
    if not path.exists():
        raise FileNotFoundError(f"No config found for '{pub_id}' at {path}")
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    config = PipelineConfig(
        publication=parse_publication(required_table(raw, "publication")),
        gcs=parse_gcs(required_table(raw, "gcs")),
        source=parse_source(optional_table(raw, "source")),
        explode=parse_explode(optional_table(raw, "explode")),
        ocr=parse_ocr(optional_table(raw, "ocr")),
        acquisition=parse_acquisition(optional_table(raw, "acquisition")),
    )
    _validate_config(config)
    return config


def parse_publication(raw: Mapping[str, object]) -> PublicationConfig:
    return PublicationConfig(
        id=required_string(raw, "id", "publication"),
        name=required_string(raw, "name", "publication"),
    )


def parse_gcs(raw: Mapping[str, object]) -> GcsConfig:
    return GcsConfig(
        project=required_string(raw, "project", "gcs"),
        bucket=required_string(raw, "bucket", "gcs"),
        pdf_prefix=required_string(raw, "pdf_prefix", "gcs").rstrip("/"),
        images_prefix=required_string(raw, "images_prefix", "gcs").rstrip("/"),
        ocr_output_prefix=required_string(raw, "ocr_output_prefix", "gcs").rstrip("/"),
    )


def parse_source(raw: Mapping[str, object]) -> SourceConfig:
    """Decode a TOML source table into one valid, typed source variant."""
    source_type = optional_string(raw.get("type"), "source.type") or "local_dir"
    match source_type:
        case "veridian":
            return VeridianSource(
                catalogue_url=required_string(raw, "catalogue_url", "source"),
                image_server_url=required_string(raw, "image_server_url", "source"),
                title_id=required_string(raw, "title_id", "source"),
                from_date=parse_required_date(raw, "from_date"),
                to_date=parse_required_date(raw, "to_date"),
            )
        case "web_page":
            return WebPagePdfSource(page_url=required_string(raw, "page_url", "source"))
        case "url_sequence":
            return UrlSequencePdfSource(
                base_url=required_string(raw, "base_url", "source"),
                pattern=optional_string(raw.get("pattern"), "source.pattern") or "{}.pdf",
                issue_range=parse_issue_range(raw.get("range")),
                extra_urls=parse_strings(raw.get("urls", ()), "urls"),
            )
        case "url_list":
            return UrlListPdfSource(urls=parse_strings(raw.get("urls", ()), "urls"))
        case "local_dir":
            return LocalPdfSource(path=optional_string(raw.get("path"), "source.path") or ".")
        case _:
            raise ValueError(f"Unknown source.type: {source_type!r}")


def parse_explode(raw: Mapping[str, object]) -> ExplodeParams:
    return ExplodeParams(
        negate_png=parse_bool(raw.get("negate_png", False), "explode.negate_png"),
        preserve_crop=parse_bool(raw.get("preserve_crop", False), "explode.preserve_crop"),
        preserve_orientation=parse_bool(raw.get("preserve_orientation", False), "explode.preserve_orientation"),
        no_annotations=parse_bool(raw.get("no_annotations", False), "explode.no_annotations"),
        no_text=parse_bool(raw.get("no_text", False), "explode.no_text"),
        dpi=parse_int(raw.get("dpi", 300), "explode.dpi"),
    )


def parse_ocr(raw: Mapping[str, object]) -> OcrConfig:
    return OcrConfig(language_hints=parse_strings(raw.get("language_hints", ()), "ocr.language_hints"))


def parse_acquisition(raw: Mapping[str, object]) -> AcquisitionConfig:
    return AcquisitionConfig(
        max_workers=parse_int(raw.get("max_workers", 4), "acquisition.max_workers"),
        min_request_interval_seconds=parse_float(raw.get("min_request_interval_seconds", 0.0), "acquisition.min_request_interval_seconds"),
        max_attempts=parse_int(raw.get("max_attempts", 5), "acquisition.max_attempts"),
        backoff_factor=parse_float(raw.get("backoff_factor", 1.0), "acquisition.backoff_factor"),
        backoff_max_seconds=parse_float(raw.get("backoff_max_seconds", 30.0), "acquisition.backoff_max_seconds"),
        backoff_jitter_seconds=parse_float(raw.get("backoff_jitter_seconds", 0.5), "acquisition.backoff_jitter_seconds"),
    )


def required_table(raw: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = raw.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a table")
    return value


def optional_table(raw: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = raw.get(field, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a table")
    return value


def optional_string(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def required_string(raw: Mapping[str, object], field: str, section: str) -> str:
    value = optional_string(raw.get(field), f"{section}.{field}")
    if not value:
        raise ValueError(f"{section}.{field} is required")
    return value


def parse_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"source.{field} must be an array of strings")
    return tuple(value)


def parse_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be true or false")
    return value


def parse_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def parse_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    return float(value)


def parse_issue_range(value: object | None) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise ValueError("source.range must be a two-item integer array")
    start, end = value
    if start > end:
        raise ValueError("source.range start must not exceed end")
    return start, end


def parse_optional_date(value: object | None, field: str) -> date | None:
    """Convert an optional TOML ISO date string into a typed configuration value."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from error


def parse_required_date(raw: Mapping[str, object], field: str) -> date:
    value = parse_optional_date(raw.get(field), f"source.{field}")
    if value is None:
        raise ValueError(f"source.{field} is required")
    return value


def _validate_config(config: PipelineConfig) -> None:
    if config.acquisition.max_workers < 1:
        raise ValueError("acquisition.max_workers must be at least one")
    if config.acquisition.min_request_interval_seconds < 0:
        raise ValueError("acquisition.min_request_interval_seconds must be non-negative")
    if config.acquisition.max_attempts < 1:
        raise ValueError("acquisition.max_attempts must be at least one")
