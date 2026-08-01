"""Validated configuration records and TOML loading."""

import hashlib
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
class GcsTarget:
    """Google Cloud Storage target for durable source, image, and OCR objects."""

    project: str
    bucket: str
    pdf_prefix: str
    images_prefix: str
    ocr_output_prefix: str
    type: Literal["gcs"] = "gcs"


@dataclass(frozen=True)
class LocalTarget:
    """Filesystem target using paths relative to one local root directory."""

    root: str = "."
    pdf_prefix: str = "pdf"
    images_prefix: str = "images"
    ocr_output_prefix: str = "ocr"
    type: Literal["local"] = "local"


TargetStorage: TypeAlias = GcsTarget | LocalTarget


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
class SourceRequestsConfig:
    """Concurrency, pacing, and retry policy for requests to source servers."""

    max_concurrent_requests: int = 4
    min_interval_seconds: float = 0.0
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
    target: TargetStorage
    source: SourceConfig
    explode: ExplodeParams
    ocr: OcrConfig
    source_requests: SourceRequestsConfig = SourceRequestsConfig()
    config_sha256: str | None = None


def load_config(pub_id: str, config_dir: str = "sources") -> PipelineConfig:
    path = Path(config_dir) / f"{pub_id}.toml"
    if not path.exists():
        raise FileNotFoundError(f"No config found for '{pub_id}' at {path}")
    raw_bytes = path.read_bytes()
    raw = tomllib.loads(raw_bytes.decode("utf-8"))

    config = PipelineConfig(
        publication=parse_publication(_required_table(raw, "publication")),
        target=parse_target(_required_table(raw, "target")),
        source=parse_source(_optional_table(raw, "source")),
        explode=parse_explode(_optional_table(raw, "explode")),
        ocr=parse_ocr(_optional_table(raw, "ocr")),
        source_requests=parse_source_requests(_optional_table(raw, "source_requests")),
        config_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )
    _validate_config(config)
    return config


def parse_publication(raw: Mapping[str, object]) -> PublicationConfig:
    return PublicationConfig(
        id=_required_string(raw, "id", "publication"),
        name=_required_string(raw, "name", "publication"),
    )


def parse_target(raw: Mapping[str, object]) -> TargetStorage:
    """Decode the configured durable target into one storage variant."""
    target_type = _optional_string(raw.get("type"), "target.type")
    match target_type:
        case "gcs":
            return GcsTarget(
                project=_required_string(raw, "project", "target"),
                bucket=_required_string(raw, "bucket", "target"),
                pdf_prefix=_required_string(raw, "pdf_prefix", "target").rstrip("/"),
                images_prefix=_required_string(raw, "images_prefix", "target").rstrip("/"),
                ocr_output_prefix=_required_string(raw, "ocr_output_prefix", "target").rstrip("/"),
            )
        case "local":
            return LocalTarget(
                root=_optional_string(raw.get("root"), "target.root") or ".",
                pdf_prefix=_optional_string(raw.get("pdf_prefix"), "target.pdf_prefix") or "pdf",
                images_prefix=_optional_string(raw.get("images_prefix"), "target.images_prefix") or "images",
                ocr_output_prefix=(
                    _optional_string(raw.get("ocr_output_prefix"), "target.ocr_output_prefix") or "ocr"
                ),
            )
        case _:
            raise ValueError(f"Unknown target.type: {target_type!r}; expected 'gcs' or 'local'")


def parse_source(raw: Mapping[str, object]) -> SourceConfig:
    """Decode a TOML source table into one valid, typed source variant."""
    source_type = _optional_string(raw.get("type"), "source.type") or "local_dir"
    match source_type:
        case "veridian":
            return VeridianSource(
                catalogue_url=_required_string(raw, "catalogue_url", "source"),
                image_server_url=_required_string(raw, "image_server_url", "source"),
                title_id=_required_string(raw, "title_id", "source"),
                from_date=_parse_required_date(raw, "from_date"),
                to_date=_parse_required_date(raw, "to_date"),
            )
        case "web_page":
            return WebPagePdfSource(page_url=_required_string(raw, "page_url", "source"))
        case "url_sequence":
            return UrlSequencePdfSource(
                base_url=_required_string(raw, "base_url", "source"),
                pattern=_optional_string(raw.get("pattern"), "source.pattern") or "{}.pdf",
                issue_range=_parse_issue_range(raw.get("range")),
                extra_urls=_parse_strings(raw.get("urls", ()), "urls"),
            )
        case "url_list":
            return UrlListPdfSource(urls=_parse_strings(raw.get("urls", ()), "urls"))
        case "local_dir":
            return LocalPdfSource(path=_optional_string(raw.get("path"), "source.path") or ".")
        case _:
            raise ValueError(f"Unknown source.type: {source_type!r}")


def parse_explode(raw: Mapping[str, object]) -> ExplodeParams:
    return ExplodeParams(
        negate_png=_parse_bool(raw.get("negate_png", False), "explode.negate_png"),
        preserve_crop=_parse_bool(raw.get("preserve_crop", False), "explode.preserve_crop"),
        preserve_orientation=_parse_bool(raw.get("preserve_orientation", False), "explode.preserve_orientation"),
        no_annotations=_parse_bool(raw.get("no_annotations", False), "explode.no_annotations"),
        no_text=_parse_bool(raw.get("no_text", False), "explode.no_text"),
        dpi=_parse_int(raw.get("dpi", 300), "explode.dpi"),
    )


def parse_ocr(raw: Mapping[str, object]) -> OcrConfig:
    return OcrConfig(language_hints=_parse_strings(raw.get("language_hints", ()), "ocr.language_hints"))


def parse_source_requests(raw: Mapping[str, object]) -> SourceRequestsConfig:
    return SourceRequestsConfig(
        max_concurrent_requests=_parse_int(
            raw.get("max_concurrent_requests", 4), "source_requests.max_concurrent_requests"
        ),
        min_interval_seconds=_parse_float(
            raw.get("min_interval_seconds", 0.0), "source_requests.min_interval_seconds"
        ),
        max_attempts=_parse_int(raw.get("max_attempts", 5), "source_requests.max_attempts"),
        backoff_factor=_parse_float(raw.get("backoff_factor", 1.0), "source_requests.backoff_factor"),
        backoff_max_seconds=_parse_float(
            raw.get("backoff_max_seconds", 30.0), "source_requests.backoff_max_seconds"
        ),
        backoff_jitter_seconds=_parse_float(
            raw.get("backoff_jitter_seconds", 0.5), "source_requests.backoff_jitter_seconds"
        ),
    )


def _required_table(raw: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = raw.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a table")
    return value


def _optional_table(raw: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = raw.get(field, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a table")
    return value


def _optional_string(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _required_string(raw: Mapping[str, object], field: str, section: str) -> str:
    value = _optional_string(raw.get(field), f"{section}.{field}")
    if not value:
        raise ValueError(f"{section}.{field} is required")
    return value


def _parse_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"source.{field} must be an array of strings")
    return tuple(value)


def _parse_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be true or false")
    return value


def _parse_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _parse_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    return float(value)


def _parse_issue_range(value: object | None) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise ValueError("source.range must be a two-item integer array")
    start, end = value
    if start > end:
        raise ValueError("source.range start must not exceed end")
    return start, end


def _parse_optional_date(value: object | None, field: str) -> date | None:
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


def _parse_required_date(raw: Mapping[str, object], field: str) -> date:
    value = _parse_optional_date(raw.get(field), f"source.{field}")
    if value is None:
        raise ValueError(f"source.{field} is required")
    return value


def _validate_config(config: PipelineConfig) -> None:
    if config.source_requests.max_concurrent_requests < 1:
        raise ValueError("source_requests.max_concurrent_requests must be at least one")
    if config.source_requests.min_interval_seconds < 0:
        raise ValueError("source_requests.min_interval_seconds must be non-negative")
    if config.source_requests.max_attempts < 1:
        raise ValueError("source_requests.max_attempts must be at least one")
    if config.source_requests.backoff_factor < 0:
        raise ValueError("source_requests.backoff_factor must be non-negative")
    if config.source_requests.backoff_max_seconds < 0:
        raise ValueError("source_requests.backoff_max_seconds must be non-negative")
    if config.source_requests.backoff_jitter_seconds < 0:
        raise ValueError("source_requests.backoff_jitter_seconds must be non-negative")
