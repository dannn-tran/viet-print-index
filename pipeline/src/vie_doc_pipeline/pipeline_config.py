import tomllib
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

    pub = raw["publication"]
    gcs = raw["gcs"]
    src = raw.get("source", {})
    exp = raw.get("explode", {})
    ocr = raw.get("ocr", {})
    acquisition = raw.get("acquisition", {})

    src_range = src.get("range")
    config = PipelineConfig(
        publication=PublicationConfig(
            id=pub["id"],
            name=pub["name"],
        ),
        gcs=GcsConfig(
            project=gcs["project"],
            bucket=gcs["bucket"],
            pdf_prefix=gcs["pdf_prefix"].rstrip("/"),
            images_prefix=gcs["images_prefix"].rstrip("/"),
            ocr_output_prefix=gcs["ocr_output_prefix"].rstrip("/"),
        ),
        source=SourceConfig(
            type=src.get("type", "local_dir"),
            page_url=src.get("page_url"),
            base_url=src.get("base_url"),
            pattern=src.get("pattern"),
            range=tuple(src_range) if src_range else None,
            urls=src.get("urls", []),
            path=src.get("path"),
            catalogue_url=src.get("catalogue_url"),
            image_server_url=src.get("image_server_url"),
            title_id=src.get("title_id"),
            from_date=src.get("from_date"),
            to_date=src.get("to_date"),
        ),
        explode=ExplodeParams(
            negate_png=exp.get("negate_png", False),
            preserve_crop=exp.get("preserve_crop", False),
            preserve_orientation=exp.get("preserve_orientation", False),
            no_annotations=exp.get("no_annotations", False),
            no_text=exp.get("no_text", False),
            dpi=exp.get("dpi", 300),
        ),
        ocr=OcrConfig(
            language_hints=tuple(ocr.get("language_hints", [])),
        ),
        acquisition=AcquisitionConfig(
            max_workers=int(acquisition.get("max_workers", 4)),
            min_request_interval_seconds=float(acquisition.get("min_request_interval_seconds", 0.0)),
            max_attempts=int(acquisition.get("max_attempts", 5)),
            backoff_factor=float(acquisition.get("backoff_factor", 1.0)),
            backoff_max_seconds=float(acquisition.get("backoff_max_seconds", 30.0)),
            backoff_jitter_seconds=float(acquisition.get("backoff_jitter_seconds", 0.5)),
        ),
    )
    _validate_config(config)
    return config


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
