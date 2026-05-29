"""
src/engine/parsers/json_parser.py
──────────────────────────────────
JSON parser — flattens arbitrarily nested JSON into searchable key:value text.

Strategy
--------
Recursively walk the JSON tree. Every leaf value (string, number, bool) is
emitted as a "path: value" line so the LLM can search by either key name or
value content.

Examples
--------
Input:
    {"ticker": "AAPL", "financials": {"close": 189.25, "volume": 54321200}}

Output chunk:
    File: data.json
    ticker: AAPL
    financials.close: 189.25
    financials.volume: 54321200

Arrays of objects (common in API responses / data exports) each get their
own numbered block:
    trades[0].price: 189.25
    trades[0].qty: 100
    trades[1].price: 190.00
    trades[1].qty: 50

Large JSON files are split into chunks so FTS5 entries stay readable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

from src.engine.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Max characters per FTS5 chunk
_CHUNK_LINES = 60   # lines, not chars — keeps chunks human-readable


class JSONParser(BaseParser):
    """Parse .json files into flat key:value text chunks."""

    file_type = "json"

    def extract(self, path: Path) -> Iterator[str]:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("JSONParser: cannot read %s — %s", path, exc)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("JSONParser: invalid JSON in %s — %s", path, exc)
            # Still index the raw text so the file isn't invisible
            yield self.clean(f"File: {path.name} (malformed JSON)\n\n{raw[:2000]}")
            return

        lines: list[str] = [f"File: {path.name}"]
        self._flatten(data, prefix="", lines=lines)

        # Emit in batches of _CHUNK_LINES lines
        header = lines[0]
        body = lines[1:]

        for i in range(0, max(len(body), 1), _CHUNK_LINES):
            batch = body[i : i + _CHUNK_LINES]
            chunk = self.clean(header + "\n" + "\n".join(batch))
            if chunk:
                yield chunk

    # ── Recursive flattener ───────────────────────────────────────────────────

    def _flatten(
        self,
        node: Any,
        prefix: str,
        lines: list[str],
        depth: int = 0,
    ) -> None:
        """Recursively flatten *node* into key:value lines appended to *lines*."""

        # Guard against pathological nesting
        if depth > 20:
            lines.append(f"{prefix}: [deeply nested — truncated]")
            return

        if isinstance(node, dict):
            for key, value in node.items():
                child_prefix = f"{prefix}.{key}" if prefix else key
                self._flatten(value, child_prefix, lines, depth + 1)

        elif isinstance(node, list):
            for i, item in enumerate(node):
                child_prefix = f"{prefix}[{i}]"
                self._flatten(item, child_prefix, lines, depth + 1)

        else:
            # Leaf node — emit as "key: value"
            value_str = str(node) if not isinstance(node, str) else node
            # Skip empty strings and None
            if value_str and value_str.lower() != "none":
                lines.append(f"{prefix}: {value_str}")