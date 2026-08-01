"""Inspect PDF-to-image variants before normalizing a collection."""

from pathlib import Path

import fitz

from vie_doc_pipeline.explode_mem import ExplodeParams, explode_pdf_bytes
from vie_doc_pipeline.pipeline_config import PipelineConfig

_VARIANTS: list[tuple[str, ExplodeParams]] = [
    ("raw", ExplodeParams()),
    ("render", ExplodeParams(preserve_crop=True)),
    ("render+negate", ExplodeParams(preserve_crop=True, negate_png=True)),
    ("render+no-text", ExplodeParams(preserve_crop=True, no_text=True)),
    ("render+no-text+negate", ExplodeParams(preserve_crop=True, no_text=True, negate_png=True)),
]


def run_image_calibration(config: PipelineConfig, pdf_path: Path, out_dir: Path | None = None) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    base = out_dir or Path("calibrate") / config.publication.id / pdf_path.stem
    pdf_bytes = pdf_path.read_bytes()
    for variant_name, params in _VARIANTS:
        images = explode_pdf_bytes(pdf_bytes, params)
        variant_dir = base / variant_name
        variant_dir.mkdir(parents=True, exist_ok=True)
        for filename, data in images:
            (variant_dir / filename).write_bytes(data)
        print(f"  {variant_name}: {len(images)} images → {variant_dir}")
    _print_hints(pdf_bytes)


def _print_hints(pdf_bytes: bytes) -> None:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    hints: list[str] = []
    if any(len(page.get_text().strip()) > 50 for page in doc):
        hints.append("no_text = true  (digital text layer detected)")
    if (sample := _render_first_page(doc)) and _mean_brightness(sample) < 50:
        hints.append("negate_png = true  (dark background detected)")
    if any(page.rotation != 0 for page in doc):
        hints.append("preserve_orientation = true  (rotated pages detected)")
    if any(page.cropbox != page.mediabox for page in doc):
        hints.append("preserve_crop = true  (crop box differs from media box)")
    print("\nHeuristic suggestions for [explode] in your TOML:" if hints else "\nNo heuristic hints. Try render variants.")
    for hint in hints:
        print(f"  {hint}")


def _render_first_page(doc: fitz.Document) -> bytes | None:
    if not doc.page_count:
        return None
    return doc[0].get_pixmap(matrix=fitz.Matrix(1, 1)).tobytes("png")


def _mean_brightness(png_bytes: bytes) -> float:
    pix = fitz.Pixmap(png_bytes)
    if pix.n > 1:
        pix = fitz.Pixmap(fitz.csGRAY, pix)
    return sum(pix.samples) / len(pix.samples) if pix.samples else 128.0
