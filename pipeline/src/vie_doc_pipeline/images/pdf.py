import fitz
from vie_doc_pipeline.config.models import ExplodeParams


def explode_pdf_bytes(pdf_bytes: bytes, params: ExplodeParams) -> list[tuple[str, bytes]]:
    """Explode a PDF into page images entirely in memory.

    Returns a list of (filename, image_bytes) pairs.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if params.no_annotations:
        for page in doc:
            for annot in list(page.annots()):
                page.delete_annot(annot)

    if params.no_text:
        for page in doc:
            page.add_redact_annot(page.rect)
            page.apply_redactions(images=0, graphics=0)

    if params.preserve_crop or params.preserve_orientation:
        results = _render_pages(doc, params.dpi, params.preserve_crop)
    else:
        results = _extract_raw(doc)

    if params.negate_png:
        results = [
            (name, _negate_png_bytes(data)) if name.endswith(".png") else (name, data)
            for name, data in results
        ]

    return results


def _extract_raw(doc: fitz.Document) -> list[tuple[str, bytes]]:
    pnm_exts = {"pnm", "ppm", "pbm", "pgm"}
    seen: set[int] = set()
    results: list[tuple[str, bytes]] = []
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
                results.append((f"{index:03d}.jpg", pix.tobytes("jpeg", jpg_quality=85)))
            else:
                suffix = "jpg" if ext == "jpeg" else ext
                results.append((f"{index:03d}.{suffix}", data))
    return results


def _render_pages(doc: fitz.Document, dpi: int, preserve_crop: bool) -> list[tuple[str, bytes]]:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    results: list[tuple[str, bytes]] = []
    for i, page in enumerate(doc):
        clip = page.rect if preserve_crop else None
        pix = page.get_pixmap(matrix=mat, clip=clip)
        results.append((f"{i + 1:03d}.png", pix.tobytes("png")))
    return results


def _negate_png_bytes(data: bytes) -> bytes:
    pix = fitz.Pixmap(data)
    pix.invert_irect(pix.irect)
    return pix.tobytes("png")
