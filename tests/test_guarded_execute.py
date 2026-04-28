from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from src.config.settings import clear_settings_cache
from src.sql.guarded_execute import fetch_select_as_markdown


def test_fetch_select_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "g.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INT)")
    conn.execute("INSERT INTO t VALUES (1),(2)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("APP_DB_PATH", "database/g.db")
    clear_settings_cache()
    try:
        md = fetch_select_as_markdown(tmp_path, "SELECT x FROM t ORDER BY x")
        assert "| x |" in md
        assert "1" in md and "2" in md
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()


def test_fetch_select_rejects_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "database").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APP_DB_PATH", "database/g.db")
    clear_settings_cache()
    try:
        md = fetch_select_as_markdown(tmp_path, "DELETE FROM t")
        assert md.startswith("ERROR:")
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()
