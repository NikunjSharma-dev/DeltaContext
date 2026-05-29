"""
src/engine/parsers/__init__.py
──────────────────────────────
Parser registry — maps file_type strings to parser instances.

To add a new format:
1. Create parsers/myparsers.py with a class inheriting BaseParser.
2. Add an entry to PARSER_REGISTRY below.
"""

from src.engine.parsers.base import BaseParser
from src.engine.parsers.csv import CSVParser
from src.engine.parsers.image import ImageParser
from src.engine.parsers.pdf import PDFParser
from src.engine.parsers.text import TextParser

# Singleton instances — parsers are stateless, so one per type is enough
PARSER_REGISTRY: dict[str, BaseParser] = {
    "csv": CSVParser(mode="auto"),
    "text": TextParser(),
    "image": ImageParser(),
    "pdf": PDFParser(),
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


__all__ = ["BaseParser", "CSVParser", "ImageParser", "PDFParser", "TextParser", "get_parser"]
