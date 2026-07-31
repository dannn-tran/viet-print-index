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
    title_id: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    delay_seconds: float = 1.0


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

    src_range = src.get("range")
    return PipelineConfig(
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
            title_id=src.get("title_id"),
            from_date=src.get("from_date"),
            to_date=src.get("to_date"),
            delay_seconds=float(src.get("delay_seconds", 1.0)),
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
    )
