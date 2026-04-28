"""Tests for database path resolution and runtime validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.config.runtime_check import DatabaseConfigError, validate_database_path
from src.config.settings import resolve_db_path


def test_resolve_db_path_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DB_PATH", raising=False)
    p = resolve_db_path(tmp_path)
    assert p == tmp_path / "database" / "AI_DATABASE.DB"


def test_resolve_db_path_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PATH", "custom/foo.db")
    p = resolve_db_path(tmp_path)
    assert p == tmp_path / "custom" / "foo.db"
    monkeypatch.delenv("APP_DB_PATH", raising=False)


def test_validate_rejects_parent_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PATH", "../outside.db")
    with pytest.raises(DatabaseConfigError, match="\\.\\."):
        validate_database_path(tmp_path, require_exists=False)


def test_validate_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PATH", "database/missing.db")
    (tmp_path / "database").mkdir(parents=True)
    with pytest.raises(DatabaseConfigError, match="not found"):
        validate_database_path(tmp_path, require_exists=True)


def test_validate_ok_when_file_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DB_PATH", "database/AI_DATABASE.DB")
    db = tmp_path / "database" / "AI_DATABASE.DB"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"")
    out = validate_database_path(tmp_path, require_exists=True)
    assert out == db
