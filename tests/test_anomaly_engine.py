from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import anomaly_engine as anomaly_engine  # noqa: E402


def _seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE AI_TEST_INVOICEBILLREGISTER (
                DT TEXT,
                LOCATION_NAME TEXT,
                NETAMT REAL,
                TRNNO TEXT
            );
            INSERT INTO AI_TEST_INVOICEBILLREGISTER VALUES
              ('2026-01-01T10:00:00','TestOutlet',80.0,'a1'),
              ('2026-01-02T10:00:00','TestOutlet',82.0,'a2'),
              ('2026-01-03T10:00:00','TestOutlet',78.0,'a3'),
              ('2026-01-04T10:00:00','TestOutlet',81.0,'a4'),
              ('2026-01-05T10:00:00','TestOutlet',79.0,'a5'),
              ('2026-01-06T10:00:00','TestOutlet',83.0,'a6'),
              ('2026-01-07T10:00:00','TestOutlet',77.0,'a7'),
              ('2026-01-08T10:00:00','TestOutlet',80.0,'a8'),
              ('2026-01-09T10:00:00','TestOutlet',5.0,'a9');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_anomaly_engine_detects_dip(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    _seed(db)
    anomalies = anomaly_engine.detect_anomalies_all_outlets(db_path=db)
    assert any(a.severity in ("WARNING", "CRITICAL") for a in anomalies)
