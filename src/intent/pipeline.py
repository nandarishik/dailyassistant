"""
Match high-confidence natural-language patterns to fixed SELECT templates.

When `use_guarded_sql_pipeline` is enabled, the Copilot engine tries this path
before the full LLM planner. All SQL is validated by `sql_guard` and executed
via `guarded_execute` (parameterized where possible).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.copilot.data_scope import build_data_scope
from src.copilot.premise_check import compute_premise_check
from src.data.sidebar_bounds import load_outlet_date_bounds
from src.sql.guarded_execute import fetch_select_as_markdown, fetch_select_as_markdown_params

_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_DECLINE = re.compile(
    r"\b(drop|declin|worst|fell|fallen|underperform|slow\s+day|low\s+sales|"
    r"plummet|tank|slump|downturn|dip\b|down\s+vs|below\s+avg|below\s+average)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentMatch:
    name: str
    sql: str
    date_start: str
    date_end: str
    sql_params: tuple[Any, ...] = ()
    sql_b: str = ""
    sql_b_params: tuple[Any, ...] = ()


def _extract_dates(question: str) -> list[str]:
    found = _DATE_RE.findall(question)
    return sorted(set(found))


def _resolve_dates(question: str, base_dir: Path) -> tuple[str, str]:
    bounds = load_outlet_date_bounds(base_dir)
    lo, hi = bounds.min_date.isoformat(), bounds.max_date.isoformat()
    dates = _extract_dates(question)
    if len(dates) >= 2:
        return min(dates[0], dates[-1]), max(dates[0], dates[-1])
    if len(dates) == 1:
        return dates[0], dates[0]
    return lo, hi


def _outlet_placeholders(n: int) -> str:
    return ",".join("?" * n)


def _find_two_outlets(question: str, outlets: list[str]) -> tuple[str, str] | None:
    low = question.lower()
    hits: list[str] = []
    for o in outlets:
        if o.lower() in low:
            hits.append(o)
    hits = list(dict.fromkeys(hits))
    if len(hits) >= 2:
        return hits[0], hits[1]
    return None


def _try_match(question: str, base_dir: Path) -> IntentMatch | None:
    q = question.strip()
    if len(q) < 8:
        return None
    low = q.lower()
    ds, de = _resolve_dates(q, base_dir)
    bounds = load_outlet_date_bounds(base_dir)
    outlets = list(bounds.outlets)
    if not outlets:
        return None
    ph = _outlet_placeholders(len(outlets))
    dates = _extract_dates(q)

    # Compare two explicit ISO dates
    if len(dates) >= 2 and re.search(r"\b(compare|vs\.?|versus)\b", low):
        d1, d2 = dates[0], dates[-1]
        sql = f"""
SELECT SUBSTR(DT, 1, 10) AS day, IFNULL(ROUND(SUM(NETAMT), 2), 0) AS total_revenue,
       COUNT(DISTINCT TRNNO) AS orders
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) IN (?, ?)
GROUP BY SUBSTR(DT, 1, 10) ORDER BY day
""".strip()
        params = tuple(outlets) + (d1, d2)
        return IntentMatch("compare_two_dates", sql, d1, d2, sql_params=params)

    # Decline / drop on a single day (before generic single-day total)
    if len(dates) == 1 and _DECLINE.search(low):
        d = dates[0]
        sql_chain = f"""
SELECT ROUND(SUM(NETAMT), 0) AS total_revenue, COUNT(DISTINCT TRNNO) AS orders
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) = ?
""".strip()
        sql_outlet = f"""
SELECT LOCATION_NAME AS outlet_name, IFNULL(ROUND(SUM(NETAMT), 2), 0) AS revenue,
       COUNT(DISTINCT TRNNO) AS orders
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) = ?
GROUP BY LOCATION_NAME ORDER BY revenue DESC
""".strip()
        params_chain = tuple(outlets) + (d,)
        params_outlet = tuple(outlets) + (d,)
        return IntentMatch(
            "decline_on_date",
            sql_chain,
            d,
            d,
            sql_params=params_chain,
            sql_b=sql_outlet,
            sql_b_params=params_outlet,
        )

    # Compare two named outlets (same date window)
    pair = _find_two_outlets(q, outlets)
    if pair and re.search(r"\b(compare|vs\.?|versus)\b", low):
        a, b = pair
        sql = """
SELECT LOCATION_NAME AS outlet_name, IFNULL(ROUND(SUM(NETAMT), 2), 0) AS revenue,
       COUNT(DISTINCT TRNNO) AS orders
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN (?, ?) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
GROUP BY LOCATION_NAME ORDER BY revenue DESC
""".strip()
        params = (a, b, ds, de)
        return IntentMatch("outlet_comparison", sql, ds, de, sql_params=params)

    # Best / worst single day in range (or month)
    if re.search(r"\b(worst|lowest|weakest)\b.{0,40}\b(day|daily)\b|\b(lowest|worst)\s+sales\s+day\b", low):
        sql = f"""
SELECT SUBSTR(DT, 1, 10) AS day, IFNULL(ROUND(SUM(NETAMT), 2), 0) AS total_revenue
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
GROUP BY SUBSTR(DT, 1, 10) ORDER BY total_revenue ASC LIMIT 1
""".strip()
        return IntentMatch("best_worst_day", sql, ds, de, sql_params=tuple(outlets) + (ds, de))

    if re.search(r"\b(best|highest|strongest)\b.{0,40}\b(day|daily)\b|\b(best|highest)\s+sales\s+day\b", low):
        sql = f"""
SELECT SUBSTR(DT, 1, 10) AS day, IFNULL(ROUND(SUM(NETAMT), 2), 0) AS total_revenue
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
GROUP BY SUBSTR(DT, 1, 10) ORDER BY total_revenue DESC LIMIT 1
""".strip()
        return IntentMatch("best_worst_day", sql, ds, de, sql_params=tuple(outlets) + (ds, de))

    # Daily trend
    if re.search(r"\b(daily|day[- ]by[- ]day|each\s+day|trend)\b.{0,30}\b(revenue|sales)\b|\b(revenue|sales)\b.{0,30}\b(daily|trend)\b", low):
        sql = f"""
SELECT SUBSTR(DT, 1, 10) AS day, IFNULL(ROUND(SUM(NETAMT), 2), 0) AS revenue,
       COUNT(DISTINCT TRNNO) AS orders
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
GROUP BY SUBSTR(DT, 1, 10) ORDER BY day
""".strip()
        return IntentMatch("daily_trend", sql, ds, de, sql_params=tuple(outlets) + (ds, de))

    if (
        len(dates) == 1
        and re.search(r"\b(revenue|sales)\b", low)
        and re.search(
            r"\b(how much|what was|how much was|total|combined|entire chain|all outlets)\b",
            low,
        )
    ):
        d = dates[0]
        sql = f"""
SELECT ROUND(SUM(NETAMT),0) AS total_revenue,
       COUNT(DISTINCT TRNNO) AS orders
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) = ?
""".strip()
        return IntentMatch("single_day_chain_revenue", sql, d, d, sql_params=tuple(outlets) + (d,))

    if re.search(r"\b(top\s+\d+|top\s+items?|best\s+sell(?:ing|ers)?)\b", low) and not re.search(r"\b(per|by|each)\s+outlet\b", low):
        sql = f"""
SELECT PRODUCT_NAME AS item_name,
       IFNULL(ROUND(SUM(NET_AMT),2), 0) AS revenue,
       SUM(CAST(QTY AS REAL)) AS qty
FROM AI_TEST_TAXCHARGED_REPORT
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
  AND PRODUCT_NAME IS NOT NULL
GROUP BY PRODUCT_NAME ORDER BY revenue DESC LIMIT 5
""".strip()
        return IntentMatch("top_items", sql, ds, de, sql_params=tuple(outlets) + (ds, de))

    if re.search(
        r"\b(by|per|each)\s+outlet\b|\boutlet\b.{0,48}\b(revenue|sales|performance)\b|\b(revenue|sales)\b.{0,48}\boutlet\b",
        low,
    ) and not re.search(r"\b(product|item|selling|top|highest)\b", low):
        sql = f"""
SELECT LOCATION_NAME AS outlet_name, IFNULL(ROUND(SUM(NETAMT),2), 0) AS revenue,
       COUNT(DISTINCT TRNNO) AS orders
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
GROUP BY LOCATION_NAME ORDER BY revenue DESC
""".strip()
        return IntentMatch("revenue_by_outlet", sql, ds, de, sql_params=tuple(outlets) + (ds, de))

    if re.search(
        r"\b(total|overall|chain|aggregate)\b.{0,40}\b(revenue|sales|net)\b|\b(revenue|sales)\b.{0,40}\b(total|overall|chain)\b",
        low,
    ) and not re.search(r"\b(product|item|selling|top|highest|by outlet|per outlet)\b", low):
        sql = f"""
SELECT IFNULL(ROUND(SUM(NETAMT),2), 0) AS total_revenue,
       COUNT(DISTINCT TRNNO) AS total_orders,
       IFNULL(ROUND(SUM(NETAMT)/NULLIF(COUNT(DISTINCT TRNNO),0),2), 0) AS aov
FROM AI_TEST_INVOICEBILLREGISTER
WHERE LOCATION_NAME IN ({ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
""".strip()
        return IntentMatch("total_revenue", sql, ds, de, sql_params=tuple(outlets) + (ds, de))

    return None


def _run_intent_sql(base_dir: Path, m: IntentMatch) -> str:
    if m.name == "decline_on_date" and m.sql_b:
        a = fetch_select_as_markdown_params(base_dir, m.sql, m.sql_params)
        b = fetch_select_as_markdown_params(base_dir, m.sql_b, m.sql_b_params)
        return a + "\n\n### Per-outlet breakdown\n\n" + b
    if m.sql_params:
        return fetch_select_as_markdown_params(base_dir, m.sql, m.sql_params)
    return fetch_select_as_markdown(base_dir, m.sql)


def try_guarded_intent_run(question: str, base_dir: Path) -> dict[str, Any] | None:
    """
    If the question matches a supported intent, run guarded SQL and return a
    Copilot-shaped dict; otherwise return None.
    """
    m = _try_match(question, base_dir)
    if m is None:
        return None

    md = _run_intent_sql(base_dir, m)
    if md.startswith("ERROR:") or md.startswith("SQL Error:"):
        return {
            "question": question,
            "tool_calls": [
                {
                    "tool": "query_sales_db",
                    "args": {"sql": m.sql[:500]},
                    "result": md,
                    "success": False,
                    "emoji": "⚠️",
                    "label": "Guarded SQL (intent)",
                }
            ],
            "response": md,
            "engine": "IntentSQL",
            "model": "template-v1",
            "error": md,
            "monologue": [
                f"📌 Matched intent `{m.name}` for {m.date_start} → {m.date_end}.",
                "⚠️ Query did not complete cleanly — see tool result.",
            ],
            "evidence": {
                "intent": m.name,
                "date_start": m.date_start,
                "date_end": m.date_end,
                "sql_sha256": hashlib.sha256(m.sql.encode()).hexdigest()[:16],
            },
        }

    premise = compute_premise_check(question, base_dir) if m.name == "decline_on_date" else None
    ev: dict[str, Any] = {
        "intent": m.name,
        "date_start": m.date_start,
        "date_end": m.date_end,
        "sql_sha256": hashlib.sha256(m.sql.encode()).hexdigest()[:16],
        "premise": "template_sql",
        "data_scope": build_data_scope(
            base_dir, question=question, tool_names=["query_sales_db"]
        ),
    }
    if premise:
        ev["premise_check"] = premise
        if premise.get("premise_conflict"):
            ev["guardrail_flags"] = ["premise_conflict"]

    return {
        "question": question,
        "tool_calls": [
            {
                "tool": "query_sales_db",
                "args": {"sql": m.sql[:800]},
                "result": md,
                "success": True,
                "emoji": "📊",
                "label": "Guarded SQL (intent)",
            }
        ],
        "response": (
            f"**Intent match:** `{m.name}` ({m.date_start} → {m.date_end}).\n\n"
            f"{md}\n\n"
            "_Generated from a fixed template (no LLM SQL synthesis)._"
        ),
        "engine": "IntentSQL",
        "model": "template-v1",
        "error": "",
        "monologue": [
            f"📌 Matched intent `{m.name}` for {m.date_start} → {m.date_end}.",
            "🔧 Executed guarded SELECT against the sales warehouse.",
        ],
        "evidence": ev,
    }
