"""tests/test_delta.py — Delta engine: hashing + diff logic tests."""

from pathlib import Path

import pandas as pd
import pytest

from src.engine.db import DB
from src.engine.delta import compute_delta, hash_file, scan_directory


def test_hash_file_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    h1 = hash_file(f)
    h2 = hash_file(f)
    assert h1 == h2
    assert len(h1) == 16  # xxh64 hex = 16 chars


def test_hash_file_changes_on_content_change(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("version 1")
    h1 = hash_file(f)
    f.write_text("version 2")
    h2 = hash_file(f)
    assert h1 != h2


def test_scan_directory_finds_csv(tmp_path: Path, sample_csv: Path) -> None:
    # sample_csv fixture writes to tmp_path, just scan it
    df = scan_directory(sample_csv.parent)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["file_type"] == "csv"
    assert row["file_path"] == str(sample_csv)


def test_scan_directory_skips_unknown_extensions(tmp_path: Path) -> None:
    (tmp_path / "file.xyz").write_text("skip me")
    df = scan_directory(tmp_path)
    assert len(df) == 0


def test_compute_delta_added(tmp_db: DB, sample_csv: Path) -> None:
    df = scan_directory(sample_csv.parent)
    delta = compute_delta(df, tmp_db)
    assert len(delta.added) == 1
    assert delta.modified == []
    assert delta.deleted == []


def test_compute_delta_modified(tmp_db: DB, sample_csv: Path) -> None:
    # Index the file first
    tmp_db.upsert_file_state(str(sample_csv), "oldhash", 0.0, "csv")
    df = scan_directory(sample_csv.parent)
    delta = compute_delta(df, tmp_db)
    assert len(delta.modified) == 1
    assert delta.added == []
    assert delta.deleted == []


def test_compute_delta_deleted(tmp_db: DB, tmp_path: Path) -> None:
    # DB knows about a file that no longer exists on disk
    tmp_db.upsert_file_state("/ghost/file.csv", "hash", 0.0, "csv")
    df = pd.DataFrame(columns=["file_path", "content_hash", "mtime", "file_type"])
    delta = compute_delta(df, tmp_db)
    assert "/ghost/file.csv" in delta.deleted


def test_compute_delta_unchanged(tmp_db: DB, sample_csv: Path) -> None:
    # Pre-index with the REAL hash so nothing should be flagged
    real_hash = hash_file(sample_csv)
    mtime = sample_csv.stat().st_mtime
    tmp_db.upsert_file_state(str(sample_csv), real_hash, mtime, "csv")
    df = scan_directory(sample_csv.parent)
    delta = compute_delta(df, tmp_db)
    assert delta.is_empty()
