"""
src/engine/parsers/pdf.py
─────────────────────────
PDF parser using pypdf.

Each PDF page becomes its own chunk (after cleaning).
If pypdf cannot extract text from a page (scanned PDF without an embedded
text layer), the parser logs a warning. For fully scanned PDFs, pipe them
through the image parser instead (render each page to PNG first).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from src.engine.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class PDFParser(BaseParser):
    """Parse PDF files page-by-page."""

    file_type = "pdf"

    def extract(self, path: Path) -> Iterator[str]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("PDFParser: pypdf not installed. Skipping %s.", path)
            yield f"[PDF parser unavailable] {path.name}"
            return

        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            logger.error("PDFParser: cannot open %s — %s", path, exc)
            return

        total = len(reader.pages)
        logger.debug("PDFParser: %d pages in %s", total, path.name)

        for page_num, page in enumerate(reader.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception as exc:
                logger.warning(
                    "PDFParser: page %d extraction failed in %s — %s",
                    page_num, path.name, exc,
                )
                continue

            text = self.clean(raw)
            if not text:
                logger.debug(
                    "PDFParser: page %d of %s yielded no text (possibly scanned)",
                    page_num, path.name,
                )
                continue

            header = f"File: {path.name} | Page {page_num}/{total}\n\n"
            full = header + text

            yield from (
                chunk
                for chunk in self.split_into_chunks(full)
                if chunk.strip()
            )
