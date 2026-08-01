"""Inspect PDF-to-image variants before normalizing a collection."""

from pathlib import Path

import fitz

from vie_doc_pipeline.images.pdf import explode_pdf_bytes
from vie_doc_pipeline.config.models import ExplodeParams
from vie_doc_pipeline.config.models import PipelineConfig
from vie_doc_pipeline.domain.results import CalibrationSummary, CalibrationVariantSummary

_VARIANTS: list[tuple[str, ExplodeParams]] = [
    ("raw", ExplodeParams()),
    ("render", ExplodeParams(preserve_crop=True)),
    ("render+negate", ExplodeParams(preserve_crop=True, negate_png=True)),
    ("render+no-text", ExplodeParams(preserve_crop=True, no_text=True)),
    ("render+no-text+negate", ExplodeParams(preserve_crop=True, no_text=True, negate_png=True)),
]


def run_image_calibration(config: PipelineConfig, pdf_path: Path, out_dir: Path | None = None) -> CalibrationSummary:
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    base = out_dir or Path("calibrate") / config.publication.id / pdf_path.stem
    pdf_bytes = pdf_path.read_bytes()
    variants: list[CalibrationVariantSummary] = []
    for variant_name, params in _VARIANTS:
        images = explode_pdf_bytes(pdf_bytes, params)
        variant_dir = base / variant_name
        variant_dir.mkdir(parents=True, exist_ok=True)
        for filename, data in images:
            (variant_dir / filename).write_bytes(data)
        variants.append(CalibrationVariantSummary(variant_name, len(images), str(variant_dir)))
    return CalibrationSummary(tuple(variants), tuple(_hints(pdf_bytes)))


def _hints(pdf_bytes: bytes) -> list[str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        hints: list[str] = []
        if any(len(page.get_text().strip()) > 50 for page in doc):
            hints.append("no_text = true  (digital text layer detected)")
        if (sample := _render_first_page(doc)) and _mean_brightness(sample) < 50:
            hints.append("negate_png = true  (dark background detected)")
        if any(page.rotation != 0 for page in doc):
            hints.append("preserve_orientation = true  (rotated pages detected)")
        if any(page.cropbox != page.mediabox for page in doc):
            hints.append("preserve_crop = true  (crop box differs from media box)")
        return hints
    finally:
        doc.close()


def _render_first_page(doc: fitz.Document) -> bytes | None:
    if not doc.page_count:
        return None
    return doc[0].get_pixmap(matrix=fitz.Matrix(1, 1)).tobytes("png")


def _mean_brightness(png_bytes: bytes) -> float:
    pix = fitz.Pixmap(png_bytes)
    if pix.n > 1:
        pix = fitz.Pixmap(fitz.csGRAY, pix)
    return sum(pix.samples) / len(pix.samples) if pix.samples else 128.0
