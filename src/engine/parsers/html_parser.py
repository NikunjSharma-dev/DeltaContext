"""
src/engine/parsers/html_parser.py
───────────────────────────────────
HTML parser using BeautifulSoup4.

Strategy
--------
1. Strip all <script>, <style>, <meta>, <noscript>, <head> tags entirely.
2. Extract visible text from the remaining DOM.
3. Preserve structural hints:
   - <title>       → prefixed with "Page title: "
   - <h1>-<h6>     → prefixed with #-###### (Markdown style)
   - <table>       → rows emitted as pipe-separated lines
   - <a href="..."> → URLs appended as "Link: <url>" so they're searchable
4. Split into chunks and yield.

This handles .html files from web scrapes, exported reports, dashboards,
and any HTML-formatted documentation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator

from src.engine.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_STRIP_TAGS = {"script", "style", "meta", "noscript", "head", "iframe", "svg"}
_HEADING_MAP = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "######"}


class HTMLParser(BaseParser):
    """Parse .html files into clean, searchable text chunks."""

    file_type = "html"

    def extract(self, path: Path) -> Iterator[str]:
        try:
            from bs4 import BeautifulSoup, Comment
        except ImportError:
            logger.warning("HTMLParser: beautifulsoup4 not installed. Skipping %s.", path)
            yield f"[HTML parser unavailable] {path.name}"
            return

        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("HTMLParser: cannot read %s — %s", path, exc)
            return

        soup = BeautifulSoup(raw, "html.parser")

        # Remove invisible / noisy tags completely
        for tag in soup.find_all(_STRIP_TAGS):
            tag.decompose()

        # Remove HTML comments
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        lines: list[str] = [f"File: {path.name}"]

        # <title>
        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            lines.append(f"Page title: {title_tag.get_text(strip=True)}")

        # Walk the body (or whole doc if no body tag)
        root = soup.find("body") or soup

        self._walk(root, lines)

        # Yield in chunks
        full_text = self.clean("\n".join(lines))
        yield from (c for c in self.split_into_chunks(full_text) if c.strip())

    # ── DOM walker ────────────────────────────────────────────────────────────

    def _walk(self, node, lines: list[str]) -> None:
        from bs4 import NavigableString, Tag

        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                lines.append(text)
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower() if node.name else ""

        # Headings
        if tag in _HEADING_MAP:
            text = node.get_text(separator=" ", strip=True)
            if text:
                lines.append(_HEADING_MAP[tag] + text)
            return

        # Tables — emit as structured rows
        if tag == "table":
            self._extract_table(node, lines)
            return

        # Links — append URL so they're searchable
        if tag == "a":
            text = node.get_text(separator=" ", strip=True)
            href = node.get("href", "").strip()
            if text:
                line = text
                if href and href.startswith("http"):
                    line += f"  [Link: {href}]"
                lines.append(line)
            return

        # Block elements — add blank line for readability
        if tag in {"p", "div", "section", "article", "li", "dt", "dd", "blockquote"}:
            inner = node.get_text(separator=" ", strip=True)
            if inner:
                lines.append(inner)
            return

        # Recurse into everything else
        for child in node.children:
            self._walk(child, lines)

    def _extract_table(self, table_node, lines: list[str]) -> None:
        from bs4 import Tag

        rows = table_node.find_all("tr")
        if not rows:
            return

        lines.append("")
        for r_idx, row in enumerate(rows, start=1):
            cells = [
                cell.get_text(separator=" ", strip=True)
                for cell in row.find_all(["th", "td"])
            ]
            if any(cells):
                lines.append(f"Row {r_idx}: " + " | ".join(cells))
        lines.append("")