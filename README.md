# DeltaContext ⚡

> **Multimodal ETL Pipeline & Model Context Protocol (MCP) Memory Engine** — Gives LLM Agents (Claude, Antigravity, Cursor) persistent, sub-5ms searchable memory over local files without context window bloat.

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Protocol-purple.svg)](https://modelcontextprotocol.io)
[![SQLite](https://img.shields.io/badge/SQLite-FTS5-green.svg)](https://sqlite.org)
[![Tesseract](https://img.shields.io/badge/OCR-Tesseract%205-orange.svg)](https://github.com/tesseract-ocr/tesseract)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 Candidate Showcase & Engineering Highlights

DeltaContext solves the LLM context window bottleneck by replacing brute-force file dumping with an automated, incremental FTS5 indexing engine and FastMCP server:

- **Incremental xxHash Delta Fingerprinting:** Avoids re-processing static files by tracking 64-bit content hashes; re-indexes changed chunks in under 10ms.
- **AST-Aware Code & Multimodal Parsers:** Uses `libcst` for AST-aware Python code chunking, `pypdf` for page-by-page PDF extraction, Tesseract 5 for OCR image parsing, and `bs4` for script-stripped HTML text extraction.
- **Model Context Protocol (MCP) Tools:** Exposes 3 native MCP tools (`ctx_search`, `ctx_pandas_query`, `ctx_file_list`) allowing AI agents to query structured data via sandboxed Pandas or BM25-ranked full-text search.
- **Session Audit Memory:** Logs every tool execution, AST mutation, and snapshot to survive context window resets.

---

## 🏛️ System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                    INPUT SOURCES                                       │
│    CSVs · Images (OCR) · PDFs · Markdown · Python (AST) · HTML · Word (.docx)          │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              DELTA ENGINE & PARSER REGISTRY                            │
│  · Watchdog File System Observer        · xxHash Content Fingerprinting                │
│  · AST Python Chunking (libcst)        · Tesseract 5 OCR Engine                        │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              STORAGE & QUERY INDEX LAYER                               │
│  · SQLite FTS5 (BM25 Ranking + Porter Stemming)   · Sandboxed Pandas Memory Store      │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 FASTMCP SERVER LAYER                                   │
│            Tools: [ ctx_search ]  [ ctx_pandas_query ]  [ ctx_file_list ]             │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                             LLM AGENTS (Claude / AGY / Cursor)                         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Key Features

| Feature | Engineering Detail |
|---------|-------------------|
| **Incremental Fingerprinting** | Uses `xxhash.xxh64` for microsecond delta checks — untouched files incur 0 I/O cost. |
| **Real-time Observer** | Background `watchdog` thread detects file modifications and triggers async index updates. |
| **AST Code Chunking** | Python files parsed via `libcst` to keep class and function definitions atomically intact. |
| **BM25 Search** | SQLite FTS5 with Porter Stemming delivers BM25 relevance ranking in <5ms. |
| **Sandboxed Execution** | LLMs run `df.describe()` / SQL aggregations via sandboxed Pandas contexts. |
| **Docker Multi-Stage Build** | 2-stage build pre-configured with Tesseract 5 C-libraries & OCR data packs. |

---

## 📁 Repository Structure

```
DeltaContext/
├── .github/workflows/ci.yml   # GitHub Actions CI — pytest, coverage, Docker build
├── src/
│   ├── engine/
│   │   ├── db.py              # SQLite FTS5 database schema & BM25 search
│   │   ├── delta.py           # xxHash fingerprinting & diff logic
│   │   ├── indexer.py         # Watchdog observer & index orchestrator
│   │   └── parsers/           # Multimodal parser registry
│   │       ├── base.py        # Abstract BaseParser & text chunker
│   │       ├── csv.py         # Pandas DataFrame parser
│   │       ├── docx_parser.py # Microsoft Word text extraction
│   │       ├── html_parser.py # Beautiful Soup 4 HTML DOM parser
│   │       ├── image.py       # Tesseract OCR engine integration
│   │       ├── json_parser.py # Hierarchical JSON flattener
│   │       ├── pdf.py         # Page-by-page PDF extractor
│   │       └── python_parser.py # libcst AST code parser
│   ├── mcp_server/
│   │   ├── server.py          # FastMCP server entry point
│   │   └── tools.py           # MCP tool definitions & sandboxed execution
│   └── memory/
│       └── session.py         # Session history & snapshot logger
├── tests/                     # 100% Pytest coverage suite
├── Dockerfile                 # Multi-stage production container build
├── pyproject.toml             # Pytest & coverage configuration
└── requirements.txt           # Pinned production dependencies
```

---

## 🚀 Quick Start

### 1. Clone & Setup Environment

```bash
git clone https://github.com/NikunjSharma-dev/DeltaContext.git
cd DeltaContext

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Tesseract OCR Dependency (Optional for Images)

```bash
# macOS
brew install tesseract

# Ubuntu / Debian
sudo apt-get install -y tesseract-ocr
```

### 3. Launch FastMCP Server

```bash
python -m src.mcp_server.server
```

---

## 🧪 Testing Suite

```bash
# Run complete unit & integration test suite
pytest tests/ -v --cov=src
```

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
