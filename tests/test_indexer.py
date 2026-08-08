"""tests/test_indexer.py — Tests for Indexer & Watchdog event handler."""

from pathlib import Path
import time
import pytest
from src.engine.db import DB
from src.engine.indexer import Indexer, _DeltaEventHandler


class TestIndexer:
    def test_run_full_scan(self, tmp_db: DB, tmp_path: Path) -> None:
        file1 = tmp_path / "test1.txt"
        file1.write_text("Hello world testing indexer scan")
        
        file2 = tmp_path / "data.csv"
        file2.write_text("col1,col2\nval1,val2\n")
        
        indexer = Indexer(db=tmp_db, watch_dirs=[tmp_path])
        indexer.run_full_scan()
        
        indexed_files = tmp_db.all_file_states()
        paths = [f["file_path"] for f in indexed_files]
        assert str(file1) in paths
        assert str(file2) in paths
        
        # Test deletion scan
        file1.unlink()
        indexer.run_full_scan()
        
        indexed_files_after = tmp_db.all_file_states()
        paths_after = [f["file_path"] for f in indexed_files_after]
        assert str(file1) not in paths_after
        assert str(file2) in paths_after

    def test_watcher_lifecycle(self, tmp_db: DB, tmp_path: Path) -> None:
        indexer = Indexer(db=tmp_db, watch_dirs=[tmp_path])
        indexer.start_watcher()
        assert indexer._observer is not None and indexer._observer.is_alive()
        
        # Calling start_watcher again should be a no-op
        indexer.start_watcher()
        
        indexer.stop_watcher()
        assert indexer._observer is None

    def test_event_handler_methods(self, tmp_db: DB, tmp_path: Path) -> None:
        indexer = Indexer(db=tmp_db, watch_dirs=[tmp_path])
        handler = _DeltaEventHandler(indexer)
        
        test_file = tmp_path / "sample.txt"
        test_file.write_text("Event handler sample text")
        
        class DummyEvent:
            def __init__(self, src_path, dest_path=None, is_directory=False):
                self.src_path = str(src_path)
                self.dest_path = str(dest_path) if dest_path else None
                self.is_directory = is_directory

        # Test on_created & on_modified
        handler.on_created(DummyEvent(test_file))
        assert len(tmp_db.all_file_states()) == 1
        
        handler.on_modified(DummyEvent(test_file))
        assert len(tmp_db.all_file_states()) == 1

        # Test on_moved
        new_file = tmp_path / "renamed.txt"
        test_file.rename(new_file)
        handler.on_moved(DummyEvent(test_file, new_file))
        
        paths = [f["file_path"] for f in tmp_db.all_file_states()]
        assert str(new_file) in paths
        assert str(test_file) not in paths

        # Test on_deleted
        new_file.unlink()
        handler.on_deleted(DummyEvent(new_file))
        paths = [f["file_path"] for f in tmp_db.all_file_states()]
        assert str(new_file) not in paths
