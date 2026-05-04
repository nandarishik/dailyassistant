"""Evidence payload: what the warehouse can show vs gaps, plus DB freshness."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.data.access.db import sqlite_connection
from src.data.sidebar_bounds import load_outlet_date_bounds

_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

_NOT_IN_DB = [
    "unit_cost",
    "gross_margin",
    "foot_traffic",
    "marketing_spend",
    "staff_hours",
    "inventory_levels",
]


def build_data_scope(
    base_dir: Path,
    *,
    question: str,
    tool_names: list[str],
) -> dict[str, Any]:
    """Static scope + freshness; does not parse every SQL variant."""
    bounds = load_outlet_date_bounds(base_dir)
    dates = sorted(set(_DATE_RE.findall(question)))
    date_start = dates[0] if dates else bounds.min_date.isoformat()
    date_end = dates[-1] if dates else bounds.max_date.isoformat()
    if len(dates) >= 2:
        date_start, date_end = min(dates[0], dates[-1]), max(dates[0], dates[-1])

    max_invoice_date: str | None = None
    try:
        with sqlite_connection(base_dir) as conn:
            row = conn.execute(
                "SELECT SUBSTR(MAX(INVOICE_DATE), 1, 10) FROM VIEW_AI_SALES"
            ).fetchone()
            if row and row[0]:
                max_invoice_date = str(row[0])
    except Exception:  # noqa: BLE001
        max_invoice_date = bounds.max_date.isoformat()

    tables_hint: list[str] = []
    if any(t == "query_sales_db" for t in tool_names):
        tables_hint.append("VIEW_AI_SALES (DMS secondary sales)")
    if any(t in ("get_holiday_status", "get_news_context") for t in tool_names):
        tables_hint.append("context_intelligence (external context tools)")

    return {
        "date_window_interpreted": {"date_start": date_start, "date_end": date_end},
        "outlet_count": len(bounds.outlets),
        "max_invoice_date": max_invoice_date,
        "tables_hint": tables_hint or ["none inferred from tool list"],
        "columns_available_summary": [
            "line-item revenue (NET_AMT)",
            "invoices (INVOICE_NO)",
            "products/SKUs (PRODUCT, PRODUCT_CLASS, CODE)",
            "territory (STATE, ZONE, TOWN)",
            "distribution (STOCKIEST, ISR, CUSTOMER)",
            "volume (QTY_CASES, QTY_PACKS, TOTAL_VOLUME_BILLED_LTR)",
        ],
        "not_in_this_database": [
            "unit_cost", "gross_margin", "foot_traffic",
            "marketing_spend", "staff_hours", "inventory_levels",
            "return_data", "secondary_schemes",
        ],
    }
