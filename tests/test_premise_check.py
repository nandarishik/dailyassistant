from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from src.config.settings import clear_settings_cache
from src.copilot.premise_check import compute_premise_check, implies_decline_premise


def _seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE AI_TEST_INVOICEBILLREGISTER (
                DT TEXT, LOCATION_NAME TEXT, NETAMT REAL, TRNNO TEXT
            );
            INSERT INTO AI_TEST_INVOICEBILLREGISTER VALUES
              ('2026-01-01T10:00:00','O1',300.0,'a'),
              ('2026-01-02T10:00:00','O1',100.0,'b'),
              ('2026-01-03T10:00:00','O1',200.0,'c');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_implies_decline() -> None:
    assert implies_decline_premise("Why did revenue drop on 2026-01-01?")
    assert not implies_decline_premise("Total revenue on 2026-01-01")


def test_premise_rank_and_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "mini.db"
    _seed(db)
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        out = compute_premise_check("Worst day ever on 2026-01-01?", tmp_path)
        assert out is not None
        assert out["queried_date"] == "2026-01-01"
        assert out["rank"] == 1
        assert out["is_peak"] is True
        assert out["premise_conflict"] is True
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()


def test_premise_no_decline_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "mini.db"
    _seed(db)
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        assert compute_premise_check("Total revenue on 2026-01-01?", tmp_path) is None
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()


def test_premise_no_iso_date_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "mini.db"
    _seed(db)
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        assert compute_premise_check("Why did revenue drop in January?", tmp_path) is None
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()


def test_premise_true_trough_not_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lowest-revenue day has rank > 3 in a 5-day series → no premise_conflict."""
    db = tmp_path / "database" / "mini.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE AI_TEST_INVOICEBILLREGISTER (
                DT TEXT, LOCATION_NAME TEXT, NETAMT REAL, TRNNO TEXT
            );
            INSERT INTO AI_TEST_INVOICEBILLREGISTER VALUES
              ('2026-01-01T10:00:00','O1',500.0,'a'),
              ('2026-01-02T10:00:00','O1',50.0,'b'),
              ('2026-01-03T10:00:00','O1',400.0,'c'),
              ('2026-01-04T10:00:00','O1',350.0,'d'),
              ('2026-01-05T10:00:00','O1',300.0,'e');
            """
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        out = compute_premise_check("Terrible drop on 2026-01-02?", tmp_path)
        assert out is not None
        assert out["queried_date"] == "2026-01-02"
        assert out["rank"] == 5
        assert out["premise_conflict"] is False
        assert out["is_peak"] is False
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()
