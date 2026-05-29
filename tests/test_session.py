"""tests/test_session.py — Session memory CRUD and snapshot tests."""

from src.engine.db import DB
from src.memory.session import SessionMemory


class TestSessionMemory:
    def test_ensure_session_creates_record(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.ensure_session("sess-001")
        row = tmp_db.conn.execute(
            "SELECT * FROM sessions WHERE session_key = 'sess-001'"
        ).fetchone()
        assert row is not None

    def test_ensure_session_is_idempotent(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.ensure_session("sess-002")
        mem.ensure_session("sess-002")  # no error
        count = tmp_db.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_key='sess-002'"
        ).fetchone()[0]
        assert count == 1

    def test_log_event_stores_tool_call(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.log_event("sess-003", "ctx_search", {"query": "AAPL"}, duration_ms=12)
        row = tmp_db.conn.execute(
            "SELECT * FROM tool_calls WHERE session_key='sess-003'"
        ).fetchone()
        assert row is not None
        assert row["tool_name"] == "ctx_search"
        assert row["duration_ms"] == 12

    def test_log_file_edit(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.log_file_edit("sess-004", "/data/equities.csv", "added", new_hash="abc")
        row = tmp_db.conn.execute(
            "SELECT * FROM file_edits WHERE session_key='sess-004'"
        ).fetchone()
        assert row["action"] == "added"
        assert row["new_hash"] == "abc"

    def test_store_summary(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.store_summary("sess-005", "Analysed Q1 equity data for AAPL.")
        row = tmp_db.conn.execute(
            "SELECT summary FROM sessions WHERE session_key='sess-005'"
        ).fetchone()
        assert row["summary"] == "Analysed Q1 equity data for AAPL."

    def test_get_resume_snapshot_returns_empty_for_unknown_key(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        snap = mem.get_resume_snapshot("unknown-key")
        assert snap == ""

    def test_get_resume_snapshot_contains_session_key(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.ensure_session("snap-test")
        snap = mem.get_resume_snapshot("snap-test")
        assert "snap-test" in snap
        assert "DeltaContext Resume Snapshot" in snap

    def test_resume_snapshot_includes_tool_calls(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.log_event("snap-full", "ctx_search", {"query": "GOOG"}, duration_ms=8)
        snap = mem.get_resume_snapshot("snap-full")
        assert "ctx_search" in snap

    def test_resume_snapshot_includes_file_edits(self, tmp_db: DB) -> None:
        mem = SessionMemory(tmp_db)
        mem.log_file_edit("snap-edits", "/data/f.csv", "updated", new_hash="xx")
        snap = mem.get_resume_snapshot("snap-edits")
        assert "UPDATED" in snap
        assert "/data/f.csv" in snap
