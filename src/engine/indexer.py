"""
src/engine/indexer.py
─────────────────────
Orchestrates the full pipeline:

  scan → delta → parse → upsert FTS + file_state

Also provides a watchdog-based real-time watcher so files are indexed the
moment they land in the watched directory.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.engine.db import DB
from src.engine.delta import compute_delta, scan_directory, EXTENSION_MAP
from src.engine.parsers import get_parser

logger = logging.getLogger(__name__)


# ── Core indexing logic ───────────────────────────────────────────────────────

class Indexer:
    """
    High-level controller that ties together the delta engine and the parsers.

    Usage
    -----
    idx = Indexer(db=DB(), watch_dirs=["./data/inbox"])
    idx.run_full_scan()   # one-shot: index everything that changed
    idx.start_watcher()   # start background watchdog thread
    """

    def __init__(self, db: DB, watch_dirs: list[str | Path]) -> None:
        self.db = db
        self.watch_dirs = [Path(d).resolve() for d in watch_dirs]
        self._observer: Observer | None = None

    # ── Full scan (batch mode) ────────────────────────────────────────────────

    def run_full_scan(self) -> None:
        """
        Walk all watch_dirs, compute the delta vs. the DB, and process every
        added / modified / deleted file.
        """
        import pandas as pd

        all_frames = [scan_directory(d) for d in self.watch_dirs]
        current_df = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()

        delta = compute_delta(current_df, self.db)

        for record in delta.added + delta.modified:
            self._index_file(record["file_path"], record["content_hash"], record["mtime"], record["file_type"])

        for file_path in delta.deleted:
            self._remove_file(file_path)

    # ── Real-time watcher ─────────────────────────────────────────────────────

    def start_watcher(self) -> None:
        """Start a watchdog observer in a background thread."""
        if self._observer and self._observer.is_alive():
            return  # already running

        handler = _DeltaEventHandler(self)
        self._observer = Observer()
        for d in self.watch_dirs:
            self._observer.schedule(handler, str(d), recursive=True)
        self._observer.start()
        logger.info("Watcher started for: %s", self.watch_dirs)

    def stop_watcher(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Watcher stopped.")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _index_file(
        self, file_path: str, content_hash: str, mtime: float, file_type: str
    ) -> None:
        logger.info("Indexing [%s] %s", file_type, file_path)
        try:
            parser = get_parser(file_type)
            chunks = list(parser.extract(Path(file_path)))
            self.db.upsert_chunks(file_path, chunks)
            self.db.upsert_file_state(file_path, content_hash, mtime, file_type)
        except Exception as exc:
            logger.error("Failed to index %s: %s", file_path, exc, exc_info=True)

    def _remove_file(self, file_path: str) -> None:
        logger.info("Removing [deleted] %s", file_path)
        self.db.delete_chunks(file_path)
        self.db.delete_file_state(file_path)


# ── Watchdog event handler ────────────────────────────────────────────────────

class _DeltaEventHandler(FileSystemEventHandler):
    """Routes watchdog filesystem events back to the Indexer."""

    def __init__(self, indexer: Indexer) -> None:
        super().__init__()
        self._indexer = indexer

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._process(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._process(event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._indexer._remove_file(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._indexer._remove_file(event.src_path)
            self._process(event.dest_path)

    def _process(self, raw_path: str) -> None:
        path = Path(raw_path)
        ext = path.suffix.lower()
        file_type = EXTENSION_MAP.get(ext)
        if file_type is None:
            return  # unsupported extension — ignore

        try:
            from src.engine.delta import hash_file
            content_hash = hash_file(path)
            mtime = path.stat().st_mtime

            # Only re-index if content actually changed
            existing = self._indexer.db.get_file_state(str(path))
            if existing and existing["content_hash"] == content_hash:
                return

            self._indexer._index_file(str(path), content_hash, mtime, file_type)
        except OSError:
            pass  # file may have been deleted between event and processing
