"""tests/test_db.py — SQLite FTS5 schema and CRUD tests."""

import pytest
from src.engine.db import DB


def test_db_initialises(tmp_db: DB) -> None:
    """Schema creation must be idempotent — running it twice raises no error."""
    tmp_db._init_schema()  # second call
    assert tmp_db.path.exists()


def test_upsert_and_get_file_state(tmp_db: DB) -> None:
    tmp_db.upsert_file_state("/tmp/a.csv", "abc123", 1000.0, "csv")
    row = tmp_db.get_file_state("/tmp/a.csv")
    assert row is not None
    assert row["content_hash"] == "abc123"
    assert row["file_type"] == "csv"


def test_upsert_is_idempotent(tmp_db: DB) -> None:
    tmp_db.upsert_file_state("/tmp/a.csv", "hash1", 1000.0, "csv")
    tmp_db.upsert_file_state("/tmp/a.csv", "hash2", 2000.0, "csv")  # update
    row = tmp_db.get_file_state("/tmp/a.csv")
    assert row["content_hash"] == "hash2"


def test_delete_file_state(tmp_db: DB) -> None:
    tmp_db.upsert_file_state("/tmp/b.csv", "xyz", 1000.0, "csv")
    tmp_db.delete_file_state("/tmp/b.csv")
    assert tmp_db.get_file_state("/tmp/b.csv") is None


def test_fts5_upsert_and_search(tmp_db: DB) -> None:
    tmp_db.upsert_chunks("/tmp/doc.txt", ["The quick brown fox", "jumped over the lazy dog"])
    results = tmp_db.search("fox")
    assert len(results) == 1
    assert "fox" in results[0]["content"]


def test_fts5_delete_chunks(tmp_db: DB) -> None:
    tmp_db.upsert_chunks("/tmp/doc.txt", ["AAPL earnings report", "Revenue grew 12%"])
    tmp_db.delete_chunks("/tmp/doc.txt")
    results = tmp_db.search("AAPL")
    assert results == []


def test_fts5_search_returns_empty_on_no_match(tmp_db: DB) -> None:
    results = tmp_db.search("xyzzy_no_match")
    assert results == []


def test_all_file_states_empty(tmp_db: DB) -> None:
    assert tmp_db.all_file_states() == []


def test_all_file_states_populated(tmp_db: DB) -> None:
    tmp_db.upsert_file_state("/a.csv", "h1", 1.0, "csv")
    tmp_db.upsert_file_state("/b.txt", "h2", 2.0, "text")
    rows = tmp_db.all_file_states()
    assert len(rows) == 2
