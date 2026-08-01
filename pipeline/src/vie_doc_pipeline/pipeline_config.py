import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

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
class SourceConfig:
    type: str
    page_url: str | None = None
    base_url: str | None = None
    pattern: str | None = None
    range: tuple[int, int] | None = None
    urls: list[str] = field(default_factory=list)
    path: str | None = None
    catalogue_url: str | None = None
    image_server_url: str | None = None
    title_id: str | None = None
    from_date: str | None = None
    to_date: str | None = None


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
    source_range = raw.get("range")
    return SourceConfig(
        type=str(raw.get("type", "local_dir")),
        page_url=optional_string(raw.get("page_url")),
        base_url=optional_string(raw.get("base_url")),
        pattern=optional_string(raw.get("pattern")),
        range=tuple(source_range) if source_range else None,  # type: ignore[arg-type]
        urls=list(raw.get("urls", [])),  # type: ignore[arg-type]
        path=optional_string(raw.get("path")),
        catalogue_url=optional_string(raw.get("catalogue_url")),
        image_server_url=optional_string(raw.get("image_server_url")),
        title_id=optional_string(raw.get("title_id")),
        from_date=optional_string(raw.get("from_date")),
        to_date=optional_string(raw.get("to_date")),
    )


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


def _validate_config(config: PipelineConfig) -> None:
    if config.source.type == "veridian":
        missing = [
            field for field, value in {
                "source.title_id": config.source.title_id,
                "source.catalogue_url": config.source.catalogue_url,
                "source.image_server_url": config.source.image_server_url,
                "source.from_date": config.source.from_date,
                "source.to_date": config.source.to_date,
            }.items() if not value
        ]
        if missing:
            raise ValueError(f"Veridian source is missing required configuration: {', '.join(missing)}")
    if config.acquisition.max_workers < 1:
        raise ValueError("acquisition.max_workers must be at least one")
    if config.acquisition.min_request_interval_seconds < 0:
        raise ValueError("acquisition.min_request_interval_seconds must be non-negative")
    if config.acquisition.max_attempts < 1:
        raise ValueError("acquisition.max_attempts must be at least one")
