"""
src/engine/parsers/python_parser.py
─────────────────────────────────────
Python source code parser using libcst.

Why libcst instead of just reading .py as text?
------------------------------------------------
Reading a .py file as plain text would work, but it buries the structure.
libcst gives us a proper Concrete Syntax Tree so we can index each
function, class, and module with its docstring and signature separately.

This means the LLM can search:
  "authentication function"   → finds `def authenticate_user(...):`
  "database connection class" → finds `class DBConnection:`
  "deprecation warning"       → finds a docstring that says "deprecated"

...even though the exact word "authentication" might not be in the code.

What gets indexed per chunk
---------------------------
  Module:   file name + module docstring
  Class:    class name + bases + class docstring + method names
  Function: function name + parameters + return annotation + docstring + body summary

Falls back to plain-text chunking if libcst parsing fails (e.g. syntax errors).
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Iterator

from src.engine.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class PythonParser(BaseParser):
    """Parse .py files with AST-aware chunking via libcst."""

    file_type = "python"

    def extract(self, path: Path) -> Iterator[str]:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("PythonParser: cannot read %s — %s", path, exc)
            return

        if not source.strip():
            return

        # Try libcst first; fall back to plain text on parse error
        try:
            import libcst as cst
            yield from self._cst_extract(path, source)
        except Exception as exc:
            logger.warning(
                "PythonParser: libcst parse failed for %s (%s) — falling back to text",
                path.name, exc,
            )
            yield from self._text_fallback(path, source)

    # ── CST extraction ────────────────────────────────────────────────────────

    def _cst_extract(self, path: Path, source: str) -> Iterator[str]:
        import libcst as cst

        tree = cst.parse_module(source)
        visitor = _StructureVisitor(path.name)
        tree.walk(visitor)

        for chunk_text in visitor.chunks:
            cleaned = self.clean(chunk_text)
            if cleaned:
                yield cleaned

    # ── Plain text fallback ───────────────────────────────────────────────────

    def _text_fallback(self, path: Path, source: str) -> Iterator[str]:
        header = f"File: {path.name} (Python source)\n\n"
        full = header + source
        yield from (c for c in self.split_into_chunks(full) if c.strip())


# ── CST Visitor ───────────────────────────────────────────────────────────────

class _StructureVisitor:
    """
    Walks a libcst tree and accumulates one text chunk per
    module / class / function definition.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.chunks: list[str] = []
        self._scope_stack: list[str] = []

    # ── Module ────────────────────────────────────────────────────────────────

    def visit_Module(self, node) -> None:
        import libcst as cst

        docstring = _extract_docstring(node)
        lines = [f"File: {self.filename} (Python module)"]
        if docstring:
            lines.append(f"Module docstring: {docstring}")

        # Collect top-level imports for searchability
        imports: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, (cst.SimpleStatementLine,)):
                for s in stmt.body:
                    if isinstance(s, (cst.Import, cst.ImportFrom)):
                        imports.append(node.code_for_node(s).strip())

        if imports:
            lines.append("Imports: " + ", ".join(imports[:20]))

        self.chunks.append("\n".join(lines))

    # ── Classes ───────────────────────────────────────────────────────────────

    def visit_ClassDef(self, node) -> None:
        import libcst as cst

        name = node.name.value
        bases = ", ".join(
            _arg_to_str(b) for b in node.bases
        ) if node.bases else ""
        docstring = _extract_docstring(node)

        # Collect method names
        methods: list[str] = []
        for item in node.body.body:
            if isinstance(item, cst.FunctionDef):
                methods.append(item.name.value)

        scope = ".".join(self._scope_stack + [name]) if self._scope_stack else name

        lines = [f"Class: {scope}"]
        if bases:
            lines.append(f"Bases: {bases}")
        if docstring:
            lines.append(f"Docstring: {docstring}")
        if methods:
            lines.append(f"Methods: {', '.join(methods)}")
        lines.append(f"File: {self.filename}")

        self.chunks.append("\n".join(lines))
        self._scope_stack.append(name)

    def leave_ClassDef(self, node) -> None:
        if self._scope_stack:
            self._scope_stack.pop()

    # ── Functions ─────────────────────────────────────────────────────────────

    def visit_FunctionDef(self, node) -> None:
        import libcst as cst

        name = node.name.value
        docstring = _extract_docstring(node)
        params = _params_to_str(node.params)

        # Grab the raw code for the entire function
        try:
            module = cst.parse_module("") # dummy module for rendering
            raw_code = module.code_for_node(node)
        except Exception:
            raw_code = ""

        # ... (extract returns as you already did) ...

        scope = ".".join(self._scope_stack + [name]) if self._scope_stack else name

        lines = [f"Function: {scope}({params})"]
        # ... (append returns, docstrings, filename) ...
        
        # APPEND THE RAW CODE
        if raw_code:
            lines.append(f"\nCode:\n{raw_code}")

        self.chunks.append("\n".join(lines))

    # Walk protocol — libcst uses on_visit / on_leave
    def on_visit(self, node) -> bool:
        import libcst as cst
        if isinstance(node, cst.ClassDef):
            self.visit_ClassDef(node)
        elif isinstance(node, cst.FunctionDef):
            self.visit_FunctionDef(node)
        elif isinstance(node, cst.Module):
            self.visit_Module(node)
        return True

    def on_leave(self, node) -> None:
        import libcst as cst
        if isinstance(node, cst.ClassDef):
            self.leave_ClassDef(node)


# ── CST helpers ───────────────────────────────────────────────────────────────

def _extract_docstring(node) -> str:
    """Return the first string literal in a function/class/module body, if any."""
    import libcst as cst

    body = getattr(node, "body", None)
    stmts = getattr(body, "body", []) if body else []

    if not stmts:
        return ""

    first = stmts[0]
    if isinstance(first, cst.SimpleStatementLine) and first.body:
        expr = first.body[0]
        if isinstance(expr, cst.Expr):
            val = expr.value
            if isinstance(val, (cst.SimpleString, cst.FormattedString, cst.ConcatenatedString)):
                try:
                    raw = cst.parse_module("").code_for_node(val)
                    # Strip quotes
                    stripped = raw.strip("\"'").strip()
                    return textwrap.shorten(stripped, width=300, placeholder="...")
                except Exception:
                    pass
    return ""


def _params_to_str(params) -> str:
    """Return a readable parameter string like 'self, path: Path, limit: int = 10'."""
    import libcst as cst

    parts: list[str] = []
    module = cst.parse_module("")

    def _ann(p):
        if p.annotation:
            try:
                return ": " + module.code_for_node(p.annotation.annotation)
            except Exception:
                return ""
        return ""

    def _default(p):
        if p.default:
            try:
                return " = " + module.code_for_node(p.default)
            except Exception:
                return " = ..."
        return ""

    for p in params.params:
        parts.append(p.name.value + _ann(p) + _default(p))

    if params.star_kwarg:
        parts.append("**" + params.star_kwarg.name.value)

    return ", ".join(parts)


def _arg_to_str(arg) -> str:
    import libcst as cst
    try:
        return cst.parse_module("").code_for_node(arg.value)
    except Exception:
        return "?"
    