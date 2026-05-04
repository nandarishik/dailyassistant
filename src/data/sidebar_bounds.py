"""Outlet list and date extrema from the warehouse (sqlite only — no pandas)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from src.data.access.db import sqlite_connection


@dataclass(frozen=True)
class OutletDateBounds:
    outlets: list[str]
    min_date: date
    max_date: date


def _parse_yyyy_mm_dd(value: object) -> date:
    if value is None:
        return date(2026, 1, 1)
    s = str(value)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return date(2026, 1, 1)


def load_outlet_date_bounds(base_dir: Path) -> OutletDateBounds:
    """Same source tables as `kpi_service.load_sidebar_filter_options`, without pandas."""
    base = Path(base_dir)
    with sqlite_connection(base) as conn:
        cur = conn.execute(
            "SELECT DISTINCT ZONE AS outlet_name FROM VIEW_AI_SALES "
            "ORDER BY ZONE;"
        )
        outlets = [r[0] for r in cur.fetchall() if r[0]]
        cur = conn.execute(
            "SELECT SUBSTR(MIN(INVOICE_DATE), 1, 10) AS mn, SUBSTR(MAX(INVOICE_DATE), 1, 10) AS mx "
            "FROM VIEW_AI_SALES;"
        )
        row = cur.fetchone()
    mn, mx = (row[0], row[1]) if row else (None, None)
    min_date = _parse_yyyy_mm_dd(mn)
    max_date = _parse_yyyy_mm_dd(mx) if mx else min_date
    if max_date < min_date:
        max_date = min_date
    return OutletDateBounds(outlets=outlets, min_date=min_date, max_date=max_date)
