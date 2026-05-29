"""
src/engine/delta.py
───────────────────
The Delta Engine: computes exactly which files are new, changed, or deleted
by comparing the live filesystem against the last-known state in SQLite.

Design
------
1. `hash_file()` – xxhash of file contents (fast, non-cryptographic).
2. `scan_directory()` – walks a directory tree and returns a DataFrame of
   (file_path, content_hash, mtime, file_type).
3. `compute_delta()` – Pandas merge of current state vs. DB state, returning
   three lists: added, modified, deleted.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
import xxhash

from src.engine.db import DB

logger = logging.getLogger(__name__)

# ── Supported extensions → parser type tags ───────────────────────────────────
EXTENSION_MAP: dict[str, str] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "text",
    ".md": "text",
    ".rst": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".webp": "image",
    ".pdf": "pdf",
}


# ── Hashing ───────────────────────────────────────────────────────────────────

def hash_file(path: Path) -> str:
    """
    Return a hex digest of the file using xxHash (xxh64).
    Reads in 1 MiB blocks to avoid loading large files into RAM.
    """
    h = xxhash.xxh64()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ── Directory scan ────────────────────────────────────────────────────────────

def scan_directory(root: str | Path) -> pd.DataFrame:
    """
    Walk *root* recursively and return a DataFrame describing every supported
    file found.

    Columns
    -------
    file_path     : str  – absolute path string
    content_hash  : str  – xxh64 hex digest
    mtime         : float – os.path.getmtime
    file_type     : str  – one of csv / text / image / pdf
    """
    root = Path(root).resolve()
    records: list[dict] = []

    for dirpath, _dirs, filenames in os.walk(root):
        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()
            ftype = EXTENSION_MAP.get(ext)
            if ftype is None:
                continue  # skip unsupported types silently

            try:
                records.append(
                    {
                        "file_path": str(fpath),
                        "content_hash": hash_file(fpath),
                        "mtime": fpath.stat().st_mtime,
                        "file_type": ftype,
                    }
                )
            except OSError as exc:
                logger.warning("Could not read %s: %s", fpath, exc)

    return pd.DataFrame(
        records,
        columns=["file_path", "content_hash", "mtime", "file_type"],
    )


# ── Delta computation ─────────────────────────────────────────────────────────

class FileDelta:
    """Container for the three-way diff result."""

    __slots__ = ("added", "modified", "deleted")

    def __init__(
        self,
        added: list[dict],
        modified: list[dict],
        deleted: list[str],
    ) -> None:
        self.added = added
        self.modified = modified
        self.deleted = deleted

    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FileDelta(added={len(self.added)}, "
            f"modified={len(self.modified)}, "
            f"deleted={len(self.deleted)})"
        )


def compute_delta(current_df: pd.DataFrame, db: DB) -> FileDelta:
    """
    Compare *current_df* (live scan) against the indexed state in *db*.

    Algorithm
    ---------
    1. Load DB state into a DataFrame.
    2. Left-merge on file_path.
    3. Classify each row:
       - present in current only  → added
       - present in both, hash changed → modified
       - present in DB only       → deleted

    Parameters
    ----------
    current_df : output of scan_directory()
    db         : initialised DB instance

    Returns
    -------
    FileDelta
    """
    # ── Build DB state DF ─────────────────────────────────────────────────────
    db_rows = db.all_file_states()
    db_df = pd.DataFrame(
        [dict(r) for r in db_rows],
        columns=["file_path", "content_hash", "mtime", "file_type", "id", "indexed_at"],
    ) if db_rows else pd.DataFrame(
        columns=["file_path", "content_hash", "mtime", "file_type"]
    )

    # ── Outer merge on file_path ──────────────────────────────────────────────
    merged = pd.merge(
        current_df,
        db_df[["file_path", "content_hash"]].rename(
            columns={"content_hash": "db_hash"}
        ),
        on="file_path",
        how="outer",
        indicator=True,
    )

    # ── Classify ──────────────────────────────────────────────────────────────
    added_mask = merged["_merge"] == "left_only"
    deleted_mask = merged["_merge"] == "right_only"
    both_mask = merged["_merge"] == "both"
    changed_mask = both_mask & (merged["content_hash"] != merged["db_hash"])

    def _to_records(df: pd.DataFrame) -> list[dict]:
        return df[["file_path", "content_hash", "mtime", "file_type"]].to_dict(
            orient="records"
        )

    added = _to_records(merged[added_mask])
    modified = _to_records(merged[changed_mask])
    deleted = merged.loc[deleted_mask, "file_path"].tolist()

    delta = FileDelta(added=added, modified=modified, deleted=deleted)
    logger.info("Delta: %r", delta)
    return delta
