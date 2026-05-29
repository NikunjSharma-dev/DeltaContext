"""
src/engine/parsers/text.py
──────────────────────────
Plain text / Markdown / RST parser.

Strategy: split on double-newlines (paragraph boundaries) first,
then fall back to fixed-size chunking for paragraphs that are still
longer than DEFAULT_CHUNK_SIZE.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator

from src.engine.parsers.base import BaseParser, DEFAULT_CHUNK_SIZE

logger = logging.getLogger(__name__)


class TextParser(BaseParser):
    """Parse .txt, .md, and .rst files."""

    file_type = "text"

    def extract(self, path: Path) -> Iterator[str]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("TextParser: cannot read %s — %s", path, exc)
            return

        text = self.clean(text)
        if not text:
            return

        header = f"File: {path.name}\n\n"
        full = header + text

        # Split on paragraph boundaries first
        paragraphs = re.split(r"\n\s*\n", full)
        buffer = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # If this paragraph alone exceeds chunk size, split it further
            if len(para) > DEFAULT_CHUNK_SIZE:
                if buffer:
                    yield from self.split_into_chunks(buffer)
                    buffer = ""
                yield from self.split_into_chunks(para)
            else:
                # Accumulate paragraphs until we hit the target chunk size
                if len(buffer) + len(para) + 2 > DEFAULT_CHUNK_SIZE:
                    if buffer:
                        yield buffer.strip()
                    buffer = para
                else:
                    buffer = (buffer + "\n\n" + para).strip()

        if buffer:
            yield buffer.strip()
