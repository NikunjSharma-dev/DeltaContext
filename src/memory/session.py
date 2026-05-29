"""
src/memory/session.py
──────────────────────
Session memory for DeltaContext.

Provides
--------
SessionMemory       – High-level interface for reading / writing session state.
log_tool_call()     – Decorator that auto-logs every tool invocation to SQLite.
get_resume_snapshot() – Compiles a short text summary for LLM context injection.

Design
------
All state is stored in SQLite (sessions, tool_calls, file_edits tables created
in db.py). This means session memory survives process restarts and Docker
container replacements without any external state store.

Usage in the MCP server
-----------------------
from src.memory.session import SessionMemory, log_tool_call

mem = SessionMemory(db)

# Ensure a session exists (idempotent)
mem.ensure_session("session-abc123")

# Log a manual event
mem.log_event("session-abc123", tool_name="ctx_search", arguments={"query": "AAPL"}, result=..., duration_ms=12)

# Retrieve the resume snapshot
print(mem.get_resume_snapshot("session-abc123"))
"""

from __future__ import annotations

import functools
import json
import logging
import time
from typing import Any, Callable

from src.engine.db import DB

logger = logging.getLogger(__name__)


class SessionMemory:
    """CRUD interface for the sessions / tool_calls / file_edits tables."""

    def __init__(self, db: DB) -> None:
        self.db = db

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def ensure_session(self, session_key: str) -> None:
        """Create a session record if one doesn't already exist."""
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO sessions (session_key)
                VALUES (?)
                ON CONFLICT(session_key) DO UPDATE SET
                    last_active = unixepoch('now')
                """,
                (session_key,),
            )

    def store_summary(self, session_key: str, summary: str) -> None:
        """Persist a natural-language summary of this session for future resumption."""
        self.ensure_session(session_key)
        with self.db.transaction() as c:
            c.execute(
                "UPDATE sessions SET summary = ? WHERE session_key = ?",
                (summary, session_key),
            )

    # ── Event logging ─────────────────────────────────────────────────────────

    def log_event(
        self,
        session_key: str,
        tool_name: str,
        arguments: dict | None = None,
        result: Any = None,
        duration_ms: int | None = None,
    ) -> None:
        self.ensure_session(session_key)
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO tool_calls
                    (session_key, tool_name, arguments, result, duration_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_key,
                    tool_name,
                    json.dumps(arguments) if arguments else None,
                    json.dumps(result) if result is not None else None,
                    duration_ms,
                ),
            )

    def log_file_edit(
        self,
        session_key: str,
        file_path: str,
        action: str,
        old_hash: str | None = None,
        new_hash: str | None = None,
    ) -> None:
        """
        Record a file mutation (added / updated / deleted).

        Parameters
        ----------
        action : one of 'added', 'updated', 'deleted'
        """
        self.ensure_session(session_key)
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO file_edits
                    (session_key, file_path, action, old_hash, new_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_key, file_path, action, old_hash, new_hash),
            )

    # ── Resume snapshot ───────────────────────────────────────────────────────

    def get_resume_snapshot(self, session_key: str, max_events: int = 20) -> str:
        """
        Compile a compact plain-text summary of the last known session state.

        This string is designed to be injected at the TOP of the system prompt
        when a session resumes after context truncation or a process restart.

        Format
        ------
        ## DeltaContext Resume Snapshot
        Session: <key>
        Last active: <timestamp>
        Stored summary: <summary or "(none)">

        ### Recent tool calls (last N)
        1. ctx_search({"query": "AAPL"}) → 200ms
        ...

        ### File activity
        - ADDED   /data/inbox/equities_2025-06-01.csv
        ...
        """
        conn = self.db.conn

        session = conn.execute(
            "SELECT * FROM sessions WHERE session_key = ?", (session_key,)
        ).fetchone()

        if not session:
            return ""

        lines: list[str] = [
            "## DeltaContext Resume Snapshot",
            f"Session     : {session_key}",
            f"Last active : {_fmt_ts(session['last_active'])}",
            f"Summary     : {session['summary'] or '(none)'}",
            "",
        ]

        # ── Tool calls ────────────────────────────────────────────────────────
        calls = conn.execute(
            """
            SELECT tool_name, arguments, duration_ms, called_at
            FROM   tool_calls
            WHERE  session_key = ?
            ORDER  BY called_at DESC
            LIMIT  ?
            """,
            (session_key, max_events),
        ).fetchall()

        if calls:
            lines.append(f"### Recent tool calls (last {len(calls)})")
            for i, c in enumerate(reversed(calls), start=1):
                args = c["arguments"] or "{}"
                ms = f"{c['duration_ms']}ms" if c["duration_ms"] else "?"
                lines.append(f"  {i}. {c['tool_name']}({args}) → {ms}")
            lines.append("")

        # ── File edits ────────────────────────────────────────────────────────
        edits = conn.execute(
            """
            SELECT action, file_path, edited_at
            FROM   file_edits
            WHERE  session_key = ?
            ORDER  BY edited_at DESC
            LIMIT  20
            """,
            (session_key,),
        ).fetchall()

        if edits:
            lines.append("### File activity")
            for e in reversed(edits):
                lines.append(f"  - {e['action'].upper():<8} {e['file_path']}")
            lines.append("")

        return "\n".join(lines)


# ── Decorator ────────────────────────────────────────────────────────────────

def log_tool_call(session_key: str, db: DB) -> Callable:
    """
    Decorator factory. Wraps a tool function to log its call + result + timing
    into the session_memory database.

    Usage
    -----
    mem = SessionMemory(db)

    @log_tool_call("my-session", db)
    def ctx_search(query: str, limit: int = 10) -> str:
        ...
    """
    def decorator(fn: Callable) -> Callable:
        mem = SessionMemory(db)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                duration = int((time.monotonic() - start) * 1000)
                mem.log_event(
                    session_key,
                    tool_name=fn.__name__,
                    arguments={"args": str(args), "kwargs": str(kwargs)},
                    result={"error": str(exc)},
                    duration_ms=duration,
                )
                raise
            duration = int((time.monotonic() - start) * 1000)
            mem.log_event(
                session_key,
                tool_name=fn.__name__,
                arguments={"args": str(args), "kwargs": str(kwargs)},
                result=None,  # don't log full results (can be large)
                duration_ms=duration,
            )
            return result

        return wrapper
    return decorator


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_ts(unix_ts: float | None) -> str:
    if unix_ts is None:
        return "(unknown)"
    import datetime
    return datetime.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S")
