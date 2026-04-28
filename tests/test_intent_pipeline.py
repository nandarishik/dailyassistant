from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from src.config.settings import clear_settings_cache
from src.intent.pipeline import try_guarded_intent_run


def _seed_minimal_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE AI_TEST_INVOICEBILLREGISTER (
                DT TEXT,
                LOCATION_NAME TEXT,
                NETAMT REAL,
                TRNNO TEXT,
                PAX TEXT,
                CASH_AMT REAL,
                CARD_AMT REAL,
                PAYMENT_UPI REAL
            );
            CREATE TABLE AI_TEST_TAXCHARGED_REPORT (
                DT TEXT,
                LOCATION_NAME TEXT,
                NET_AMT REAL,
                QTY REAL,
                PRODUCT_NAME TEXT,
                ORDERTYPE_NAME TEXT,
                TRNNO TEXT,
                GROUP_NAME TEXT,
                ORDER_STARTTIME TEXT
            );
            INSERT INTO AI_TEST_INVOICEBILLREGISTER VALUES
              ('2026-01-01T10:00:00','Outlet A',100.0,'T1','1',0,0,0),
              ('2026-01-01T10:00:00','Outlet B',200.0,'T2','1',0,0,0),
              ('2026-01-02T10:00:00','Outlet A',50.0,'T3','1',0,0,0);
            INSERT INTO AI_TEST_TAXCHARGED_REPORT VALUES
              ('2026-01-01T10:00:00','Outlet A',40.0,2.0,'Latte','Dine','T1','Bev','10:00'),
              ('2026-01-01T10:00:00','Outlet A',60.0,1.0,'Muffin','Dine','T1','Food','10:00');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_intent_total_revenue_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "mini.db"
    _seed_minimal_db(db)
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        out = try_guarded_intent_run("What is the total chain revenue in January 2026?", tmp_path)
        assert out is not None
        assert out["engine"] == "IntentSQL"
        assert "evidence" in out and out["evidence"]["intent"] == "total_revenue"
        assert "350" in (out.get("response") or "") or "350.0" in (out.get("response") or "")
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()


def test_intent_single_day_chain_revenue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "mini.db"
    _seed_minimal_db(db)
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        out = try_guarded_intent_run("How much total revenue on 2026-01-01?", tmp_path)
        assert out is not None
        assert out["evidence"]["intent"] == "single_day_chain_revenue"
        assert "300" in (out.get("response") or "") or "300.0" in (out.get("response") or "")
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()


def test_intent_decline_on_date_includes_premise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "mini.db"
    _seed_minimal_db(db)
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        out = try_guarded_intent_run(
            "Why did revenue drop on 2026-01-01? Worst day.",
            tmp_path,
        )
        assert out is not None
        assert out["evidence"]["intent"] == "decline_on_date"
        assert out["evidence"].get("premise_check")
        assert "data_scope" in out["evidence"]
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()


def test_intent_no_match_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "database" / "mini.db"
    _seed_minimal_db(db)
    monkeypatch.setenv("APP_DB_PATH", "database/mini.db")
    clear_settings_cache()
    try:
        assert try_guarded_intent_run("Explain quantum gravity", tmp_path) is None
    finally:
        monkeypatch.delenv("APP_DB_PATH", raising=False)
        clear_settings_cache()
