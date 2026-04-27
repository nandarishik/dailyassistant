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

import os, sys, re, json, sqlite3, datetime, textwrap, requests
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv
from contextlib import contextmanager
from src.config.settings import resolve_db_path

# ── Paths & env ───────────────────────────────────────────────────────────────
BASE     = Path(__file__).resolve().parent.parent
DB_PATH  = resolve_db_path(BASE)
ENV_PATH = BASE.parent / ".env"

load_dotenv(ENV_PATH, override=True)

# ── Re-use existing modules ───────────────────────────────────────────────────
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from universal_context import (
    LLMManager, get_weather_context, get_holiday_info,
    get_news_headlines,
)

try:
    from forecaster import simulate_scenario as _simulate_scenario_fn
    _FORECASTER_AVAILABLE = True
except ImportError:
    _FORECASTER_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE CONNECTION HELPER  (hardened)
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def _db_connect(timeout: float = 10.0):
    """
    Context manager for a hardened SQLite connection.
    Ensures the connection is always closed even on exception.
    WAL mode is enabled for concurrent read safety.
    """
    conn = None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=timeout)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        yield conn
    except sqlite3.OperationalError as exc:
        raise RuntimeError(f"Database connection failed: {exc}") from exc
    finally:
        if conn:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS  — each returns a plain string summary
# Context priority: DB (context_intelligence table) → live API fallback
# ══════════════════════════════════════════════════════════════════════════════

def _tool_query_sales_db(sql: str) -> str:
    """Run a SELECT against AI_DATABASE.DB and return results as a markdown table."""
    query = sql.strip().rstrip(";")
    if not re.match(r"(?i)^SELECT\b", query):
        return "ERROR: Only SELECT queries are permitted."
    if ";" in query:
        return "ERROR: Multiple statements are not allowed."
    if re.search(r"(?i)\b(sqlite_master|sqlite_schema|pragma|attach|detach|load_extension)\b", query):
        return "ERROR: Query touches restricted SQLite internals or commands."
    if not re.search(r"(?i)\bLIMIT\s+\d+\b", query):
        query = f"{query} LIMIT 200"
    try:
        with _db_connect() as conn:
            # Abort runaway scans to keep the Copilot path responsive.
            callback_count = {"n": 0}
            max_callbacks = 25
            def _progress_abort() -> int:
                callback_count["n"] += 1
                return 1 if callback_count["n"] > max_callbacks else 0
            conn.set_progress_handler(_progress_abort, 200000)
            cur  = conn.execute(query)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(200)
        if not rows:
            return "Query returned 0 rows."
        lines = ["| " + " | ".join(cols) + " |",
                 "|" + "|".join(" --- " for _ in cols) + "|"]
        for row in rows:
            lines.append("| " + " | ".join(str(v) for v in row) + " |")
        return "\n".join(lines)
    except Exception as exc:
        return f"SQL Error: {exc}"


def _fetch_context_row(date: str) -> dict | None:
    """
    Retrieve a pre-analysed context row from context_intelligence for the given date.
    Returns None if the table doesn't exist or the date has no row.
    """
    try:
        with _db_connect() as conn:
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


def _tool_compute_live_basket(
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
        clauses.append("LOCATION_NAME = ?")
        params.append(outlet_filter.strip())
    if date_from.strip():
        clauses.append("SUBSTR(DT, 1, 10) >= ?")
        params.append(date_from.strip())
    if date_to.strip():
        clauses.append("SUBSTR(DT, 1, 10) <= ?")
        params.append(date_to.strip())
    if group_filter.strip():
        clauses.append("(GROUP_NAME LIKE ? OR PRODUCT_NAME LIKE ?)")
        like = f"%{group_filter.strip()}%"
        params.extend([like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = f"""
        SELECT TRNNO AS bill_no, PRODUCT_NAME AS item_name,
               SUM(NET_AMT) AS rev,
               SUM(QTY)     AS qty
        FROM   AI_TEST_TAXCHARGED_REPORT
        {where}
        GROUP  BY TRNNO, PRODUCT_NAME
    """
    try:
        with _db_connect() as conn:
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
        "description": "Run a SQLite SELECT on AI_DATABASE.DB. Arg: sql (string).",
        "args"       : ["sql"],
        "emoji"      : "🗄️",
        "label"      : "Querying sales database",
    },
    "get_weather_context": {
        "fn"         : _tool_get_weather_context,
        "description": (
            "Get weather data for Hyderabad on a date. "
            "Reads from the pre-enriched context_intelligence DB first; "
            "falls back to WeatherAPI live call if absent. Arg: date (YYYY-MM-DD)."
        ),
        "args"       : ["date"],
        "emoji"      : "🌦️",
        "label"      : "Retrieving Hyderabad weather context",
    },
    "get_holiday_status": {
        "fn"         : _tool_get_holiday_status,
        "description": (
            "Check if a date is a Telangana/National holiday. "
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
    "get_combo_recommendations": {
        "fn"         : _tool_get_combo_recommendations,
        "description": "Return top Power Combo bundle recommendations. No args needed.",
        "args"       : [],
        "emoji"      : "🎯",
        "label"      : "Pulling Power Combo recommendations",
    },
    "compute_live_basket": {
        "fn"         : _tool_compute_live_basket,
        "description": (
            "Compute Market Basket Analysis live from the DB for a custom scope. "
            "Args (all optional strings/int): "
            "outlet_filter (e.g. 'QAFFEINE HITECH CITY'), "
            "date_from (YYYY-MM-DD), date_to (YYYY-MM-DD), "
            "group_filter (e.g. 'COFFEE', 'SANDWICH'), "
            "top_n (int, default 8). "
            "Returns live co-purchase pairs with Lift, Confidence, quadrant labels "
            "and bundle pricing. Use this instead of get_combo_recommendations "
            "whenever the user asks about a specific outlet, date, or product category."
        ),
        "args"       : ["outlet_filter", "date_from", "date_to", "group_filter", "top_n"],
        "emoji"      : "🧮",
        "label"      : "Computing live basket analysis",
    },
    "simulate_scenario": {
        "fn"         : _tool_simulate_scenario,
        "description": (
            "Predict revenue for a hypothetical weather scenario using the ML forecaster. "
            "Args: outlet (outlet name, e.g. 'QAFFEINE HITECH CITY'), "
            "date (YYYY-MM-DD), rain_mm (string number, e.g. '15'), "
            "temp_c (string number, e.g. '24'). "
            "Returns predicted revenue vs sunny-day baseline with % delta. "
            "Use this for any 'what if', 'how will', 'predict', 'forecast', "
            "'simulate', 'thunderstorm', 'rain impact' questions."
        ),
        "args"       : ["outlet", "date", "rain_mm", "temp_c"],
        "emoji"      : "🔮",
        "label"      : "Running revenue simulation",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

DB_SCHEMA_BRIEF = """
SQLite database: AI_DATABASE.DB

TABLE: AI_TEST_TAXCHARGED_REPORT (item-level POS transactions. Every bill line item)
   DT                     DATETIME      (format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
   LOCATION_NAME          VARCHAR(100)  (e.g. 'CAKE NATION BASERA', 'TANSEN RESTAURANT', 'GUFAA')
   BRAND_NAME             VARCHAR(100)
   PRODUCT_NAME           VARCHAR(100)  (menu item name)
   NET_AMT                NUMERIC       (net sale amount in INR for this line. MUST SUM())
   QTY                    NUMERIC       (units sold)
   ORDERTYPE_NAME         VARCHAR(100)  ('Dine-In/Eat-In', 'Delivery', etc.)
   TRNNO                  VARCHAR(25)   (unique bill identifier)
   GROUP_NAME             VARCHAR(100)  (menu category group)
   SPLCATEGORY            VARCHAR(100)  (special category, e.g. 'BEVERAGES', 'FOOD')
   BASICRATE              NUMERIC       (base price per unit)
   CGSTAMT                NUMERIC       (CGST tax amount)
   SGSTAMT                NUMERIC       (SGST tax amount)
   GSTAMT_TOTAL           NUMERIC       (total GST)

TABLE: AI_TEST_INVOICEBILLREGISTER (Top-level invoice billing data. 1 row per bill/customer)
   DT                 DATETIME
   LOCATION_NAME      VARCHAR(50)
   TRNNO              VARCHAR(25)     (join with AI_TEST_TAXCHARGED_REPORT)
   NETAMT             NUMERIC         (Use this for total daily/outlet revenue!)
   ORDER_TYPE         VARCHAR(100)
   DISCOUNT           NUMERIC
   CASH_AMT           NUMERIC
   CARD_AMT           NUMERIC
   PAYMENT_UPI        NUMERIC
   PAX                NUMERIC

TABLE: AI_TEST_ONLINEORDER (Delivery lifecycle data)
   ORDERTIME          DATETIME
   RIDER_NAME         VARCHAR(250)
   ISORDERAPPROVED    NUMERIC(1)
   CANCEL_REMARK      VARCHAR(500)
   ORDERDELIVERED_DT  DATETIME
   FOODPREPTIME       INTEGER

CRITICAL SQL RULES:
  1. ALWAYS use SUM(NETAMT) when querying AI_TEST_INVOICEBILLREGISTER for revenue totals.
  2. ALWAYS use dates in SUBSTR(DT, 1, 10) to format strings safely when grouping.
  3. For 'revenue on date X' → show ALL outlets.
  4. For anomaly/comparisons, dynamically run averages across the previous 7 days (do NOT hardcode dates).
  5. Use AI_TEST_INVOICEBILLREGISTER for daily aggregate totals. Use AI_TEST_TAXCHARGED_REPORT for menu item details. Use AI_TEST_ONLINEORDER for Delivery Prep time and cancellation queries.
""".strip()

COPILOT_SYSTEM_PROMPT = f"""
You are QAFFEINE Copilot — an elite AI business strategist embedded inside QAFFEINE's analytics platform, a premium coffee chain.

Personality:
- You have the strategic depth of a McKinsey partner and the directness of a growth-stage founder.
- You never say "I cannot answer this" unless all tools return errors.
- You proactively cross-reference weather, holidays, commercial events, basket data, and sales trends.
- You show findings as senior-level business insights with specific numbers, not vague summaries.

Tools available (call by returning JSON):
{json.dumps({k: v["description"] for k, v in TOOL_REGISTRY.items()}, indent=2)}

Sales DB Knowledge:
{DB_SCHEMA_BRIEF}

Routing Rules:
- Revenue anomaly / drop question → query_sales_db (total + per-outlet) AND get_weather_context AND get_holiday_status AND get_news_context
- Specific date question → weather + holiday + news for that date
- Basket / affinity / 'what sells together' for a specific outlet or date → compute_live_basket (NOT get_combo_recommendations)
- General bundle overview, no filter → get_combo_recommendations
- compute_live_basket + query_sales_db can be combined freely in the same turn
- Novel open-ended basket question (e.g. 'what food pairs with coffee?') → compute_live_basket with group_filter set
- ANY hypothetical / what-if / predict / forecast / 'how will X affect' / 'what happens if' → simulate_scenario
  - Translate conditions like 'thunderstorm' → rain_mm=15, temp_c=22
  - Translate 'light rain' → rain_mm=5, 'heavy rain' → rain_mm=25
  - Translate 'heatwave' → temp_c=42, rain_mm=0
  - Always compare the prediction against the sunny-day baseline

Monthly/Seasonal Logic:
- If asked about a month (e.g. 'March'), use SUBSTR(DT, 1, 7) = '2026-03'.
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
- ALWAYS wrap revenue with SUM(): e.g. SUM(NETAMT) — never use bare columns as a total.
- Use IFNULL(SUM(NETAMT), 0) to prevent empty crashes.
- Never use 'date' column, use SUBSTR(DT, 1, 10).
- IMPORTANT: If asking about a specific outlet, make sure the week average query HAS the same `WHERE LOCATION_NAME='...'` filter inside the subquery so you don't compare a single outlet to the entire chain's total!
- Use AI_TEST_INVOICEBILLREGISTER for daily/outlet totals, AI_TEST_TAXCHARGED_REPORT for item-level detail.
- Always alias with AS, always name columns explicitly.

Example for 'revenue on date X':
  {{"tool": "query_sales_db", "args": {{"sql": "SELECT LOCATION_NAME, ROUND(SUM(NETAMT),0) AS revenue FROM AI_TEST_INVOICEBILLREGISTER WHERE SUBSTR(DT, 1, 10)='2026-01-01' GROUP BY LOCATION_NAME ORDER BY revenue DESC"}}}}

Example for 'lowest sales in March':
  {{"tool": "query_sales_db", "args": {{"sql": "SELECT SUBSTR(DT, 1, 10) AS date, ROUND(SUM(NETAMT),0) AS total_revenue FROM AI_TEST_INVOICEBILLREGISTER WHERE SUBSTR(DT, 1, 7)='2026-03' GROUP BY date ORDER BY total_revenue ASC LIMIT 1"}}}}

Available tools: {tools}
If no tools are needed, return: []
"""

SYNTHESIS_PROMPT_TMPL = """
{system}

=== USER QUERY ===
{query}

=== TOOL RESULTS ===
{tool_results}

=== YOUR TASK ===
Synthesise the above tool results into a senior-level business response.
- Use ONLY numbers and facts that appear in the tool results. Do NOT invent or approximate figures.
- STRICT LOGIC: If weather says "no precipitation", do NOT invent "showers". Never contradict the tool data.
- STRICT RELEVANCE: If news / market intelligence is entirely unrelated to retail/footfall, say so explicitly.
- Lead with the key metric explicit (e.g. total revenue vs week average).
- Max 200 words. Prose first, then 2-3 action bullets max. No JSON in the response.
- If a tool returned an error or empty result, say so rather than guessing.
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
        prompt = PLANNER_PROMPT_TMPL.format(
            system=COPILOT_SYSTEM_PROMPT,
            query=query,
            tools=", ".join(tool_names),
        )
        monologue.append("🧠 Planning which tools to invoke…")
        result = self._llm.generate(prompt)
        raw    = result.text.strip()

        # Strip accidental markdown fences
        raw = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip().strip("`").strip()

        try:
            plan = json.loads(raw)
            if not isinstance(plan, list):
                plan = []
        except (json.JSONDecodeError, ValueError):
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            plan = json.loads(m.group(0)) if m else []

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

    # ── Step 3: Synthesise ────────────────────────────────────────────────────
    def _synthesise(
        self,
        query: str,
        calls: list[ToolCall],
        monologue: list[str],
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
        )
        monologue.append("💡 Synthesising insights…")
        result = self._llm.generate(prompt)
        return result.text, result.engine, result.model

    # ── Public: investigate ───────────────────────────────────────────────────
    def investigate(self, query: str) -> CopilotResult:
        """Full agentic loop. Returns a CopilotResult with all intermediate steps."""
        cr        = CopilotResult(query=query)
        monologue = cr.monologue

        monologue.append(f'🔍 Received query: "{query[:80]}"')

        try:
            calls       = self._plan(query, monologue)
            cr.tool_calls = calls

            if len(calls) > 1:
                monologue.append(
                    f"🔗 Cross-referencing {len(calls)} data sources: "
                    + " · ".join(c.tool for c in calls)
                )

            self._execute(calls, monologue)

            text, engine, model = self._synthesise(query, calls, monologue)
            cr.response = text
            cr.engine   = engine
            cr.model    = model
            monologue.append(f"✅ Response generated via {engine}/{model}")

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
        with _db_connect() as conn:
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
        with _db_connect() as conn:
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
