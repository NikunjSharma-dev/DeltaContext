"""
src/engine/parsers/csv.py
─────────────────────────
CSV / TSV parser.

Two indexing modes are supported (selected at construction time):

MODE: "summary"  (default)
    Converts each row into a human-readable sentence:
        "Row 3 | ticker: AAPL | close: 189.25 | volume: 54321200"
    Best for: equity statements, financial CSVs, small lookup tables.

MODE: "schema"
    Only indexes the column names + basic stats (min, max, mean, count)
    produced by `df.describe()`.
    Best for: very large CSVs where row-by-row text would flood the DB.

The indexer transparently chooses "schema" mode when a CSV has more than
MAX_ROWS_FOR_SUMMARY rows so the pipeline never OOMs on a 500 MB export.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import pandas as pd

from src.engine.parsers.base import BaseParser

logger = logging.getLogger(__name__)

MAX_ROWS_FOR_SUMMARY = 5_000  # rows; above this threshold → schema mode


class CSVParser(BaseParser):
    """Parse CSV / TSV files into searchable text chunks."""

    file_type = "csv"

    def __init__(self, mode: str = "auto") -> None:
        """
        Parameters
        ----------
        mode : "summary" | "schema" | "auto"
            "auto" picks "summary" for small files and "schema" for large ones.
        """
        assert mode in ("summary", "schema", "auto")
        self.mode = mode

    # ── Public interface ──────────────────────────────────────────────────────

    def extract(self, path: Path) -> Iterator[str]:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        try:
            df = pd.read_csv(path, sep=sep, low_memory=False)
        except Exception as exc:
            logger.error("CSVParser: cannot read %s — %s", path, exc)
            return

        if df.empty:
            return

        mode = self._resolve_mode(df)
        logger.debug("CSVParser: %s rows, mode=%s, file=%s", len(df), mode, path.name)

        if mode == "summary":
            yield from self._summary_chunks(df, path)
        else:
            yield from self._schema_chunks(df, path)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _resolve_mode(self, df: pd.DataFrame) -> str:
        if self.mode != "auto":
            return self.mode
        return "summary" if len(df) <= MAX_ROWS_FOR_SUMMARY else "schema"

    def _summary_chunks(self, df: pd.DataFrame, path: Path) -> Iterator[str]:
        """
        Convert rows to text sentences and yield them as chunks.
        Groups BATCH_SIZE rows per chunk so the FTS5 table doesn't have
        millions of tiny entries.
        """
        BATCH_SIZE = 50
        lines: list[str] = [f"File: {path.name} | Columns: {', '.join(df.columns)}"]

        for i, (_, row) in enumerate(df.iterrows()):
            parts = " | ".join(f"{col}: {val}" for col, val in row.items())
            lines.append(f"Row {i + 1} | {parts}")

            if len(lines) >= BATCH_SIZE:
                yield self.clean("\n".join(lines))
                lines = []

        if lines:
            yield self.clean("\n".join(lines))

    def _schema_chunks(self, df: pd.DataFrame, path: Path) -> Iterator[str]:
        """
        Yield a stats summary via df.describe() — compact but informative.
        """
        header = (
            f"File: {path.name}\n"
            f"Rows: {len(df)} | Columns: {', '.join(df.columns)}\n\n"
        )
        try:
            stats = df.describe(include="all").to_string()
        except Exception:
            stats = "(statistics unavailable)"

        yield self.clean(header + "Statistics:\n" + stats)

        # Also index the first 10 rows as a sample
        sample = df.head(10).to_string(index=False)
        yield self.clean(f"Sample rows (first 10) from {path.name}:\n{sample}")
