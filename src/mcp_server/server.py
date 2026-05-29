"""
src/mcp_server/server.py
─────────────────────────
Anthropic MCP server entry-point for DeltaContext.

Registers four tools:
  ctx_search          – FTS5 full-text search
  ctx_pandas_query    – sandboxed Pandas aggregation
  ctx_file_list       – list indexed files
  ctx_session_summary – session resume helper

Run locally
-----------
    python -m src.mcp_server.server

Or via Docker:
    docker run -e DELTA_CONTEXT_DB=/data/dc.sqlite -v $(pwd)/data:/data delta_context
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.engine.db import DB
from src.engine.indexer import Indexer
from src.mcp_server import tools as T

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Bootstrap ─────────────────────────────────────────────────────────────────

db = DB()
T.set_db(db)

watch_dirs_raw = os.getenv("WATCH_DIRS", "./data/inbox")
watch_dirs = [d.strip() for d in watch_dirs_raw.split(",") if d.strip()]
indexer = Indexer(db=db, watch_dirs=watch_dirs)

# Run a full scan at startup to catch any files added while the server was down
logger.info("Running startup scan on: %s", watch_dirs)
try:
    indexer.run_full_scan()
except Exception as exc:
    logger.warning("Startup scan failed (non-fatal): %s", exc)

# Start real-time watcher
indexer.start_watcher()
logger.info("File watcher active.")

# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP("DeltaContext")


@mcp.tool()
def ctx_search(query: str, limit: int = 10) -> str:
    """
    Search the full-text index for content matching *query*.

    Returns JSON array of matching chunks: [{file_path, chunk_index, content, rank}].
    BM25-ranked — lower rank = better match.

    Parameters
    ----------
    query  : FTS5 MATCH query. Supports AND, OR, NOT, phrase search with "quotes".
    limit  : Maximum number of chunks to return (1-50).
    """
    limit = max(1, min(limit, 50))
    return T.ctx_search(query, limit=limit)


@mcp.tool()
def ctx_pandas_query(file_path: str, pandas_expr: str) -> str:
    """
    Run a read-only Pandas expression against an indexed CSV file.

    The expression is evaluated in a sandboxed namespace with `df` (the loaded
    DataFrame) and `pd` (pandas) available.

    Returns the string result of the expression.

    Examples
    --------
    pandas_expr = "df.describe().to_string()"
    pandas_expr = "df.groupby('ticker')['close'].mean().sort_values(ascending=False).head(10).to_string()"
    pandas_expr = "df[df['volume'] > 1_000_000].shape"

    Parameters
    ----------
    file_path   : Absolute path to the CSV file (must be indexed).
    pandas_expr : A single Python expression (no statements, no imports).
    """
    return T.ctx_pandas_query(file_path, pandas_expr)


@mcp.tool()
def ctx_file_list() -> str:
    """
    List all files currently indexed in DeltaContext.

    Returns JSON array of {file_path, file_type, content_hash, indexed_at}.
    """
    return T.ctx_file_list()


@mcp.tool()
def ctx_session_summary(session_key: str) -> str:
    """
    Retrieve the resume snapshot for *session_key*.

    Returns a compact plain-text summary of the last session's activity:
    files indexed, tools called, and any stored summary. Inject this into
    your system prompt to restore context after truncation.

    Parameters
    ----------
    session_key : Unique identifier for the session (e.g. a UUID or user ID).
    """
    return T.ctx_session_summary(session_key)


if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_SERVER_PORT", "8765"))
    logger.info("Starting DeltaContext MCP server on %s:%s", host, port)
    mcp.run()
