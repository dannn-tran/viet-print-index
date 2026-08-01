"""Conservative image inversion detection and byte-level transformation."""

from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class InversionCheck:
    inverted: bool
    needs_review: bool


def check_inversion(image_bytes: bytes) -> InversionCheck:
    """Classify a scan conservatively from its grayscale brightness.

    Very dark scans are likely colour-inverted. Mid-tone material—especially
    covers and photographs—is preserved and surfaced for review.
    """
    pix = fitz.Pixmap(image_bytes)
    if pix.n > 1:
        pix = fitz.Pixmap(fitz.csGRAY, pix)
    brightness = sum(pix.samples) / len(pix.samples) if pix.samples else 128.0
    if brightness < 30:
        return InversionCheck(inverted=True, needs_review=False)
    if brightness < 115:
        return InversionCheck(inverted=False, needs_review=True)
    return InversionCheck(inverted=False, needs_review=False)


def invert_image(image_bytes: bytes, filename: str) -> bytes:
    pix = fitz.Pixmap(image_bytes)
    pix.invert_irect(pix.irect)
    return pix.tobytes("png" if filename.lower().endswith(".png") else "jpeg", jpg_quality=95)
