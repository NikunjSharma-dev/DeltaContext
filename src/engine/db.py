"""
src/engine/db.py
────────────────
SQLite interface for DeltaContext.

Tables
------
file_state      – canonical record of every indexed file (path, hash, mtime)
fts_chunks      – FTS5 virtual table for full-text search over parsed content
sessions        – agent session metadata           (Phase 5)
tool_calls      – log of every MCP tool invocation (Phase 5)
file_edits      – granular per-file mutation log   (Phase 5)
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable

logger = logging.getLogger(__name__)

# ── Default DB path (overridden by env var or constructor arg) ────────────────
_DEFAULT_DB = os.getenv("DELTA_CONTEXT_DB", "./data/delta_context.sqlite")


class DB:
    """
    Thin wrapper around sqlite3 that owns schema creation and FTS5 operations.

    Usage
    -----
    db = DB()               # uses DELTA_CONTEXT_DB env var or default path
    db = DB("/tmp/test.db") # explicit path (useful in tests)
    """

    def __init__(self, path: str | Path = _DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_schema()

    # ── Connection management ─────────────────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # Performance pragmas
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for explicit transactions with auto-rollback on error."""
        conn = self.conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Schema bootstrap ──────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create all tables if they don't exist. Idempotent."""
        with self.transaction() as c:
            # ── Phase 2: Delta Engine tables ─────────────────────────────────
            c.execute("""
                CREATE TABLE IF NOT EXISTS file_state (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path   TEXT    NOT NULL UNIQUE,
                    content_hash TEXT   NOT NULL,
                    mtime       REAL    NOT NULL,
                    file_type   TEXT    NOT NULL,
                    indexed_at  REAL    NOT NULL DEFAULT (unixepoch('now'))
                )
            """)

            # FTS5 virtual table — content= points at file_state for row ownership
            c.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
                    file_path   UNINDEXED,
                    chunk_index UNINDEXED,
                    content,
                    tokenize = "porter ascii"
                )
            """)

            # ── Phase 5: Session memory tables ───────────────────────────────
            c.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT    NOT NULL UNIQUE,
                    started_at  REAL    NOT NULL DEFAULT (unixepoch('now')),
                    last_active REAL    NOT NULL DEFAULT (unixepoch('now')),
                    summary     TEXT
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT    NOT NULL,
                    tool_name   TEXT    NOT NULL,
                    arguments   TEXT,           -- JSON blob
                    result      TEXT,           -- JSON blob
                    called_at   REAL    NOT NULL DEFAULT (unixepoch('now')),
                    duration_ms INTEGER,
                    FOREIGN KEY (session_key) REFERENCES sessions(session_key)
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS file_edits (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT    NOT NULL,
                    file_path   TEXT    NOT NULL,
                    action      TEXT    NOT NULL CHECK(action IN ('added','updated','deleted')),
                    old_hash    TEXT,
                    new_hash    TEXT,
                    edited_at   REAL    NOT NULL DEFAULT (unixepoch('now')),
                    FOREIGN KEY (session_key) REFERENCES sessions(session_key)
                )
            """)

        logger.info("Schema initialised at %s", self.path)

    # ── file_state helpers ────────────────────────────────────────────────────

    def get_file_state(self, file_path: str) -> sqlite3.Row | None:
        row = self.conn.execute(
            "SELECT * FROM file_state WHERE file_path = ?", (file_path,)
        ).fetchone()
        return row

    def upsert_file_state(
        self,
        file_path: str,
        content_hash: str,
        mtime: float,
        file_type: str,
    ) -> None:
        with self.transaction() as c:
            c.execute(
                """
                INSERT INTO file_state (file_path, content_hash, mtime, file_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    mtime        = excluded.mtime,
                    file_type    = excluded.file_type,
                    indexed_at   = unixepoch('now')
                """,
                (file_path, content_hash, mtime, file_type),
            )

    def delete_file_state(self, file_path: str) -> None:
        with self.transaction() as c:
            c.execute("DELETE FROM file_state WHERE file_path = ?", (file_path,))

    def all_file_states(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM file_state").fetchall()

    # ── FTS5 helpers ──────────────────────────────────────────────────────────

    def upsert_chunks(self, file_path: str, chunks: Iterable[str]) -> None:
        """
        Replace all FTS5 chunks for a file with freshly parsed content.
        Uses a delete-then-insert strategy (safe for FTS5).
        """
        with self.transaction() as c:
            c.execute("DELETE FROM fts_chunks WHERE file_path = ?", (file_path,))
            c.executemany(
                "INSERT INTO fts_chunks (file_path, chunk_index, content) VALUES (?,?,?)",
                [(file_path, i, chunk) for i, chunk in enumerate(chunks)],
            )

    def delete_chunks(self, file_path: str) -> None:
        with self.transaction() as c:
            c.execute("DELETE FROM fts_chunks WHERE file_path = ?", (file_path,))

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """
        Full-text search using FTS5 BM25 ranking.
        Returns a list of dicts: {file_path, chunk_index, content, rank}.
        """
        rows = self.conn.execute(
            """
            SELECT file_path, chunk_index, content, rank
            FROM   fts_chunks
            WHERE  fts_chunks MATCH ?
            ORDER  BY rank
            LIMIT  ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
