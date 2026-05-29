"""
src/engine/parsers/__init__.py
──────────────────────────────
Parser registry — maps file_type strings to parser instances.

To add a new format:
1. Create parsers/myformat.py with a class inheriting BaseParser.
2. Add an entry to PARSER_REGISTRY below.
3. Add the file extension → type mapping in delta.py EXTENSION_MAP.
"""

from src.engine.parsers.base import BaseParser
from src.engine.parsers.csv import CSVParser
from src.engine.parsers.docx_parser import DOCXParser
from src.engine.parsers.html_parser import HTMLParser
from src.engine.parsers.image import ImageParser
from src.engine.parsers.json_parser import JSONParser
from src.engine.parsers.pdf import PDFParser
from src.engine.parsers.python_parser import PythonParser
from src.engine.parsers.text import TextParser

# Singleton instances — parsers are stateless, so one per type is enough
PARSER_REGISTRY: dict[str, BaseParser] = {
    # ── Original ──────────────────────────────────────────────────────────────
    "csv":    CSVParser(mode="auto"),
    "text":   TextParser(),
    "image":  ImageParser(),
    "pdf":    PDFParser(),
    # ── Phase 7A additions ────────────────────────────────────────────────────
    "json":   JSONParser(),
    "docx":   DOCXParser(),
    "html":   HTMLParser(),
    "python": PythonParser(),
}


def get_parser(file_type: str) -> BaseParser:
    """
    Return the parser for *file_type*.

    Raises
    ------
    KeyError if the file_type has no registered parser.
    """
    try:
        return PARSER_REGISTRY[file_type]
    except KeyError:
        raise KeyError(
            f"No parser registered for file_type={file_type!r}. "
            f"Available: {list(PARSER_REGISTRY)}"
        )


__all__ = [
    "BaseParser", "CSVParser", "DOCXParser", "HTMLParser",
    "ImageParser", "JSONParser", "PDFParser", "PythonParser",
    "TextParser", "get_parser",
]