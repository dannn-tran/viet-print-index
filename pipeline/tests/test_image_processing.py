import unittest

import fitz

from vie_doc_pipeline.images.processing import check_inversion, invert_image


def _png(value: int) -> bytes:
    return fitz.Pixmap(fitz.csGRAY, 2, 2, bytes([value] * 4), False).tobytes("png")


class ImageProcessingTest(unittest.TestCase):
    def test_dark_image_is_inverted(self) -> None:
        self.assertEqual(check_inversion(_png(0)).inverted, True)

    def test_mid_tone_image_requires_review(self) -> None:
        self.assertEqual(check_inversion(_png(80)).needs_review, True)

    def test_light_image_is_kept(self) -> None:
        self.assertEqual(check_inversion(_png(240)).needs_review, False)
        self.assertEqual(check_inversion(_png(240)).inverted, False)

    def test_inversion_preserves_png_encoding(self) -> None:
        self.assertTrue(invert_image(_png(0), "scan.png").startswith(b"\x89PNG"))
