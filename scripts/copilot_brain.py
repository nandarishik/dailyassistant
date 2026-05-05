"""
QAFFEINE Copilot  —  Agentic Intelligence Layer
================================================
Exposes:
  - CopilotAgent          : multi-tool agentic reasoning loop
  - generate_proactive_brief() : autonomous morning brief (anomaly + combo + risk)
  - generate_anomaly_diagnosis() : per-anomaly LLM root-cause narrative

Architecture — "Plan → Execute → Synthesise":
  1. LLM decides which tools are needed (JSON plan)
  2. Tools run locally in Python  — DB-backed first, live API as fallback
  3. LLM synthesises results into a senior-level business response

Context Retrieval Priority (hardened):
  news / weather / holiday  →  context_intelligence table (pre-analysed)
                            →  live API call only when DB row is absent
"""

import datetime
import json
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field
from src.config.env import load_app_dotenv
from src.config.settings import get_settings
from src.copilot.causal_postcheck import apply_causal_postcheck
from src.copilot.data_scope import build_data_scope
from src.copilot.numeric_digest import digest_markdown_tables
from src.copilot.numeric_postcheck import apply_numeric_postcheck
from src.copilot.planner_parse import parse_planner_tool_plan
from src.copilot.premise_check import compute_premise_check, implies_decline_premise
from src.copilot.query_context import build_resolved_query_context
from src.copilot.trace import append_copilot_trace
from src.data.access.db import sqlite_connection
from src.data.sidebar_bounds import load_outlet_date_bounds
from src.sql.guarded_execute import fetch_select_as_markdown

# ── Paths & env ───────────────────────────────────────────────────────────────
BASE     = Path(__file__).resolve().parent.parent
load_app_dotenv(BASE)

# ── Re-use existing modules ───────────────────────────────────────────────────
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from universal_context import (  # noqa: E402
    LLMManager,
    get_holiday_info,
    get_news_headlines,
    get_weather_context,
)

try:
    from forecaster import simulate_scenario as _simulate_scenario_fn
    _FORECASTER_AVAILABLE = True
except ImportError:
    _FORECASTER_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS  — each returns a plain string summary
# Context priority: DB (context_intelligence table) → live API fallback
# ══════════════════════════════════════════════════════════════════════════════

def _tool_query_sales_db(sql: str) -> str:
    """Run a SELECT against AI_DATABASE.DB and return results as a markdown table."""
    return fetch_select_as_markdown(BASE, sql)


def _fetch_context_row(date: str) -> dict | None:
    """
    Retrieve a pre-analysed context row from context_intelligence for the given date.
    Returns None if the table doesn't exist or the date has no row.
    """
    try:
        with sqlite_connection(BASE) as conn:
            cur = conn.execute(
                """
                SELECT is_holiday, holiday_name, holiday_type,
                       temp_max_c, precipitation_mm, weather_condition,
                       news_headlines, news_disruptors
                FROM   context_intelligence
                WHERE  date = ?
                """,
                (date,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        cols = [
            "is_holiday", "holiday_name", "holiday_type",
            "temp_max_c", "precipitation_mm", "weather_condition",
            "news_headlines", "news_disruptors",
        ]
        return dict(zip(cols, row))
    except Exception:
        return None


def _tool_get_weather_context(date: str) -> str:
    """
    Return weather for Hyderabad on the given date.
    Priority: context_intelligence DB row → WeatherAPI live call.
    """
    try:
        date_obj = datetime.date.fromisoformat(date)
    except ValueError:
        return f"Invalid date: {date!r}. Use YYYY-MM-DD."

    # ── DB-first lookup ──────────────────────────────────────────────────────
    ctx = _fetch_context_row(date)
    if ctx and ctx.get("weather_condition") and "Unavailable" not in (ctx["weather_condition"] or ""):
        return (
            f"Weather for Hyderabad on {date}: "
            f"Avg temp={ctx.get('temp_max_c', 'N/A')}°C, "
            f"Precipitation={ctx.get('precipitation_mm', 'N/A')}mm, "
            f"Condition={ctx['weather_condition']}  [Source: context_intelligence DB]"
        )

    # ── Live API fallback ────────────────────────────────────────────────────
    w = get_weather_context(date_obj)
    return (
        f"Weather for Hyderabad on {date}: "
        f"Avg temp={w.get('temp_max_c', 'N/A')}°C, "
        f"Precipitation={w.get('precipitation_mm', 'N/A')}mm, "
        f"Condition={w.get('weather_condition', 'N/A')}, "
        f"Source={w.get('source', 'N/A')}"
        + (f", API error={w.get('api_error_msg', '')}" if w.get("api_error_code") else "")
    )


def _tool_get_holiday_status(date: str) -> str:
    """
    Check Telangana/National holiday status for a date.
    Priority: context_intelligence DB row → local holidays library.
    """
    try:
        date_obj = datetime.date.fromisoformat(date)
    except ValueError:
        return f"Invalid date: {date!r}. Use YYYY-MM-DD."

    # ── DB-first lookup ──────────────────────────────────────────────────────
    ctx = _fetch_context_row(date)
    if ctx is not None:
        if ctx.get("is_holiday"):
            name = ctx.get("holiday_name") or "Holiday"
            htype = ctx.get("holiday_type") or "Public"
            return f"{date} is a {htype} holiday: {name}  [Source: context_intelligence DB]"
        return f"{date} is a regular trading day (no public holiday in Telangana/India).  [Source: context_intelligence DB]"

    # ── Local library fallback ───────────────────────────────────────────────
    h = get_holiday_info(date_obj)
    if h["is_holiday"]:
        return f"{date} is a {h['holiday_type']} holiday: {h['holiday_name']}"
    return f"{date} is a regular trading day (no public holiday in Telangana/India)."


def _tool_get_news_context(date: str) -> str:
    """
    Return enriched market signals / disruptors for the given date.
    Priority: context_intelligence.news_disruptors (LLM-analysed) → raw live headlines.
    """
    try:
        date_obj = datetime.date.fromisoformat(date)
    except ValueError:
        return f"Invalid date: {date!r}. Use YYYY-MM-DD."

    # ── DB-first: prefer pre-analysed LLM summary ────────────────────────────
    ctx = _fetch_context_row(date)
    if ctx:
        disruptors = (ctx.get("news_disruptors") or "").strip()
        headlines_json = ctx.get("news_headlines") or "[]"
        try:
            headlines = json.loads(headlines_json)
        except (json.JSONDecodeError, TypeError):
            headlines = []

        if disruptors and "No headlines" not in disruptors and "skipped" not in disruptors.lower():
            head_block = ""
            if headlines:
                head_block = "\n\nSource Headlines:\n" + "\n".join(
                    f"  {i}. {h[:100]}" for i, h in enumerate(headlines[:6], 1)
                )
            return (
                f"Market Intelligence for {date}  [Source: context_intelligence DB – LLM-analysed]\n\n"
                f"{disruptors}"
                f"{head_block}"
            )

        if headlines:
            lines = [f"Headlines for {date}  [Source: context_intelligence DB – raw]:"]
            for i, h in enumerate(headlines[:8], 1):
                lines.append(f"  {i}. {h[:100]}")
            return "\n".join(lines)

    # ── Live API fallback ────────────────────────────────────────────────────
    headlines = get_news_headlines(date_obj)
    if not headlines:
        return "No headlines retrieved."
    lines = [f"Headlines for {date}  [Source: live NewsAPI/RSS]:"]
    for i, h in enumerate(headlines[:8], 1):
        lines.append(f"  {i}. {h[:100]}")
    return "\n".join(lines)


def _tool_get_combo_recommendations() -> str:
    """Return top Power Combos from the latest basket_results.json."""
    json_path = BASE / "database" / "basket_results.json"
    if not json_path.exists():
        return "No basket analysis data. Run scripts/basket_analysis.py first."
    try:
        data   = json.loads(json_path.read_text(encoding="utf-8"))
        combos = data.get("power_combos", [])[:5]
        if not combos:
            return "No power combos computed yet."
        lines = ["Top Power Combo Recommendations (from Market Basket Analysis):"]
        for i, c in enumerate(combos, 1):
            lines.append(
                f"  #{i} {c['item_a'][:28]} + {c['item_b'][:28]}  "
                f"Lift={c['lift']:.1f}x  Co-purchased {c['co_count']}×  "
                f"Bundle=₹{c['bundle_price']:.0f}  AOV lift +{c['aov_lift_pct']:.1f}%"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Combo load error: {exc}"


def _tool_analyze_product_mix(
    outlet_filter: str = "",
    date_from:     str = "",
    date_to:       str = "",
    group_filter:  str = "",
    top_n:         int = 8,
) -> str:
    """
    Compute Market Basket Analysis live from fact_sales for any custom filter.
    Returns top co-purchased pairs with Lift, Confidence, quadrant labels,
    and suggested bundle pricing.  All filter args are optional strings.
    """
    clauses: list[str] = []
    params:  list      = []

    if outlet_filter.strip():
        clauses.append("ZONE = ?")
        params.append(outlet_filter.strip())
    if date_from.strip():
        clauses.append("SUBSTR(INVOICE_DATE, 1, 10) >= ?")
        params.append(date_from.strip())
    if date_to.strip():
        clauses.append("SUBSTR(INVOICE_DATE, 1, 10) <= ?")
        params.append(date_to.strip())
    if group_filter.strip():
        clauses.append("(PRODUCT_CLASS LIKE ? OR PRODUCT LIKE ?)")
        like = f"%{group_filter.strip()}%"
        params.extend([like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = f"""
        SELECT INVOICE_NO AS bill_no, PRODUCT AS item_name,
               SUM(NET_AMT) AS rev,
               SUM(QTY_PACKS) AS qty
        FROM   VIEW_AI_SALES
        {where}
        GROUP  BY INVOICE_NO, PRODUCT
    """
    try:
        with sqlite_connection(BASE) as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception as exc:
        return f"Live basket DB error: {exc}"

    if not rows:
        return "No transactions matched the specified filters."

    baskets: dict[str, set]        = {}
    item_rev: dict[str, float]     = {}
    item_qty: dict[str, float]     = {}
    items_in_bills: dict[str, int] = {}

    for bill_no, item, rev, qty in rows:
        baskets.setdefault(bill_no, set()).add(item)
        item_rev[item] = item_rev.get(item, 0.0) + (rev or 0)
        item_qty[item] = item_qty.get(item, 0.0) + (qty or 0)

    for bill_items in baskets.values():
        for item in bill_items:
            items_in_bills[item] = items_in_bills.get(item, 0) + 1

    total_bills = len(baskets)
    multi_bills = sum(1 for b in baskets.values() if len(b) > 1)

    if total_bills < 2:
        return "Not enough transactions to compute basket analysis."

    from itertools import combinations
    pair_count: dict[tuple, int] = {}
    for bill_items in baskets.values():
        for a, b in combinations(sorted(bill_items), 2):
            pair_count[(a, b)] = pair_count.get((a, b), 0) + 1

    if not pair_count:
        return (
            f"Found {total_bills} bills, but none had 2+ distinct items "
            "(basket analysis requires multi-item transactions)."
        )

    pairs_scored: list[dict] = []
    for (a, b), co_cnt in pair_count.items():
        if item_qty.get(a, 0) < 2 or item_qty.get(b, 0) < 2:
            continue
        sup_a  = items_in_bills.get(a, 1) / total_bills
        sup_b  = items_in_bills.get(b, 1) / total_bills
        sup_ab = co_cnt / total_bills
        conf   = sup_ab / sup_a if sup_a else 0
        lift   = conf / sup_b   if sup_b else 0
        avg_a  = item_rev.get(a, 0) / max(item_qty.get(a, 1), 1)
        avg_b  = item_rev.get(b, 0) / max(item_qty.get(b, 1), 1)
        if avg_a < 10 or avg_b < 10:
            continue
        pairs_scored.append({
            "a": a, "b": b, "co": co_cnt,
            "lift": round(lift, 2),
            "support": round(sup_ab * 100, 2),
            "conf": round(conf * 100, 1),
            "avg_a": round(avg_a, 0),
            "avg_b": round(avg_b, 0),
        })

    pairs_scored.sort(key=lambda x: x["lift"], reverse=True)
    top_pairs = pairs_scored[:top_n]

    qtys  = sorted(item_qty.values())
    revs  = sorted(item_rev.values())
    med_qty = qtys[len(qtys) // 2] if qtys else 1
    med_rev = revs[len(revs) // 2] if revs else 1

    def _quad(item: str) -> str:
        q, r = item_qty.get(item, 0), item_rev.get(item, 0)
        if q >= med_qty and r >= med_rev:  return "⭐ Star"
        if q <  med_qty and r >= med_rev:  return "🔮 Puzzle"
        if q >= med_qty and r <  med_rev:  return "🐴 Plowhorse"
        return "🐕 Dog"

    filter_desc_parts = []
    if outlet_filter: filter_desc_parts.append(f"Outlet: {outlet_filter}")
    if date_from:     filter_desc_parts.append(f"From: {date_from}")
    if date_to:       filter_desc_parts.append(f"To: {date_to}")
    if group_filter:  filter_desc_parts.append(f"Group: {group_filter}")
    filter_desc = " | ".join(filter_desc_parts) or "All data"

    lines = [
        f"Live Market Basket Analysis  [{filter_desc}]",
        f"  Transactions: {total_bills} bills  |  Multi-item: {multi_bills} "
        f"({multi_bills/total_bills*100:.0f}%)  |  Unique items: {len(item_qty)}",
        "",
        f"  Top {len(top_pairs)} Co-purchased Pairs (by Lift):",
    ]
    for i, p in enumerate(top_pairs, 1):
        qa, qb  = _quad(p["a"]), _quad(p["b"])
        bundle  = round((p["avg_a"] + p["avg_b"]) * 0.85)
        lines.append(
            f"  #{i}  {p['a'][:30]} ({qa})"
            f"  +  {p['b'][:30]} ({qb})"
        )
        lines.append(
            f"       Lift={p['lift']:.2f}x  Co-purchased {p['co']}x"
            f"  Support={p['support']:.1f}%  Confidence={p['conf']:.0f}%"
        )
        lines.append(
            f"       Individual: ₹{p['avg_a']:.0f} + ₹{p['avg_b']:.0f}  "
            f"→  Bundle @ 15% off: ₹{bundle}"
        )
        lines.append("")

    return "\n".join(lines)


def _tool_simulate_scenario(
    outlet:  str = "QAFFEINE HITECH CITY",
    date:    str = "",
    rain_mm: str = "0",
    temp_c:  str = "28",
) -> str:
    """Run the ML revenue forecaster for a what-if scenario."""
    if not _FORECASTER_AVAILABLE:
        return "Forecaster not available. Run `python scripts/forecaster.py` to train the model first."
    try:
        if not date:
            date = datetime.date.today().strftime("%Y-%m-%d")
        return _simulate_scenario_fn(
            outlet=outlet,
            date=date,
            rain_mm=float(rain_mm),
            temp_c=float(temp_c),
        )
    except Exception as exc:
        return f"Simulation error: {exc}"


# ── Tool Registry ──────────────────────────────────────────────────────────────
TOOL_REGISTRY: dict[str, dict] = {
    "query_sales_db": {
        "fn"         : _tool_query_sales_db,
        "description": "Run a SQLite SELECT on the DMS sales database. Arg: sql (string).",
        "args"       : ["sql"],
        "emoji"      : "🗄️",
        "label"      : "Querying sales database",
    },
    "get_holiday_status": {
        "fn"         : _tool_get_holiday_status,
        "description": (
            "Check if a date is a India National/State holiday. "
            "Reads from context_intelligence DB first; falls back to local library. "
            "Arg: date (YYYY-MM-DD)."
        ),
        "args"       : ["date"],
        "emoji"      : "📅",
        "label"      : "Checking regional holiday calendar",
    },
    "get_news_context": {
        "fn"         : _tool_get_news_context,
        "description": (
            "Get enriched market signals & disruptors for a date. "
            "Returns the pre-analysed LLM market intelligence from context_intelligence DB "
            "(includes sentiment, disruptors, and positive signals). "
            "Falls back to raw live headlines only if no DB row exists. "
            "Arg: date (YYYY-MM-DD)."
        ),
        "args"       : ["date"],
        "emoji"      : "📰",
        "label"      : "Scanning market intelligence signals",
    },
    "analyze_product_mix": {
        "fn"         : _tool_analyze_product_mix,
        "description": (
            "Compute Product Mix and Cross-sell Analysis live from the DB for a custom scope. "
            "Args (all optional strings/int): "
            "outlet_filter (e.g. 'East Zone'), "
            "date_from (YYYY-MM-DD), date_to (YYYY-MM-DD), "
            "group_filter (e.g. 'Hair Oil', 'Toothpowder'), "
            "top_n (int, default 8). "
            "Returns live co-purchase pairs with Lift, Confidence, and quadrant labels. "
            "Use this whenever the user asks about product bundles, mix, or what sells together."
        ),
        "args"       : ["outlet_filter", "date_from", "date_to", "group_filter", "top_n"],
        "emoji"      : "🧮",
        "label"      : "Computing product mix analysis",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

DB_SCHEMA_BRIEF = """
SQLite database: AI_DMS_database.db

TABLE: VIEW_AI_SALES (FMCG distributor secondary sales — 1 row per invoice line item / SKU)

  -- Geography & Territory --
  STATE              VARCHAR(50)    (e.g. 'UTTAR PRADESH', 'RAJASTHAN', 'BIHAR')
  ZONE               VARCHAR(50)    (e.g. 'East Zone', 'Central Zone', 'North Zone 2', 'West Zone', 'North Zone 1', 'South Zone')
  TOWN               VARCHAR(50)    (e.g. 'Jaipur', 'Badnawar', 'Patna')

  -- Sales Hierarchy --
  ZONAL_HEAD         VARCHAR(50)    (top-level sales leader)
  SALES_MANAGER      VARCHAR(50)    (regional sales manager)
  AREA_SALES_MANAGER VARCHAR(50)    (area-level manager)
  SALES_OFFICER      VARCHAR(50)    (field-level officer)

  -- Distribution --
  STOCKIEST          VARCHAR(100)   (Super Stockist / distributor name)
  STOCKIEST_CODE     NUMERIC(10)
  ISR                VARCHAR(100)   (In-Store Representative name)
  ISR_CATEGORY       VARCHAR(25)    ('REGULAR ISR', 'VSR', 'HIPO ISR', etc.)
  BEAT               VARCHAR(50)    (sales route)
  CHANNEL            VARCHAR(50)    (always 'Sub Stockiest' in this dataset)

  -- Customer --
  CUSTOMER_CODE      NUMERIC(10)    (unique retailer ID)
  CUSTOMER           VARCHAR(100)   (retailer/sub-stockist name)
  CUSTOMER_CATEGORY  VARCHAR(25)    ('Base Sub', 'Exclusive Van', 'Counter Sub')

  -- Product --
  PRODUCT            VARCHAR(100)   (full SKU name, e.g. 'ADHO 45ML+10% EXTRA...')
  CLUB_SKU           VARCHAR(25)    (grouping of similar SKUs)
  PRODUCT_CLASS      VARCHAR(25)    (top category: 'Hair Oil', 'CNO', 'CNO Gold Blue', 'Toothpowder', etc.)
  PRODUCT_SUBCLASS   VARCHAR(25)    (sub-category: 'Light hair oil', 'Amla Oil', 'CNO', etc.)
  CODE               VARCHAR(25)    (brand short-code: 'ADHO', 'AHO', 'CNO', 'BTP', 'BGJ', etc.)
  PRODUCT_TYPE       VARCHAR(25)    ('OFFER' or 'Plain')
  PRODUCT_MRP        NUMERIC(10,2)  (Maximum Retail Price)
  MSS_TAGGING        VARCHAR(25)    ('MustSell' or NULL)

  -- Invoice --
  INVOICE_NO         VARCHAR(25)    (unique invoice identifier — use COUNT(DISTINCT INVOICE_NO) for invoice counts)
  INVOICE_DATE       DATETIME       (format: YYYY-MM-DD)

  -- Financials (per line item) --
  QTY_CASES          NUMERIC(10,2)  (quantity in cases)
  QTY_PACKS          NUMERIC(10,2)  (quantity in individual packs)
  GROSS_AMT          NUMERIC(12,2)  (gross amount before discounts)
  TAXABLE_AMT        NUMERIC(12,2)  (taxable amount after discounts)
  NET_AMT            NUMERIC(12,2)  (** ALWAYS use SUM(NET_AMT) for revenue totals! **)
  SCHEME_AMT         NUMERIC(10,2)  (scheme/promotional discount amount)
  CD_AMT             NUMERIC(10,2)  (cash discount amount)
  TOTAL_VOLUME_BILLED_LTR NUMERIC(14,2) (volume billed in litres)

CRITICAL SQL RULES:
  1. ALWAYS use SUM(NET_AMT) for revenue totals. Never use bare NET_AMT as a total.
  2. ALWAYS use SUBSTR(INVOICE_DATE, 1, 10) for date grouping/filtering.
  3. For 'revenue on date X' → show breakdown by STATE or ZONE.
  4. Use COUNT(DISTINCT INVOICE_NO) for invoice/order counts.
  5. VIEW_AI_SALES is the ONLY data table. There are no other tables.
  6. For territory analysis: GROUP BY STATE, ZONE, TOWN, or AREA_SALES_MANAGER.
  7. For product analysis: GROUP BY PRODUCT_CLASS, CODE, or PRODUCT.
  8. For distribution analysis: GROUP BY STOCKIEST, ISR, or CUSTOMER.
  9. Current dataset covers January 2026 only.
""".strip()

COPILOT_SYSTEM_PROMPT = f"""
You are the DMS Copilot — an elite AI business strategist for an FMCG distributor management system, analyzing secondary sales data for Bajaj Consumer Care (personal care products: hair oils, coconut oils, etc.).

Priority order (when instructions conflict, follow the lower number first):
1) **Numerical truth** — VERIFIED_NUMERIC_FACTS, PREMISE_CHECK, and tool tables override tone and user wording.
2) **Premise correction** — If PREMISE_CHECK shows `premise_conflict: true`, your **first sentence** must state that the day was **not** a trough in the ranked window (cite rank / total_days from PREMISE_CHECK).
3) **Honest limits** — DATA_SCOPE and missing tools: say what the warehouse cannot show.
4) **Personality** — strategic, direct voice only after (1)–(3) are satisfied.

Non-negotiables:
- **No causal leaps:** holidays and news are **context**, not proven causes of revenue unless a tool explicitly links them.
- **Comparisons need two numbers:** do not say "below/above average" or "dropped vs" unless both figures appear in tool results or VERIFIED_NUMERIC_FACTS.

Personality:
- You have the strategic depth of a McKinsey partner and the directness of a growth-stage founder.
- Prefer saying what the data **does** and **does not** show over bluffing when tools are incomplete.
- You proactively cross-reference holidays, commercial events, product mix data, and sales trends **when relevant**.
- You show findings as senior-level business insights with specific numbers, not vague summaries.

Tools available (call by returning JSON):
{json.dumps({k: v["description"] for k, v in TOOL_REGISTRY.items()}, indent=2)}

Sales DB Knowledge:
{DB_SCHEMA_BRIEF}

Routing Rules:
- Revenue anomaly / drop question → query_sales_db (total + per-zone) AND get_holiday_status AND get_news_context
- Specific date question → holiday + news for that date
- Basket / affinity / 'what sells together' for a specific zone or date → analyze_product_mix
- analyze_product_mix + query_sales_db can be combined freely in the same turn

Monthly/Seasonal Logic:
- If asked about a month (e.g. 'March'), use SUBSTR(INVOICE_DATE, 1, 7) = '2026-03'.
- January=01, February=02, March=03, April=04, May=05, June=06, July=07, August=08, September=09, October=10, November=11, December=12.
- Current Dataset Year is 2026.
""".strip()

PLANNER_PROMPT_TMPL = """
{system}

=== USER QUERY ===
{query}

=== YOUR TASK ===
Decide which tools to call. Return ONLY valid JSON array — no prose, no explanation, no markdown fences.

SQL WRITING RULES (read before writing any SQL):
- ALWAYS wrap revenue with SUM(): e.g. SUM(NET_AMT) — never use bare columns as a total.
- Use IFNULL(SUM(NET_AMT), 0) to prevent empty crashes.
- Never use 'date' column, use SUBSTR(INVOICE_DATE, 1, 10).
- SQLITE DIALECT: SQLite does NOT have `DAYOFWEEK()`. Use `STRFTIME('%w', INVOICE_DATE)` (0=Sunday, 6=Saturday).
- Use `COUNT(DISTINCT INVOICE_NO)` for unique invoice counts (never count bare rows).
- Always use `AVG(...)` in SQL for averages. DO NOT do math in your head later.
- `context_intelligence` is NOT a database table. Use the `get_holiday_status` tool for holidays.
- IMPORTANT: If asking about a specific zone, make sure the week average query HAS the same `WHERE ZONE='...'` filter inside the subquery so you don't compare a single zone to the entire company total!
- VIEW_AI_SALES is the ONLY table. Use it for all queries.
- Always alias with AS, always name columns explicitly.
- CASE INSENSITIVITY: SQLite string matching is case-sensitive! Always use UPPER(column) = UPPER('value') or LIKE '%value%' when filtering string columns like ISR, ZONE, STOCKIEST, PRODUCT, BEAT.

Example for 'revenue on date X' (by state):
  {{"tool": "query_sales_db", "args": {{"sql": "SELECT STATE, ROUND(SUM(NET_AMT),0) AS revenue FROM VIEW_AI_SALES WHERE SUBSTR(INVOICE_DATE, 1, 10)='2026-01-01' GROUP BY STATE ORDER BY revenue DESC"}}}}

Example for 'total company revenue on date X' (single scalar — use when user asks total / all zones / company sum):
  {{"tool": "query_sales_db", "args": {{"sql": "SELECT ROUND(SUM(NET_AMT),0) AS total_revenue FROM VIEW_AI_SALES WHERE SUBSTR(INVOICE_DATE, 1, 10)='2026-02-14'"}}}}

Example for 'lowest sales in March':
  {{"tool": "query_sales_db", "args": {{"sql": "SELECT SUBSTR(INVOICE_DATE, 1, 10) AS date, ROUND(SUM(NET_AMT),0) AS total_revenue FROM VIEW_AI_SALES WHERE SUBSTR(INVOICE_DATE, 1, 7)='2026-03' GROUP BY date ORDER BY total_revenue ASC LIMIT 1"}}}}

- IMPORTANT: To calculate averages of totals (e.g. average daily sales per day-of-week), you MUST use a CTE or Subquery to aggregate by day first, then calculate the average in the outer query (never nest AVG(SUM(...))).

Example for 'average daily sales per day of week':
  {{"tool": "query_sales_db", "args": {{"sql": "WITH DailyTotal AS (SELECT SUBSTR(INVOICE_DATE, 1, 10) AS date_only, SUM(NET_AMT) AS total FROM VIEW_AI_SALES GROUP BY date_only) SELECT CASE STRFTIME('%w', date_only) WHEN '0' THEN 'Sunday' WHEN '1' THEN 'Monday' WHEN '2' THEN 'Tuesday' WHEN '3' THEN 'Wednesday' WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday' WHEN '6' THEN 'Saturday' END AS day_of_week, ROUND(AVG(total),0) AS avg_daily_revenue FROM DailyTotal GROUP BY day_of_week ORDER BY avg_daily_revenue DESC"}}}}

Example for 'top selling item per zone':
  {{"tool": "query_sales_db", "args": {{"sql": "WITH Ranked AS (SELECT ZONE, PRODUCT, SUM(NET_AMT) AS revenue, ROW_NUMBER() OVER(PARTITION BY ZONE ORDER BY SUM(NET_AMT) DESC) as rn FROM VIEW_AI_SALES GROUP BY ZONE, PRODUCT) SELECT ZONE, PRODUCT, ROUND(revenue, 0) AS revenue FROM Ranked WHERE rn = 1 ORDER BY revenue DESC"}}}}

**Comparison rule —** user implies a **drop / decline / worst day** and the query contains **one** ISO date (YYYY-MM-DD):
- Include **at least two** `query_sales_db` steps: revenue **for that date** (company or per-zone) **and** a **baseline across other days** (e.g. `GROUP BY SUBSTR(INVOICE_DATE,1,10)` … `ORDER BY total_revenue DESC LIMIT 6`, or a trailing 7-day average for the same zone filter).
- Add `get_holiday_status`, and optionally `get_news_context` for that date.

Example JSON for "why revenue dropped on 2026-01-01" (shape only — adjust SQL to the schema):
  [
    {{"tool": "query_sales_db", "args": {{"sql": "SELECT ROUND(SUM(NET_AMT),0) AS total_revenue FROM VIEW_AI_SALES WHERE SUBSTR(INVOICE_DATE, 1, 10)='2026-01-01'"}}}},
    {{"tool": "query_sales_db", "args": {{"sql": "SELECT SUBSTR(INVOICE_DATE, 1, 10) AS day, ROUND(SUM(NET_AMT),0) AS total_revenue FROM VIEW_AI_SALES GROUP BY day ORDER BY total_revenue DESC LIMIT 6"}}}},
    {{"tool": "get_holiday_status", "args": {{"date": "2026-01-01"}}}}
  ]

Available tools: {tools}
If no tools are needed, return: []
"""

SYNTHESIS_PROMPT_TMPL = """
{system}

=== USER QUERY ===
{query}

=== TOOL RESULTS ===
{tool_results}

=== VERIFIED_NUMERIC_FACTS ===
{verified_block}

{strict_mode_addon}

=== YOUR TASK ===
You are a Senior Business Analyst talking to the Regional Sales Head of Bajaj Consumer Care.

STRICT RULES:
1. NO TECHNICAL JARGON: Never mention "tools", "database", "data scope", "sql", "results", or "visibility". 
2. BE DIRECT: Answer the question as if you are the manager of the territory.
   - Good: "Hair Dye had zero net revenue this month — only 2 trial invoices were raised."
   - Bad: "Our data scope doesn't include Hair Dye..."
3. WEAVE CONTEXT: If tools provide news or holidays, ALWAYS weave them into your answer.
4. PRESERVE TABLES: If the owner asks for a ranking or list, show the table.
5. CONCISE: Be brief, but ALWAYS complete your thought and include the actual numbers requested.

Example:
Sales Head: "How is Toothpowder performing?"
You: "Bajaj Tooth Powder contributed ₹4.85L this month — 340 transactions across 14 states, representing just 0.14% of total secondary sales."

Keep it crisp, professional, and business-focused.
"""




# ══════════════════════════════════════════════════════════════════════════════
# COPILOT AGENT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ToolCall:
    tool    : str
    args    : dict
    result  : str  = ""
    success : bool = True
    emoji   : str  = "🔧"
    label   : str  = ""


@dataclass
class CopilotResult:
    query      : str
    tool_calls : list[ToolCall] = field(default_factory=list)
    response   : str            = ""
    engine     : str            = "none"
    model      : str            = "none"
    error      : str            = ""
    monologue  : list[str]      = field(default_factory=list)
    evidence   : dict           = field(default_factory=dict)


def _augment_plan_for_decline_single_date(query: str, calls: list[ToolCall]) -> list[ToolCall]:
    """
    When the user implies a decline and names one ISO date, append a top-days SQL
    call if the planner did not already supply an ORDER BY total_revenue DESC baseline.
    """
    if not implies_decline_premise(query):
        return calls
    dates = sorted(set(re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", query)))
    if len(dates) != 1:
        return calls
    sql_blob = " ".join(
        str((c.args or {}).get("sql") or "") for c in calls if c.tool == "query_sales_db"
    ).upper()
    if (
        re.search(r"ORDER BY\s+TOTAL_REVENUE\s+DESC", sql_blob)
        and re.search(r"GROUP BY\s+1", sql_blob)
        and re.search(r"LIMIT\s+\d+", sql_blob)
    ):
        return calls
    bounds = load_outlet_date_bounds(BASE)
    outlets = list(bounds.outlets)
    if not outlets:
        return calls
    lit = "(" + ",".join("'" + str(o).replace("'", "''") + "'" for o in outlets) + ")"
    lo, hi = bounds.min_date.isoformat(), bounds.max_date.isoformat()
    sql = (
        "SELECT SUBSTR(INVOICE_DATE, 1, 10) AS day, IFNULL(ROUND(SUM(NET_AMT), 0), 0) AS total_revenue "
        "FROM VIEW_AI_SALES WHERE ZONE IN "
        + lit
        + f" AND SUBSTR(INVOICE_DATE, 1, 10) BETWEEN '{lo}' AND '{hi}' "
        "GROUP BY 1 ORDER BY total_revenue DESC LIMIT 6"
    )
    spec = TOOL_REGISTRY["query_sales_db"]
    return calls + [
        ToolCall(
            tool="query_sales_db",
            args={"sql": sql},
            emoji=spec["emoji"],
            label="Augmented: top revenue days (baseline)",
        )
    ]


class CopilotAgent:
    """
    Multi-tool agentic loop for QAFFEINE Copilot.

    Flow:
      1. plan()      — LLM outputs JSON tool-call array
      2. execute()   — tools run locally, results collected
      3. synthesise()— LLM produces final business response
    """

    def __init__(self, llm: LLMManager | None = None):
        self._llm = llm or LLMManager()

    # ── Step 1: Plan ──────────────────────────────────────────────────────────
    def _plan(self, query: str, monologue: list[str]) -> list[ToolCall]:
        tool_names = list(TOOL_REGISTRY.keys())
        base_prompt = PLANNER_PROMPT_TMPL.format(
            system=COPILOT_SYSTEM_PROMPT,
            query=query,
            tools=", ".join(tool_names),
        )
        monologue.append("🧠 Planning which tools to invoke…")
        result = self._llm.generate(
            base_prompt,
            temperature=0.15,
            max_output_tokens=1024,
            max_tokens=1024,
        )
        raw = re.sub(r"```(?:json)?", "", result.text.strip(), flags=re.IGNORECASE).strip().strip("`").strip()
        plan = parse_planner_tool_plan(raw)
        if not plan:
            monologue.append("⚠️ Planner JSON malformed — retrying once.")
            repair = (
                base_prompt
                + "\n\n=== CRITICAL ===\nReturn ONLY a JSON array of tool objects. "
                "No markdown fences, no commentary, no trailing text."
            )
            result2 = self._llm.generate(
                repair,
                temperature=0.1,
                max_output_tokens=1024,
                max_tokens=1024,
            )
            raw2 = re.sub(
                r"```(?:json)?", "", result2.text.strip(), flags=re.IGNORECASE
            ).strip().strip("`").strip()
            plan = parse_planner_tool_plan(raw2)

        calls = []
        for item in plan:
            tool_name = item.get("tool", "")
            if tool_name not in TOOL_REGISTRY:
                continue
            spec = TOOL_REGISTRY[tool_name]
            calls.append(ToolCall(
                tool  = tool_name,
                args  = item.get("args", {}),
                emoji = spec["emoji"],
                label = spec["label"],
            ))

        if calls:
            monologue.append(f"📋 Plan: {' → '.join(c.tool for c in calls)}")
        else:
            monologue.append("📋 No tools needed — responding from knowledge.")

        max_tools = 8
        if len(calls) > max_tools:
            monologue.append(f"⚠️ Truncating plan from {len(calls)} to {max_tools} tools for latency.")
            calls = calls[:max_tools]
        return calls

    # ── Step 2: Execute ───────────────────────────────────────────────────────
    def _execute(self, calls: list[ToolCall], monologue: list[str]) -> list[ToolCall]:
        for call in calls:
            monologue.append(f"{call.emoji} {call.label}…")
            fn = TOOL_REGISTRY[call.tool]["fn"]
            try:
                call.result  = fn(**call.args)
                call.success = True
                monologue.append(
                    f"   ✓ {call.tool} → {call.result[:80]}{'…' if len(call.result) > 80 else ''}"
                )
            except Exception as exc:
                call.result  = f"Tool error: {exc}"
                call.success = False
                monologue.append(f"   ✗ {call.tool} failed: {exc}")
        return calls

    @staticmethod
    def _strict_mode_addon() -> str:
        if not get_settings().copilot_strict_demo_mode:
            return ""
        return (
            "=== STRICT DEMO MODE ===\n"
            "- Maximum **120 words** for the entire answer.\n"
            "- End with **exactly two** short action bullets (no generic “review staffing” unless tools mention staffing).\n"
            "- Use the four required headings (**Data facts:** … **Possible explanations:**) — keep each to one tight paragraph.\n\n"
        )

    @staticmethod
    def _verified_numeric_block(calls: list[ToolCall]) -> tuple[str, dict]:
        """Build JSON digest for synthesis + evidence.numeric_facts."""
        facts: list[dict] = []
        for idx, call in enumerate(calls):
            if call.tool != "query_sales_db" or not call.success:
                continue
            dig = digest_markdown_tables(call.result or "")
            if dig is None or dig.row_count == 0:
                continue
            sql_preview = ""
            try:
                sql_preview = str((call.args or {}).get("sql", ""))[:240]
            except Exception:
                pass
            facts.append(
                {
                    "tool": "query_sales_db",
                    "call_index": idx,
                    "row_count": dig.row_count,
                    "column_sums": dig.column_sums,
                    "numeric_columns": dig.numeric_columns,
                    "sql_preview": sql_preview,
                }
            )
        rules = (
            "- For chain totals tied to a query_sales_db markdown table, use ONLY column_sums above; "
            "never mentally re-sum row values.\n"
            "- If column_sums includes revenue (or total_revenue, etc.), use that exact figure for the chain total.\n"
            "- If numeric_facts is empty, do not invent chain totals from partial tables."
        )
        body = json.dumps({"numeric_facts": facts}, indent=2)
        return body + "\n\n" + rules, {"numeric_facts": facts}

    # ── Step 3: Synthesise ────────────────────────────────────────────────────
    def _synthesise(
        self,
        query: str,
        calls: list[ToolCall],
        monologue: list[str],
        verified_block: str,
        strict_mode_addon: str,
        premise_block: str,
        data_scope_block: str,
    ) -> tuple[str, str, str]:
        if calls:
            tool_results_block = "\n\n".join(
                f"[{c.tool}]\n{c.result}" for c in calls
            )
        else:
            tool_results_block = "No tools were called."

        prompt = SYNTHESIS_PROMPT_TMPL.format(
            system=COPILOT_SYSTEM_PROMPT,
            query=query,
            tool_results=tool_results_block,
            verified_block=verified_block,
            premise_block=premise_block,
            data_scope_block=data_scope_block,
            strict_mode_addon=strict_mode_addon,
        )
        monologue.append("💡 Synthesising insights…")
        result = self._llm.generate(
            prompt,
            temperature=0.35,
            max_output_tokens=2048,
            max_tokens=2048,
        )
        return result.text, result.engine, result.model

    # ── Public: investigate ───────────────────────────────────────────────────
    def investigate(self, query: str) -> CopilotResult:
        """Full agentic loop. Returns a CopilotResult with all intermediate steps."""
        cr        = CopilotResult(query=query)
        monologue = cr.monologue

        monologue.append(f'🔍 Received query: "{query[:80]}"')

        try:
            calls = self._plan(query, monologue)
            calls = _augment_plan_for_decline_single_date(query, calls)
            cr.tool_calls = calls

            if len(calls) > 1:
                monologue.append(
                    f"🔗 Cross-referencing {len(calls)} data sources: "
                    + " · ".join(c.tool for c in calls)
                )

            self._execute(calls, monologue)

            verified_block, ev = self._verified_numeric_block(calls)
            resolved = build_resolved_query_context(query)
            pc = compute_premise_check(query, BASE)
            if pc:
                ev["premise_check"] = pc
            ds = build_data_scope(BASE, question=query, tool_names=[c.tool for c in calls])
            ev["data_scope"] = ds
            ev = {
                **ev,
                "resolved_query_context": resolved,
                "guardrail_flags": list(ev.get("guardrail_flags") or []),
            }
            cr.evidence = ev

            premise_block = (
                json.dumps(ev["premise_check"], indent=2)
                if ev.get("premise_check")
                else "(none — no decline-on-single-date premise rank for this question.)"
            )
            data_scope_block = json.dumps(ev.get("data_scope") or {}, indent=2)

            strict_addon = self._strict_mode_addon()
            text, engine, model = self._synthesise(
                query,
                calls,
                monologue,
                verified_block,
                strict_addon,
                premise_block,
                data_scope_block,
            )

            settings = get_settings()
            text, post_flags = apply_numeric_postcheck(
                text,
                ev.get("numeric_facts") or [],
                enabled=settings.copilot_numeric_validation,
            )
            ev["guardrail_flags"] = list(ev.get("guardrail_flags") or []) + post_flags
            text, causal_flags = apply_causal_postcheck(
                text,
                calls,
                enabled=settings.copilot_causal_postcheck,
            )
            ev["guardrail_flags"] = list(ev.get("guardrail_flags") or []) + causal_flags
            cr.evidence = ev
            cr.response = text
            cr.engine = engine
            cr.model = model
            monologue.append(f"✅ Response generated via {engine}/{model}")

            if settings.copilot_trace_jsonl:
                try:
                    append_copilot_trace(
                        BASE,
                        {
                            "query": query[:500],
                            "model": model,
                            "engine": engine,
                            "guardrail_flags": ev.get("guardrail_flags"),
                            "numeric_facts": ev.get("numeric_facts"),
                            "response_preview": (text or "")[:1200],
                        },
                    )
                except OSError:
                    pass

        except Exception as exc:
            cr.error = str(exc)
            monologue.append(f"❌ Fatal error: {exc}")

        return cr


# ══════════════════════════════════════════════════════════════════════════════
# PROACTIVE INTELLIGENCE BRIEF  (sidebar signal panel)
# ══════════════════════════════════════════════════════════════════════════════

def generate_proactive_brief() -> dict:
    """
    Autonomously computes and returns 3 top intelligence signals:
      1. revenue_anomaly  — date with highest Z-Score deviation
      2. top_power_combo  — #1 untapped bundle opportunity
      3. market_risk      — latest disruptor from context_intelligence
    """
    brief: dict = {}

    # ── Signal 1: Revenue Z-Score Anomaly ─────────────────────────────────────
    try:
        with sqlite_connection(BASE) as conn:
            rows = conn.execute(
                "SELECT SUBSTR(DT, 1, 10) AS date, ROUND(SUM(NETAMT),2) "
                "FROM AI_TEST_INVOICEBILLREGISTER GROUP BY SUBSTR(DT, 1, 10) ORDER BY date"
            ).fetchall()

        if rows:
            import statistics
            dates    = [r[0] for r in rows]
            revs     = [r[1] for r in rows]
            mean_r   = statistics.mean(revs)
            stdev    = statistics.stdev(revs) if len(revs) > 1 else 1
            z_scores = [(d, r, (r - mean_r) / stdev) for d, r in zip(dates, revs)]
            worst    = max(z_scores, key=lambda x: abs(x[2]))
            direction = "📉 Below" if worst[2] < 0 else "📈 Above"
            brief["revenue_anomaly"] = {
                "date"     : worst[0],
                "revenue"  : worst[1],
                "z_score"  : round(worst[2], 2),
                "direction": direction,
                "mean_rev" : round(mean_r, 0),
                "label"    : (
                    f"{worst[0]}  {direction} avg by "
                    f"{abs(worst[2]):.1f}σ  (₹{worst[1]:,.0f} vs avg ₹{mean_r:,.0f})"
                ),
            }
    except Exception as exc:
        brief["revenue_anomaly"] = {"label": f"Anomaly detection error: {exc}"}

    # ── Signal 2: Top Power Combo ──────────────────────────────────────────────
    try:
        json_path = BASE / "var" / "basket_results.json"
        if not json_path.exists():
            json_path = BASE / "database" / "basket_results.json"
        if json_path.exists():
            data   = json.loads(json_path.read_text(encoding="utf-8"))
            combos = data.get("power_combos", [])
            if combos:
                c = combos[0]
                brief["top_power_combo"] = {
                    "item_a"      : c["item_a"],
                    "item_b"      : c["item_b"],
                    "lift"        : c["lift"],
                    "bundle_price": c["bundle_price"],
                    "aov_lift_pct": c["aov_lift_pct"],
                    "label"       : (
                        f"Lift {c['lift']:.1f}x — "
                        f"{c['item_a'][:22]} + {c['item_b'][:22]} "
                        f"→ Bundle ₹{c['bundle_price']:.0f}  "
                        f"AOV +{c['aov_lift_pct']:.0f}%"
                    ),
                }
            else:
                brief["top_power_combo"] = {"label": "Run basket_analysis.py to compute combos."}
        else:
            brief["top_power_combo"] = {"label": "No basket data — run basket_analysis.py."}
    except Exception as exc:
        brief["top_power_combo"] = {"label": f"Combo load error: {exc}"}

    # ── Signal 3: Latest Market Risk ──────────────────────────────────────────
    try:
        with sqlite_connection(BASE) as conn:
            row = conn.execute(
                "SELECT date, holiday_name, weather_condition, news_disruptors "
                "FROM context_intelligence "
                "WHERE news_disruptors IS NOT NULL AND news_disruptors NOT LIKE 'No headlines%' "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()

        if row:
            date_str, hol, weather, disruptors = row
            text    = disruptors or ""
            text    = re.sub(r'(?i)^.*?(?:identified|are):\s*', '', text, flags=re.DOTALL).strip()
            snippet = text.replace('\n', ' | ')[:140]
            hol_flag = f" · 🗓️ {hol}" if hol else ""
            wth_flag = f" · 🌤️ {weather}" if weather and "Unavailable" not in (weather or "") else ""
            brief["market_risk"] = {
                "date"      : date_str,
                "holiday"   : hol,
                "weather"   : weather,
                "disruptors": disruptors,
                "label"     : f"{date_str}{hol_flag}{wth_flag} — {snippet}{'…' if len(disruptors or '') > 140 else ''}",
            }
        else:
            brief["market_risk"] = {"label": "No market context data yet — run universal_context.py."}
    except Exception as exc:
        brief["market_risk"] = {"label": f"Context load error: {exc}"}

    return brief


# ══════════════════════════════════════════════════════════════════════════════
# ANOMALY DIAGNOSIS NARRATIVE
# ══════════════════════════════════════════════════════════════════════════════

DIAGNOSIS_PROMPT_TMPL = """
You are QAFFEINE Copilot — the platform's senior business strategist.
You are writing a diagnosis paragraph for an automated morning brief email.

ANOMALY DETECTED:
  Outlet    : {outlet}
  Date      : {date}
  Revenue   : ₹{revenue:,.0f}
  Rolling μ : ₹{rolling_mean:,.0f}
  Z-Score   : {z_score:.2f}
  Deviation : {pct_deviation:+.1f}%

CONTEXTUAL DATA (auto-fetched):
  Weather : {weather_ctx}
  Holiday : {holiday_ctx}
  News    : {news_ctx}

TASK:
Write exactly ONE diagnostic paragraph (3-5 sentences).
- If revenue is BELOW baseline: State the revenue drop with numbers. Cross-reference weather, holiday, and news context to identify the most probable root cause(s).
- If revenue is ABOVE baseline (Peak): Highlight the success. Identify the key drivers (e.g. festivals, positive news, sunny weather, or commercial events like Valentine's Day).
- If no external factor explains the deviation clearly, suggest internal operational factors worth investigating.
- Use confident, executive-level language. Do NOT hedge or use "I think".
- Do NOT use markdown, bullets, or headers — pure flowing prose.
""".strip()


def generate_anomaly_diagnosis(
    anomalies: list,
    llm: "LLMManager | None" = None,
) -> list[dict]:
    """
    For each anomaly, fetch weather/news/holiday context and synthesize
    a diagnosis paragraph using LLMManager.

    Parameters
    ----------
    anomalies : list
        AnomalyRecord instances or dicts with keys:
        date, outlet_name, revenue, rolling_mean, rolling_std,
        z_score, pct_deviation, severity.
    llm : LLMManager, optional
        Shared LLM instance.  Creates one if None.

    Returns
    -------
    list[dict]
        Each dict: date, outlet_name, z_score, severity, diagnosis (str).
    """
    if llm is None:
        llm = LLMManager()

    results = []

    for anomaly in anomalies:
        a = anomaly if isinstance(anomaly, dict) else anomaly.to_dict()

        date_str    = a["date"]
        outlet_name = a["outlet_name"]

        weather_ctx = _tool_get_weather_context(date_str)
        holiday_ctx = _tool_get_holiday_status(date_str)
        news_ctx    = _tool_get_news_context(date_str)

        prompt = DIAGNOSIS_PROMPT_TMPL.format(
            outlet        = outlet_name,
            date          = date_str,
            revenue       = a.get("revenue", 0),
            rolling_mean  = a.get("rolling_mean", 0),
            z_score       = a.get("z_score", 0),
            pct_deviation = a.get("pct_deviation", 0),
            weather_ctx   = weather_ctx,
            holiday_ctx   = holiday_ctx,
            news_ctx      = news_ctx,
        )

        try:
            result         = llm.generate(prompt)
            diagnosis_text = result.text.strip()
        except Exception as exc:
            diagnosis_text = (
                f"Diagnosis unavailable: LLM error ({exc}). "
                f"Revenue at {outlet_name} on {date_str} was ₹{a.get('revenue', 0):,.0f} "
                f"(Z={a.get('z_score', 0):.2f}, {a.get('pct_deviation', 0):+.1f}% vs baseline)."
            )

        results.append({
            "date"       : date_str,
            "outlet_name": outlet_name,
            "z_score"    : a.get("z_score", 0),
            "severity"   : a.get("severity", "WARNING"),
            "diagnosis"  : diagnosis_text,
            "weather_ctx": weather_ctx,
            "holiday_ctx": holiday_ctx,
            "news_ctx"   : news_ctx,
        })

    return results


# ── Backward-compat alias (do NOT import JarvisAgent in new code) ─────────────
JarvisAgent  = CopilotAgent
JarvisResult = CopilotResult
