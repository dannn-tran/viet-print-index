#!/usr/bin/env python3

# /// script
# dependencies = [
#   "pymupdf>=1.25",
# ]
# requires-python = ">=3.13"
# ///

import argparse
import sys
from pathlib import Path

import fitz


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="explode",
        description="Extract images from PDF files.",
    )
    parser.add_argument(
        "-i", dest="pdf_input", required=True, metavar="PDF_DIR_OR_FILE",
        help="Directory containing PDFs, or a single PDF file",
    )
    parser.add_argument(
        "-o", dest="output_dir", required=True, metavar="OUTPUT_DIR",
        help="Directory to write extracted images into",
    )
    parser.add_argument(
        "--negate-png", action="store_true",
        help="Negate PNG images after extraction",
    )
    parser.add_argument(
        "--preserve-crop", action="store_true",
        help="Honour PDF crop boxes; renders full pages (one image per page)",
    )
    parser.add_argument(
        "--preserve-orientation", action="store_true",
        help="Apply PDF page rotation; renders full pages (one image per page)",
    )
    parser.add_argument(
        "--no-annotations", action="store_true",
        help="Remove PDF annotation objects (sticky notes, highlights, etc.) before rendering",
    )
    parser.add_argument(
        "--no-text", action="store_true",
        help="Remove text layer from page content stream before rendering (e.g. OCR overlays)",
    )
    parser.add_argument(
        "--dpi", type=int, default=300, metavar="N",
        help="Render resolution; only applies with --preserve-crop or --preserve-orientation (default: 300)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing output instead of skipping already-processed PDFs",
    )
    return parser.parse_args()


def dir_has_images(path: Path) -> bool:
    image_exts = {".jpg", ".jpeg", ".png", ".jp2"}
    return any(f.suffix.lower() in image_exts for f in path.iterdir())


def strip_annotations(doc: fitz.Document) -> None:
    for page in doc:
        for annot in list(page.annots()):
            page.delete_annot(annot)


def strip_text_layer(doc: fitz.Document) -> None:
    for page in doc:
        page.add_redact_annot(page.rect)
        page.apply_redactions(images=0, graphics=0)  # 0 = keep images and vector graphics, remove text


def extract_raw(doc: fitz.Document, img_dir: Path) -> None:
    pnm_exts = {"pnm", "ppm", "pbm", "pgm"}
    seen: set[int] = set()
    index = 0
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen:
                continue
            seen.add(xref)
            base = doc.extract_image(xref)
            ext: str = base["ext"]
            data: bytes = base["image"]
            index += 1
            if ext in pnm_exts:
                pix = fitz.Pixmap(data)
                pix.save(str(img_dir / f"{index:03d}.jpg"), jpg_quality=85)
            else:
                suffix = "jpg" if ext == "jpeg" else ext
                (img_dir / f"{index:03d}.{suffix}").write_bytes(data)


def render_pages(doc: fitz.Document, img_dir: Path, *, dpi: int, preserve_crop: bool) -> None:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for i, page in enumerate(doc):
        clip = page.rect if preserve_crop else None
        pix = page.get_pixmap(matrix=mat, clip=clip)
        pix.save(str(img_dir / f"{i + 1:03d}.png"))


def negate_pngs(img_dir: Path) -> None:
    for png_path in img_dir.glob("*.png"):
        pix = fitz.Pixmap(str(png_path))
        pix.invert_irect(pix.irect)
        pix.save(str(png_path))


def process_pdf(pdf_path: Path, img_dir: Path, args: argparse.Namespace) -> None:
    img_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))

    if args.no_annotations:
        strip_annotations(doc)
    if args.no_text:
        strip_text_layer(doc)

    if args.preserve_crop or args.preserve_orientation:
        render_pages(doc, img_dir, dpi=args.dpi, preserve_crop=args.preserve_crop)
    else:
        extract_raw(doc, img_dir)

    if args.negate_png:
        negate_pngs(img_dir)


def main() -> None:
    args = parse_args()

    pdf_input = Path(args.pdf_input)
    output_dir = Path(args.output_dir)

    if pdf_input.is_file():
        pdf_files = [pdf_input]
        pdf_dir = pdf_input.parent
    elif pdf_input.is_dir():
        pdf_dir = pdf_input
        pdf_files = sorted(pdf_input.glob("*.pdf"))
    else:
        print(f"Error: '{pdf_input}' is not a file or directory", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_files:
        img_dir = output_dir / pdf_path.stem

        if img_dir.exists() and dir_has_images(img_dir):
            if not args.overwrite:
                print(f"Skipping {pdf_path}")
                continue
            for f in img_dir.iterdir():
                if f.is_file():
                    f.unlink()

        print(f"Processing {pdf_path}...")
        process_pdf(pdf_path, img_dir, args)

    print("Done.")


if __name__ == "__main__":
    main()
