"""
src/engine/parsers/base.py
──────────────────────────
Abstract base class that every file-type parser must implement.

Strategy Pattern — the Indexer receives a file_type string and calls
get_parser(file_type) which returns the correct concrete parser.
Each parser is responsible for:

1. Reading a file from disk.
2. Splitting the content into text *chunks* (a list of strings).
   Chunks should be ~500-1500 characters so FTS5 snippets stay readable
   and LLM context windows aren't blown out.

Extending
---------
To add a new format (e.g. DOCX), create a new module under parsers/,
subclass BaseParser, implement `extract()`, and register the class in
`parsers/__init__.py`.
"""

from __future__ import annotations

import textwrap
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

# Default target chunk size (characters)
DEFAULT_CHUNK_SIZE = 1_000
DEFAULT_CHUNK_OVERLAP = 100


class BaseParser(ABC):
    """
    All parsers must implement `extract(path)` which yields text chunks.
    """

    # Override in subclass for logging / error messages
    file_type: str = "unknown"

    @abstractmethod
    def extract(self, path: Path) -> Iterator[str]:
        """
        Parse *path* and yield non-empty text chunks.

        Parameters
        ----------
        path : Path to the file to parse (guaranteed to exist).

        Yields
        ------
        str — text chunk, stripped of leading/trailing whitespace.
        """
        ...

    # ── Shared utility helpers ────────────────────────────────────────────────

    @staticmethod
    def split_into_chunks(
        text: str,
        size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> list[str]:
        """
        Split *text* into overlapping chunks of approximately *size* chars.
        Overlap avoids cutting a sentence in half at a chunk boundary so the
        LLM retains context across adjacent FTS5 snippets.
        """
        text = text.strip()
        if not text:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + size
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start += size - overlap

        return chunks

    @staticmethod
    def clean(text: str) -> str:
        """Collapse whitespace and strip control characters."""
        import re
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
