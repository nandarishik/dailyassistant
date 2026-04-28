from __future__ import annotations

from src.sql.sql_guard import ensure_row_limit, validate_llm_select


def test_validate_accepts_simple_select() -> None:
    ok, err = validate_llm_select("SELECT 1")
    assert ok and err == ""


def test_validate_rejects_non_select() -> None:
    ok, err = validate_llm_select("DELETE FROM t")
    assert not ok


def test_validate_rejects_pragma_statement() -> None:
    ok, err = validate_llm_select("PRAGMA journal_mode=WAL")
    assert not ok


def test_ensure_row_limit_appends() -> None:
    assert "LIMIT" in ensure_row_limit("SELECT 1")


def test_ensure_row_limit_preserves_existing() -> None:
    s = "SELECT 1 LIMIT 5"
    assert ensure_row_limit(s) == s
