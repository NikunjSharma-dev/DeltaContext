# DeltaContext

**A Multimodal ETL Pipeline + MCP Server that gives LLM agents persistent, searchable memory over files.**

---

## What Is This?

DeltaContext watches a directory of files — CSVs, images, PDFs, Markdown — and maintains a SQLite FTS5 (Full-Text Search) index of their content. A Model Context Protocol (MCP) server exposes that index to any LLM agent as three clean tools, so the agent can search only the relevant snippets instead of loading entire files into the context window.

```
[ Local Files ] ───→ [ Delta Engine ] ───→ [ SQLite FTS5 DB ] ───→ [ MCP Server ] ───→ [ LLM Agent ]
 CSV, PDF, HTML        Watches for edits                              ctx_search
 DOCX, Python          Hashes content (xxHash)                        ctx_pandas_query
 JPG, PNG              Parses & extracts text                         ctx_file_list
```

## Features

| Feature | Detail |
|---------|--------|
| **Delta detection** | xxHash content fingerprinting — only re-indexes changed files |
| **Real-time watching** | watchdog background thread; new files indexed within seconds |
| **Multimodal parsing** | CSV rows → text, Tesseract OCR for images, pypdf for PDFs, python-docx for Word documents, bs4 for HTML, libcst for Python AST, and Markdown. |
| **FTS5 search** | BM25-ranked full-text search with Porter stemming |
| **Sandboxed Pandas** | LLM can run `df.describe()` / groupby without file-system access |
| **Session memory** | Every tool call + file mutation is logged; survives context truncation |
| **Docker-ready** | Two-stage build; Tesseract C-libs pre-installed |
| **GitHub Actions CI** | Lint + test (3.11 / 3.12) + Docker build on every push |

---

## Repository Structure

```
delta_context/
├── .github/workflows/ci.yml   # GitHub Actions — lint, test, Docker build
├── src/
│   ├── engine/
│   │   ├── db.py              # SQLite FTS5 interface + schema
│   │   ├── delta.py           # xxHash + Pandas diff logic
│   │   ├── indexer.py         # Orchestrator + watchdog watcher
│   │   └── parsers/
│   │       ├── base.py        # Abstract BaseParser & chunking utilities
│   │       ├── csv.py         # Pandas dataframe parser
│   │       ├── docx_parser.py # Microsoft Word text extraction
│   │       ├── html_parser.py # bs4 DOM parsing (strips scripts/styles)
│   │       ├── image.py       # Tesseract OCR engine
│   │       ├── json_parser.py # JSON flattener
│   │       ├── pdf.py         # pypdf page-by-page extraction
│   │       └── python_parser.py # libcst AST-aware code chunking
│   ├── mcp_server/
│   │   ├── server.py          # FastMCP server + tool registration
│   │   └── tools.py           # Tool implementations + sandbox
│   └── memory/
│       └── session.py         # Session CRUD + log_tool_call decorator + snapshot
├── tests/
│   ├── conftest.py            # Shared fixtures (tmp DB, sample CSV, sample TXT)
│   ├── test_db.py             # FTS5 schema + CRUD tests
│   ├── test_delta.py          # Hashing + diff logic tests
│   ├── test_parsers.py        # Parser output tests
│   ├── test_tools.py          # MCP tool tests (with sandbox verification)
│   └── test_session.py        # Session memory + snapshot tests
├── .env.example               # Config template — copy to .env
├── .gitignore
├── .dockerignore
├── Dockerfile                 # Two-stage build (builder + runtime)
├── LICENSE                    # MIT
├── pyproject.toml             # pytest + coverage config
└── requirements.txt           # Pinned dependencies
```

---

## Quick Start

### GitHub Codespaces

This repository includes a `.devcontainer/devcontainer.json` file, so you can open it directly in GitHub Codespaces and get the same Python + Tesseract environment without any local setup.

1. Open the repository on GitHub.
2. Click `Code`.
3. Switch to the `Codespaces` tab and create a new codespace.
4. Open a terminal and run `pytest` or `python -m src.mcp_server.server`.

### 1. Clone and install

```bash
git clone https://github.com/NikunjSharma-dev/DeltaContext.git
cd DeltaContext

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Install Tesseract (for image OCR)

```bash
# macOS
brew install tesseract

# Ubuntu / Debian
sudo apt install tesseract-ocr tesseract-ocr-eng

# Windows — download installer from https://github.com/UB-Mannheim/tesseract/wiki
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — set WATCH_DIRS to the folder you want indexed
```

### 4. Drop files into the watched directory

```bash
mkdir -p data/inbox
cp your_equity_data.csv data/inbox/
cp scanned_doc.png      data/inbox/
```

### 5. Run the MCP server

```bash
python -m src.mcp_server.server
```

The server runs a full scan on startup, then watches for new files continuously.

---

## Docker

```bash
# Build
docker build -t delta_context .

# Run (mount a local data directory)
docker run \
  -e DELTA_CONTEXT_DB=/data/dc.sqlite \
  -e WATCH_DIRS=/data/inbox \
  -v $(pwd)/data:/data \
  -p 8765:8765 \
  delta_context
```

---

## MCP Tools Reference

### `ctx_search(query, limit=10)`

Full-text search using FTS5 BM25 ranking. Returns JSON array of matching chunks.

```json
[
  {
    "file_path": "/data/inbox/equities.csv",
    "chunk_index": 2,
    "content": "Row 42 | ticker: AAPL | close: 189.25 | volume: 54321200",
    "rank": -1.42
  }
]
```

**FTS5 query syntax:**
- `AAPL earnings` — implicit AND
- `"quarterly report"` — exact phrase
- `AAPL OR GOOG` — OR
- `earnings NOT guidance` — negation

### `ctx_pandas_query(file_path, pandas_expr)`

Sandboxed Pandas execution. `df` and `pd` are available; builtins and I/O are stripped.

```python
# Example queries
"df.describe().to_string()"
"df.groupby('ticker')['close'].mean().sort_values(ascending=False).head(10).to_string()"
"df[df['volume'] > 1_000_000].shape"
```

### `ctx_file_list()`

Returns all indexed files with type and timestamp.

### `ctx_session_summary(session_key)`

Returns a compact resume snapshot for injection into a system prompt:

```
## DeltaContext Resume Snapshot
Session     : my-session-abc
Last active : 2025-06-01 14:32:00
Summary     : Analysed Q1 equity data for AAPL and GOOG.

### Recent tool calls (last 5)
  1. ctx_search({"query": "AAPL"}) → 8ms
  2. ctx_pandas_query(...) → 42ms

### File activity
  - ADDED    /data/inbox/equities_2025-06-01.csv
```

---

## Connecting to Claude

Add this to your Claude desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "deltacontext": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server"],
      "cwd": "/path/to/delta_context",
      "env": {
        "DELTA_CONTEXT_DB": "./data/dc.sqlite",
        "WATCH_DIRS": "./data/inbox"
      }
    }
  }
}
```

---

## Running Tests

```bash
pytest
```

To skip coverage (faster):

```bash
pytest --no-cov -q
```

---

## Adding a New Parser

1. Create `src/engine/parsers/myformat.py` — subclass `BaseParser`, implement `extract()`.
2. Register in `src/engine/parsers/__init__.py`:
   ```python
   from src.engine.parsers.myformat import MyFormatParser
   PARSER_REGISTRY["myformat"] = MyFormatParser()
   ```
3. Add the extension → type mapping in `src/engine/delta.py` `EXTENSION_MAP`.
4. Write tests in `tests/test_parsers.py`.

---

## Architecture Notes

**Why SQLite FTS5?**
SQLite FTS5 with Porter stemming delivers sub-millisecond search on millions of text chunks with zero infrastructure overhead. For a single-node agent pipeline, it vastly outperforms running a separate vector DB process.

**Why xxHash?**
xxHash (xxh64) is ~10x faster than MD5 and non-cryptographic — perfect for content fingerprinting where speed matters and collision resistance doesn't.

**Why the sandbox in ctx_pandas_query?**
The LLM generates arbitrary Python. Stripping `__builtins__` and blocking `open`, `os`, `sys`, and `subprocess` prevents the agent from reading files outside the index or executing system commands through the tool.

---

## License

MIT — see [LICENSE](LICENSE).
