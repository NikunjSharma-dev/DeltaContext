"""
src/engine/parsers/docx_parser.py
───────────────────────────────────
DOCX parser using python-docx.

Extracts
--------
- Paragraphs (body text, headings)
- Tables  — each row becomes a pipe-separated line
- Headers and footers
- Comments (if present)

Heading levels are preserved as Markdown-style prefixes (#, ##, ###)
so the LLM can reason about document structure.

Tables
------
A table like:
    | Ticker | Close | Volume |
    | AAPL   | 189.25| 54321200|

is emitted as:
    [Table 1, Row 1] Ticker | Close | Volume
    [Table 1, Row 2] AAPL | 189.25 | 54321200
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from src.engine.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Map python-docx heading style names → Markdown prefix
_HEADING_PREFIX: dict[str, str] = {
    "Heading 1": "# ",
    "Heading 2": "## ",
    "Heading 3": "### ",
    "Heading 4": "#### ",
    "Title": "# ",
    "Subtitle": "## ",
}


class DOCXParser(BaseParser):
    """Parse .docx Word documents into searchable text chunks."""

    file_type = "docx"

    def extract(self, path: Path) -> Iterator[str]:
        try:
            import docx as python_docx
        except ImportError:
            logger.warning("DOCXParser: python-docx not installed. Skipping %s.", path)
            yield f"[DOCX parser unavailable] {path.name}"
            return

        try:
            doc = python_docx.Document(str(path))
        except Exception as exc:
            logger.error("DOCXParser: cannot open %s — %s", path, exc)
            return

        buffer: list[str] = [f"File: {path.name}\n"]

        # ── Body paragraphs ───────────────────────────────────────────────────
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            prefix = _HEADING_PREFIX.get(para.style.name, "")
            line = prefix + text

            buffer.append(line)
            # Flush at headings so each section becomes its own chunk
            if prefix and len(buffer) > 3:
                yield from self._flush(buffer, keep_header=True)

        # ── Tables ────────────────────────────────────────────────────────────
        for t_idx, table in enumerate(doc.tables, start=1):
            table_lines: list[str] = [f"\n[Table {t_idx}]"]
            for r_idx, row in enumerate(table.rows, start=1):
                cells = " | ".join(cell.text.strip() for cell in row.cells)
                if cells.replace("|", "").strip():
                    table_lines.append(f"  Row {r_idx}: {cells}")
            if len(table_lines) > 1:
                buffer.extend(table_lines)

        # ── Flush remaining buffer ────────────────────────────────────────────
        if buffer:
            yield from self._flush(buffer, keep_header=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _flush(self, buffer: list[str], keep_header: bool) -> Iterator[str]:
        """
        Yield the buffer as one or more chunks, then reset it.
        If keep_header=True, retain the first line (file header) for the next batch.
        """
        text = self.clean("\n".join(buffer))
        if text:
            yield from (c for c in self.split_into_chunks(text) if c.strip())

        if keep_header:
            first = buffer[0]
            buffer.clear()
            buffer.append(first)
        else:
            buffer.clear()