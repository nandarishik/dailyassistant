from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.config.settings import resolve_db_path


def get_db_path(base_dir: Path) -> Path:
    return resolve_db_path(base_dir)


@contextmanager
def sqlite_connection(base_dir: Path, timeout: float = 10.0):
    conn = None
    try:
        conn = sqlite3.connect(str(get_db_path(base_dir)), timeout=timeout)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        yield conn
    finally:
        if conn:
            conn.close()
