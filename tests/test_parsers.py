"""tests/test_parsers.py — Parser output tests."""

from pathlib import Path

import pytest

from src.engine.parsers.csv import CSVParser
from src.engine.parsers.text import TextParser
from src.engine.parsers.base import BaseParser


# ── CSV Parser ────────────────────────────────────────────────────────────────

class TestCSVParser:
    def test_summary_mode_yields_chunks(self, sample_csv: Path) -> None:
        parser = CSVParser(mode="summary")
        chunks = list(parser.extract(sample_csv))
        assert len(chunks) >= 1
        combined = " ".join(chunks)
        assert "AAPL" in combined

    def test_schema_mode_yields_describe(self, sample_csv: Path) -> None:
        parser = CSVParser(mode="schema")
        chunks = list(parser.extract(sample_csv))
        assert any("Statistics" in c or "count" in c for c in chunks)

    def test_auto_mode_uses_summary_for_small_csv(self, sample_csv: Path) -> None:
        parser = CSVParser(mode="auto")
        chunks = list(parser.extract(sample_csv))
        assert len(chunks) >= 1
        assert any("AAPL" in c for c in chunks)

    def test_empty_csv_yields_nothing(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.csv"
        p.write_text("ticker,close\n")
        chunks = list(CSVParser().extract(p))
        assert chunks == []

    def test_missing_file_yields_nothing(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.csv"
        chunks = list(CSVParser().extract(p))
        assert chunks == []


# ── Text Parser ───────────────────────────────────────────────────────────────

class TestTextParser:
    def test_extracts_text_from_md(self, sample_txt: Path) -> None:
        parser = TextParser()
        chunks = list(parser.extract(sample_txt))
        assert len(chunks) >= 1
        combined = " ".join(chunks)
        assert "DeltaContext" in combined

    def test_file_name_appears_in_first_chunk(self, sample_txt: Path) -> None:
        chunks = list(TextParser().extract(sample_txt))
        assert sample_txt.name in chunks[0]

    def test_empty_txt_yields_nothing(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.txt"
        p.write_text("   \n\n\n   ")
        assert list(TextParser().extract(p)) == []

    def test_large_paragraph_is_split(self, tmp_path: Path) -> None:
        p = tmp_path / "big.txt"
        # Single paragraph > DEFAULT_CHUNK_SIZE
        p.write_text("word " * 500)
        chunks = list(TextParser().extract(p))
        assert len(chunks) > 1


# ── Base utility methods ──────────────────────────────────────────────────────

class TestBaseParser:
    def test_split_into_chunks_basic(self) -> None:
        text = "a" * 3000
        chunks = BaseParser.split_into_chunks(text, size=1000, overlap=100)
        assert len(chunks) > 1
        # Each chunk should be <= size (approximately)
        for c in chunks:
            assert len(c) <= 1010  # allow small overage

    def test_split_into_chunks_empty(self) -> None:
        assert BaseParser.split_into_chunks("") == []

    def test_clean_removes_control_chars(self) -> None:
        dirty = "hello\x00world\x01test"
        cleaned = BaseParser.clean(dirty)
        assert "\x00" not in cleaned
        assert "\x01" not in cleaned
        assert "hello" in cleaned
