import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, TypeAlias

from vie_doc_pipeline.explode_mem import ExplodeParams


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
        publication=parse_publication(raw["publication"]),
        gcs=parse_gcs(raw["gcs"]),
        source=parse_source(raw.get("source", {})),
        explode=parse_explode(raw.get("explode", {})),
        ocr=parse_ocr(raw.get("ocr", {})),
        acquisition=parse_acquisition(raw.get("acquisition", {})),
    )
    _validate_config(config)
    return config


def parse_publication(raw: Mapping[str, object]) -> PublicationConfig:
    return PublicationConfig(id=str(raw["id"]), name=str(raw["name"]))


def parse_gcs(raw: Mapping[str, object]) -> GcsConfig:
    return GcsConfig(
        project=str(raw["project"]),
        bucket=str(raw["bucket"]),
        pdf_prefix=str(raw["pdf_prefix"]).rstrip("/"),
        images_prefix=str(raw["images_prefix"]).rstrip("/"),
        ocr_output_prefix=str(raw["ocr_output_prefix"]).rstrip("/"),
    )


def parse_source(raw: Mapping[str, object]) -> SourceConfig:
    """Decode a TOML source table into one valid, typed source variant."""
    source_type = str(raw.get("type", "local_dir"))
    match source_type:
        case "veridian":
            return VeridianSource(
                catalogue_url=required_string(raw, "catalogue_url"),
                image_server_url=required_string(raw, "image_server_url"),
                title_id=required_string(raw, "title_id"),
                from_date=parse_required_date(raw, "from_date"),
                to_date=parse_required_date(raw, "to_date"),
            )
        case "web_page":
            return WebPagePdfSource(page_url=required_string(raw, "page_url"))
        case "url_sequence":
            return UrlSequencePdfSource(
                base_url=required_string(raw, "base_url"),
                pattern=optional_string(raw.get("pattern")) or "{}.pdf",
                issue_range=parse_issue_range(raw.get("range")),
                extra_urls=parse_strings(raw.get("urls", ()), "urls"),
            )
        case "url_list":
            return UrlListPdfSource(urls=parse_strings(raw.get("urls", ()), "urls"))
        case "local_dir":
            return LocalPdfSource(path=optional_string(raw.get("path")) or ".")
        case _:
            raise ValueError(f"Unknown source.type: {source_type!r}")


def parse_explode(raw: Mapping[str, object]) -> ExplodeParams:
    return ExplodeParams(
        negate_png=bool(raw.get("negate_png", False)),
        preserve_crop=bool(raw.get("preserve_crop", False)),
        preserve_orientation=bool(raw.get("preserve_orientation", False)),
        no_annotations=bool(raw.get("no_annotations", False)),
        no_text=bool(raw.get("no_text", False)),
        dpi=int(raw.get("dpi", 300)),
    )


def parse_ocr(raw: Mapping[str, object]) -> OcrConfig:
    return OcrConfig(language_hints=tuple(raw.get("language_hints", [])))  # type: ignore[arg-type]


def parse_acquisition(raw: Mapping[str, object]) -> AcquisitionConfig:
    return AcquisitionConfig(
        max_workers=int(raw.get("max_workers", 4)),
        min_request_interval_seconds=float(raw.get("min_request_interval_seconds", 0.0)),
        max_attempts=int(raw.get("max_attempts", 5)),
        backoff_factor=float(raw.get("backoff_factor", 1.0)),
        backoff_max_seconds=float(raw.get("backoff_max_seconds", 30.0)),
        backoff_jitter_seconds=float(raw.get("backoff_jitter_seconds", 0.5)),
    )


def optional_string(value: object | None) -> str | None:
    return str(value) if value is not None else None


def required_string(raw: Mapping[str, object], field: str) -> str:
    value = optional_string(raw.get(field))
    if not value:
        raise ValueError(f"source.{field} is required")
    return value


def parse_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"source.{field} must be an array of strings")
    return tuple(value)


def parse_issue_range(value: object | None) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, int) for item in value):
        raise ValueError("source.range must be a two-item integer array")
    start, end = value
    if start > end:
        raise ValueError("source.range start must not exceed end")
    return start, end


def parse_optional_date(value: object | None, field: str) -> date | None:
    """Convert an optional TOML ISO date string into a typed configuration value."""
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
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
