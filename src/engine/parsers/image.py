"""
src/engine/parsers/image.py
────────────────────────────
Image parser using pytesseract (Tesseract OCR).

Pipeline
--------
1. Open the image with Pillow.
2. Pre-process: convert to grayscale → enhance contrast.
   This step significantly improves OCR accuracy on scanned docs.
3. Run pytesseract to extract text.
4. Split the extracted text into FTS5 chunks.

Falls back gracefully when Tesseract is not installed:
logs a warning and yields a placeholder chunk so the file is at least
recorded in file_state (a re-index will pick it up once OCR is available).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from src.engine.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class ImageParser(BaseParser):
    """OCR-based parser for .png, .jpg, .jpeg, .tiff, .bmp, .webp files."""

    file_type = "image"

    # Tesseract config: PSM 3 = fully automatic page segmentation
    _TESSERACT_CONFIG = "--oem 3 --psm 3"

    def extract(self, path: Path) -> Iterator[str]:
        try:
            from PIL import Image, ImageEnhance, ImageFilter
            import pytesseract
        except ImportError:
            logger.warning(
                "ImageParser: pytesseract / Pillow not installed. "
                "Skipping OCR for %s.",
                path,
            )
            yield f"[OCR unavailable] {path.name}"
            return

        try:
            img = Image.open(path)
        except Exception as exc:
            logger.error("ImageParser: cannot open %s — %s", path, exc)
            return

        # ── Pre-processing ────────────────────────────────────────────────────
        img = self._preprocess(img)

        # ── OCR ───────────────────────────────────────────────────────────────
        try:
            raw_text: str = pytesseract.image_to_string(
                img, config=self._TESSERACT_CONFIG
            )
        except pytesseract.TesseractNotFoundError:
            logger.warning(
                "ImageParser: Tesseract binary not found. "
                "Install via `apt install tesseract-ocr` or brew. "
                "Skipping %s.",
                path,
            )
            yield f"[Tesseract not installed] {path.name}"
            return
        except Exception as exc:
            logger.error("ImageParser: OCR failed for %s — %s", path, exc)
            return

        text = self.clean(raw_text)
        if not text:
            logger.debug("ImageParser: no text extracted from %s", path.name)
            return

        logger.debug(
            "ImageParser: extracted %d chars from %s", len(text), path.name
        )

        # Prepend a file-name header so FTS results reference the source image
        header = f"Image: {path.name}\n\n"
        full = header + text

        yield from (
            chunk
            for chunk in self.split_into_chunks(full)
            if chunk.strip()
        )

    # ── Pre-processing helpers ────────────────────────────────────────────────

    @staticmethod
    def _preprocess(img):
        """
        Convert to grayscale and boost contrast.
        These two steps improve Tesseract accuracy on most scanned documents.
        """
        from PIL import ImageEnhance

        # Greyscale
        if img.mode not in ("L", "LA"):
            img = img.convert("L")

        # Contrast enhancement (factor >1.0 sharpens text against background)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        return img
