"""
tests/conftest.py
─────────────────
Shared pytest fixtures for DeltaContext.

All DB fixtures use a temporary file (not :memory:) because FTS5 requires
WAL mode which isn't fully supported in in-memory SQLite.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.engine.db import DB


@pytest.fixture
def tmp_db(tmp_path: Path) -> DB:
    """An empty, initialised DB in a temp directory."""
    db_path = tmp_path / "test.sqlite"
    db = DB(str(db_path))
    yield db
    db.close()


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Write a small equity CSV and return its path."""
    p = tmp_path / "equities.csv"
    p.write_text(
        "ticker,date,close,volume\n"
        "AAPL,2025-01-01,189.25,54321200\n"
        "GOOG,2025-01-01,142.10,12000000\n"
        "MSFT,2025-01-01,415.75,8900000\n"
    )
    return p


@pytest.fixture
def sample_txt(tmp_path: Path) -> Path:
    """Write a short Markdown file and return its path."""
    p = tmp_path / "notes.md"
    p.write_text(
        "# DeltaContext Notes\n\n"
        "This is a test document about the DeltaContext project.\n\n"
        "It includes multiple paragraphs so we can test chunking.\n\n"
        "Equity data includes AAPL, GOOG, and MSFT tickers.\n"
    )
    return p
