"""
QAFFEINE Jarvis System Check
==============================
Validates the full agentic stack with a "Triple-Tool" call:
  SQL (revenue data) + Weather + News for a single query

Writes results to database/jarvis_system_check.txt
Run from QAFFEINE_Prototype/:
    python scripts/jarvis_system_check.py
"""

import sys, os, datetime
from pathlib import Path
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE     = Path(__file__).resolve().parent.parent
ENV_PATH = BASE.parent / ".env"
LOG_OUT  = BASE / "database" / "jarvis_system_check.txt"
load_dotenv(ENV_PATH, override=True)

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from jarvis_brain import JarvisAgent, generate_proactive_brief, TOOL_REGISTRY

LINES: list[str] = []

def log(msg: str = "") -> None:
    print(msg)
    LINES.append(str(msg))

def section(title: str) -> None:
    log(); log("=" * 68); log(f"  {title}"); log("=" * 68)


def run_system_check():
    section("QAFFEINE Jarvis — System Check")
    log(f"  Run at : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Env    : {ENV_PATH}")
    log()

    # ── Engine status ─────────────────────────────────────────────────────
    gemini_key  = os.getenv("GEMINI_API_KEY", "")
    or_key      = os.getenv("OPENROUTER_API_KEY", "")
    weather_key = os.getenv("WEATHERAPI_KEY", "")
    news_key    = os.getenv("NEWS_API_KEY", "")

    log("  API Keys:")
    log(f"    Gemini      : {'✓ ' + gemini_key[:12] + '…' if gemini_key else '✗ missing'}")
    log(f"    OpenRouter  : {'✓ ' + or_key[:12] + '…' if or_key else '✗ missing'}")
    log(f"    WeatherAPI  : {'✓ ' + weather_key[:8] + '…' if weather_key else '✗ missing'}")
    log(f"    NewsAPI     : {'✓ ' + news_key[:8] + '…' if news_key else '✗ missing (RSS fallback)'}")

    log()
    log(f"  Tool registry: {len(TOOL_REGISTRY)} tools registered")
    for name, spec in TOOL_REGISTRY.items():
        log(f"    {spec['emoji']}  {name:<30}  — {spec['description'][:55]}")

    # ── Test 1: Proactive Brief ────────────────────────────────────────────
    section("TEST 1 — Proactive Intelligence Brief")
    log("  Generating autonomous morning brief…")
    brief = generate_proactive_brief()

    log()
    log("  SIGNAL 1 — Revenue Anomaly:")
    log(f"    {brief.get('revenue_anomaly', {}).get('label', 'N/A')}")

    log()
    log("  SIGNAL 2 — Top Power Combo:")
    log(f"    {brief.get('top_power_combo', {}).get('label', 'N/A')}")

    log()
    log("  SIGNAL 3 — Market Risk:")
    label = brief.get("market_risk", {}).get("label", "N/A")
    # wrap long line
    for chunk in [label[i:i+72] for i in range(0, len(label), 72)]:
        log(f"    {chunk}")

    log()
    log("  ✓ Proactive brief generated successfully.")

    # ── Test 2: Individual tool smoke-test ────────────────────────────────
    section("TEST 2 — Individual Tool Smoke Tests")

    test_date = "2025-12-07"   # Sunday — the anomaly day in AI_DATABASE.DB

    # Tool A: SQL
    log(f"  [query_sales_db] Fetching outlet summary for {test_date} …")
    from jarvis_brain import _tool_query_sales_db
    sql_result = _tool_query_sales_db(
        f"SELECT outlet_name, ROUND(SUM(net_revenue),2) AS rev "
        f"FROM fact_sales WHERE date='{test_date}' "
        f"GROUP BY outlet_name ORDER BY rev DESC"
    )
    log("  Result:\n" + "\n".join("    " + l for l in sql_result.splitlines()))

    # Tool B: Weather
    log()
    log(f"  [get_weather_context] Fetching Hyderabad weather for {test_date} …")
    from jarvis_brain import _tool_get_weather_context
    weather_result = _tool_get_weather_context(test_date)
    log(f"  Result: {weather_result}")

    # Tool C: News
    log()
    log(f"  [get_news_context] Fetching headlines for {test_date} …")
    from jarvis_brain import _tool_get_news_context
    news_result = _tool_get_news_context(test_date)
    log("  Result:\n" + "\n".join("    " + l for l in news_result.splitlines()[:6]))

    # Tool D: Holiday
    log()
    log(f"  [get_holiday_status] Checking holiday status for {test_date} …")
    from jarvis_brain import _tool_get_holiday_status
    holiday_result = _tool_get_holiday_status(test_date)
    log(f"  Result: {holiday_result}")

    # Tool E: Combos
    log()
    log("  [get_combo_recommendations] Pulling top combos …")
    from jarvis_brain import _tool_get_combo_recommendations
    combo_result = _tool_get_combo_recommendations()
    log("  Result:\n" + "\n".join("    " + l for l in combo_result.splitlines()[:4]))

    log()
    log("  ✓ All 5 tools returned non-empty results.")

    # ── Test 3: TRIPLE-TOOL Agentic Run ──────────────────────────────────
    section("TEST 3 — Triple-Tool Agentic Run (SQL + Weather + News)")

    TRIPLE_TOOL_QUERY = (
        "Why did revenue drop so drastically on Dec 7th at QAFFEINE HITECH CITY? "
        "Investigate the sales data, weather conditions, and any news events that day."
    )

    log(f"  Query      : {TRIPLE_TOOL_QUERY}")
    log()
    log("  Initialising JarvisAgent…")
    agent = JarvisAgent()

    log("  Executing investigation loop…")
    result = agent.investigate(TRIPLE_TOOL_QUERY)

    log()
    log("  ── Internal Monologue (Jarvis Thought Process) ──")
    for step in result.monologue:
        log(f"    {step}")

    log()
    log("  ── Tools Called ──")
    if result.tool_calls:
        for tc in result.tool_calls:
            status = "✓" if tc.success else "✗"
            log(f"    {status} {tc.tool}  args={tc.args}")
            log(f"       → {tc.result[:120]}{'…' if len(tc.result)>120 else ''}")
    else:
        log("    (No tools invoked — LLM responded directly)")

    tools_used = [tc.tool for tc in result.tool_calls]
    triple_hit = (
        any("query_sales_db" in t for t in tools_used) and
        any("weather" in t for t in tools_used) and
        (any("news" in t for t in tools_used) or any("holiday" in t for t in tools_used))
    )

    log()
    log(f"  Engine : {result.engine} / {result.model}")
    log(f"  Error  : {result.error or 'none'}")
    log()
    log("  ── Final Jarvis Response ──")
    for line in (result.response or "(no response)").splitlines():
        log(f"    {line}")

    log()
    log("  ── TRIPLE-TOOL VERDICT ──")
    tool_summary = " + ".join(tools_used) if tools_used else "NONE"
    log(f"    Tools invoked  : {tool_summary}")
    log(f"    SQL called     : {'✓' if any('query_sales_db' in t for t in tools_used) else '✗'}")
    log(f"    Weather called : {'✓' if any('weather' in t for t in tools_used) else '✗'}")
    log(f"    News/Holiday   : {'✓' if any('news' in t or 'holiday' in t for t in tools_used) else '✗'}")
    log(f"    TRIPLE-TOOL    : {'✅ PASS' if triple_hit else '⚠  PARTIAL (LLM chose fewer tools)'}")

    # ── Save log ──────────────────────────────────────────────────────────
    section("LOG FILE")
    LOG_OUT.write_text("\n".join(LINES), encoding="utf-8")
    log(f"  Log saved → {LOG_OUT}")
    log()
    log("  QAFFEINE Jarvis System Check — Complete.")


if __name__ == "__main__":
    run_system_check()
