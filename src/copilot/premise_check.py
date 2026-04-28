"""Server-side rank / peak check when user implies a revenue decline for a single day."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from src.config.settings import get_settings
from src.data.access.db import sqlite_connection
from src.data.sidebar_bounds import load_outlet_date_bounds

_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_DECLINE = re.compile(
    r"\b("
    r"drop|declin|worst|fell|fallen|underperform|slow\s+day|low\s+sales|"
    r"plummet|tank|slump|downturn|dip\b|down\s+vs|below\s+avg|below\s+average"
    r")\b",
    re.IGNORECASE,
)

# User said "drop" etc. but day is among the best in window -> conflict
_PREMISE_CONFLICT_MAX_RANK = 3


def implies_decline_premise(question: str) -> bool:
    return bool(_DECLINE.search(question or ""))


def compute_premise_check(question: str, base_dir: Path) -> dict[str, Any] | None:
    """
    If decline-like wording and exactly one ISO date, return rank vs other days
    (same outlet universe as sidebar bounds). Otherwise None.
    """
    if not implies_decline_premise(question):
        return None
    dates = sorted(set(_DATE_RE.findall(question)))
    if len(dates) != 1:
        return None
    target = dates[0]
    try:
        date.fromisoformat(target)
    except ValueError:
        return None

    bounds = load_outlet_date_bounds(base_dir)
    outlets = list(bounds.outlets)
    if not outlets:
        return None

    window = (get_settings().copilot_premise_rank_window or "all").lower()
    ph = ",".join("?" * len(outlets))
    extra = ""
    params: list[Any] = list(outlets)

    if window == "month":
        extra = " AND SUBSTR(DT, 1, 7) = ? "
        params.append(target[:7])
    elif window == "last90":
        extra = " AND SUBSTR(DT, 1, 10) >= date(?, '-90 days') "
        params.append(target)

    sql = f"""
WITH daily AS (
  SELECT SUBSTR(DT, 1, 10) AS d, ROUND(SUM(NETAMT), 2) AS rev
  FROM AI_TEST_INVOICEBILLREGISTER
  WHERE LOCATION_NAME IN ({ph}) {extra}
  GROUP BY 1
),
ranked AS (
  SELECT d, rev,
         RANK() OVER (ORDER BY rev DESC) AS rank_desc,
         COUNT(*) OVER () AS total_days
  FROM daily
)
SELECT d, rev, rank_desc, total_days FROM ranked WHERE d = ?
""".strip()
    params.append(target)

    try:
        with sqlite_connection(base_dir) as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
    except Exception as exc:  # noqa: BLE001
        return {
            "queried_date": target,
            "error": str(exc),
            "premise_conflict": False,
            "rank_window": window,
        }

    if not row:
        return {
            "queried_date": target,
            "day_revenue": None,
            "rank": None,
            "total_days": None,
            "is_peak": False,
            "premise_conflict": False,
            "note": "No sales rows for this date in the ranked window.",
            "rank_window": window,
        }

    _d, rev, rank_desc, total_days = row
    rank_i = int(rank_desc) if rank_desc is not None else None
    n_days = int(total_days) if total_days is not None else None
    is_peak = rank_i == 1 if rank_i is not None else False
    conflict = rank_i is not None and rank_i <= _PREMISE_CONFLICT_MAX_RANK

    return {
        "queried_date": target,
        "day_revenue": float(rev) if rev is not None else None,
        "rank": rank_i,
        "total_days": n_days,
        "is_peak": is_peak,
        "premise_conflict": conflict,
        "rank_window": window,
    }
