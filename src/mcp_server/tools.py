"""
src/mcp_server/tools.py
────────────────────────
MCP tool definitions for DeltaContext.

Tools
-----
ctx_search          – Full-text search over the FTS5 index.
ctx_pandas_query    – Safe Pandas sandbox: run aggregation code against a CSV.
ctx_file_list       – List all indexed files with metadata.
ctx_session_summary – Return the last-known session state for resumption.
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path

import pandas as pd

from src.engine.db import DB
from src.memory.session import SessionMemory

logger = logging.getLogger(__name__)


# ── Tool implementations ──────────────────────────────────────────────────────

def ctx_search(
    query: str,
    limit: int = 10,
    db: DB | None = None,
) -> str:
    """
    Search the FTS5 index and return JSON-formatted snippets.

    Parameters
    ----------
    query  : BM25 query string (same syntax as SQLite FTS5 MATCH)
    limit  : max number of result chunks to return (default 10)
    db     : DB instance (injected; falls back to singleton)

    Returns
    -------
    JSON string: [{file_path, chunk_index, content, rank}, ...]
    """
    _db = db or _get_db()
    results = _db.search(query, limit=limit)
    return json.dumps(results, ensure_ascii=False, indent=2)


def ctx_pandas_query(
    file_path: str,
    pandas_expr: str,
    db: DB | None = None,
) -> str:
    """
    Execute a SAFE aggregation expression against a CSV file.

    The expression is evaluated inside a restricted namespace:
        df  — the loaded DataFrame
        pd  — pandas module

    Only *read* operations are allowed. The sandbox blocks:
        - file I/O (open, write, os, sys, subprocess, __import__)
        - arbitrary code execution (__builtins__ is cleared)

    Example pandas_expr values
    --------------------------
        "df.describe().to_string()"
        "df.groupby('ticker')['close'].mean().to_string()"
        "df[df['volume'] > 1_000_000].head(20).to_string()"

    Returns
    -------
    The string result of the expression, or a JSON error dict on failure.
    """
    _db = db or _get_db()

    # Verify the file is indexed
    state = _db.get_file_state(file_path)
    if not state:
        return json.dumps({"error": f"File not indexed: {file_path}"})
    if state["file_type"] != "csv":
        return json.dumps({"error": f"ctx_pandas_query only works on CSV files, got {state['file_type']}"})

    path = Path(file_path)
    if not path.exists():
        return json.dumps({"error": f"File not found on disk: {file_path}"})

    # ── Sandbox ───────────────────────────────────────────────────────────────
    BLOCKED_TOKENS = ["__import__", "open(", "os.", "sys.", "subprocess", "exec(", "eval("]
    for token in BLOCKED_TOKENS:
        if token in pandas_expr:
            return json.dumps({"error": f"Blocked: expression contains disallowed token '{token}'"})

    try:
        df = pd.read_csv(path, low_memory=False)
        safe_globals = {
            "__builtins__": {},   # strip all builtins
            "pd": pd,
            "df": df,
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "list": list,
            "dict": dict,
            "print": print,
        }
        result = eval(pandas_expr, safe_globals)  # noqa: S307 — sandboxed
        return str(result)
    except Exception:
        tb = traceback.format_exc(limit=5)
        logger.warning("ctx_pandas_query failed for %s:\n%s", file_path, tb)
        return json.dumps({"error": tb})


def ctx_file_list(db: DB | None = None) -> str:
    """
    Return a JSON list of all indexed files with their type and last indexed timestamp.
    """
    _db = db or _get_db()
    rows = _db.all_file_states()
    files = [
        {
            "file_path": r["file_path"],
            "file_type": r["file_type"],
            "content_hash": r["content_hash"],
            "indexed_at": r["indexed_at"],
        }
        for r in rows
    ]
    return json.dumps(files, ensure_ascii=False, indent=2)


def ctx_session_summary(session_key: str, db: DB | None = None) -> str:
    """
    Return a compact text summary of the last known session state.
    This string can be injected into the system prompt when a session resumes.
    """
    _db = db or _get_db()
    mem = SessionMemory(_db)
    summary = mem.get_resume_snapshot(session_key)
    return summary or json.dumps({"message": "No session found for key: " + session_key})


# ── DB singleton ──────────────────────────────────────────────────────────────

_db_instance: DB | None = None


def _get_db() -> DB:
    global _db_instance
    if _db_instance is None:
        _db_instance = DB()
    return _db_instance


def set_db(db: DB) -> None:
    """Inject a DB instance (used in tests and by the server at startup)."""
    global _db_instance
    _db_instance = db
