"""tests/test_tools.py — MCP tool function tests."""

import json
from pathlib import Path

import pytest

from src.engine.db import DB
from src.mcp_server import tools as T


@pytest.fixture(autouse=True)
def inject_db(tmp_db: DB) -> None:
    """Point tool module at the test DB for every test in this file."""
    T.set_db(tmp_db)


# ── ctx_search ────────────────────────────────────────────────────────────────

class TestCtxSearch:
    def test_returns_empty_list_when_nothing_indexed(self) -> None:
        result = json.loads(T.ctx_search("anything"))
        assert result == []

    def test_returns_matching_chunk(self, tmp_db: DB) -> None:
        tmp_db.upsert_chunks("/tmp/doc.txt", ["AAPL quarterly earnings report"])
        result = json.loads(T.ctx_search("AAPL"))
        assert len(result) == 1
        assert "AAPL" in result[0]["content"]

    def test_limit_respected(self, tmp_db: DB) -> None:
        for i in range(20):
            tmp_db.upsert_chunks(f"/tmp/doc{i}.txt", [f"token keyword chunk {i}"])
        result = json.loads(T.ctx_search("keyword", limit=5))
        assert len(result) <= 5


# ── ctx_pandas_query ─────────────────────────────────────────────────────────

class TestCtxPandasQuery:
    def test_basic_describe(self, tmp_db: DB, sample_csv: Path) -> None:
        tmp_db.upsert_file_state(str(sample_csv), "h", 0.0, "csv")
        result = T.ctx_pandas_query(str(sample_csv), "df.describe().to_string()")
        assert "count" in result

    def test_filter_returns_rows(self, tmp_db: DB, sample_csv: Path) -> None:
        tmp_db.upsert_file_state(str(sample_csv), "h", 0.0, "csv")
        result = T.ctx_pandas_query(str(sample_csv), "df[df['ticker']=='AAPL'].to_string()")
        assert "AAPL" in result

    def test_blocked_import_returns_error(self, tmp_db: DB, sample_csv: Path) -> None:
        tmp_db.upsert_file_state(str(sample_csv), "h", 0.0, "csv")
        result = json.loads(
            T.ctx_pandas_query(str(sample_csv), "__import__('os').listdir('/')")
        )
        assert "error" in result

    def test_blocked_open_returns_error(self, tmp_db: DB, sample_csv: Path) -> None:
        tmp_db.upsert_file_state(str(sample_csv), "h", 0.0, "csv")
        result = json.loads(
            T.ctx_pandas_query(str(sample_csv), "open('/etc/passwd').read()")
        )
        assert "error" in result

    def test_unindexed_file_returns_error(self, tmp_db: DB, tmp_path: Path) -> None:
        result = json.loads(T.ctx_pandas_query("/not/indexed.csv", "df.head()"))
        assert "error" in result

    def test_non_csv_returns_error(self, tmp_db: DB) -> None:
        tmp_db.upsert_file_state("/tmp/img.png", "h", 0.0, "image")
        result = json.loads(T.ctx_pandas_query("/tmp/img.png", "df.head()"))
        assert "error" in result


# ── ctx_file_list ────────────────────────────────────────────────────────────

class TestCtxFileList:
    def test_empty(self, tmp_db: DB) -> None:
        result = json.loads(T.ctx_file_list())
        assert result == []

    def test_lists_indexed_files(self, tmp_db: DB) -> None:
        tmp_db.upsert_file_state("/a.csv", "h1", 1.0, "csv")
        tmp_db.upsert_file_state("/b.txt", "h2", 2.0, "text")
        result = json.loads(T.ctx_file_list())
        paths = [r["file_path"] for r in result]
        assert "/a.csv" in paths
        assert "/b.txt" in paths
