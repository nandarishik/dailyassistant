"""
QAFFEINE Sales Dashboard — v2 with Gemini AI Assistant
=======================================================
Tabbed Streamlit app: Tab 1 = KPI Dashboard, Tab 2 = AI Assistant
Run: streamlit run app/dashboard.py
"""

import sys, os, sqlite3, pathlib, re, textwrap, html
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
from src.config.settings import resolve_db_path

# ─── Load .env and import LLMManager from context engine ─────────────────────
_BASE_DIR  = pathlib.Path(__file__).parent.parent
_ENV_PATH  = _BASE_DIR.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

# Make scripts/ importable
if str(_BASE_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(_BASE_DIR / "scripts"))
from universal_context import LLMManager
from copilot_brain import CopilotAgent, generate_proactive_brief, generate_anomaly_diagnosis
from anomaly_engine import detect_anomalies_all_outlets, get_anomaly_summary_table
from mailer import send_morning_brief, load_notification_history, build_email_html, log_notification
from copilot_brain import _tool_compute_live_basket

# Phase 4.2/5 imports
try:
    from forecaster import (
        predict_revenue, simulate_scenario, load_model,
        OUTLETS as FORECAST_OUTLETS, interpret_scenario_prompt,
        generate_hourly_trend,
    )
    _FORECASTER_READY = True
except Exception:
    _FORECASTER_READY = False
    FORECAST_OUTLETS = []

try:
    from chaos_monkey import run_all_scenarios, get_chaos_history
    _CHAOS_READY = True
except Exception:
    _CHAOS_READY = False

# ─── Basket Analysis results (pre-computed by basket_analysis.py) ────────────
@st.cache_data(ttl=300)                 # refresh every 5 min
def load_basket_results() -> dict:
    """Load pre-computed basket analysis JSON. Returns empty dict if missing."""
    json_path = _BASE_DIR / "database" / "basket_results.json"
    if json_path.exists():
        import json
        return json.loads(json_path.read_text(encoding="utf-8"))
    return {}

# ─── Copilot Intelligence Brief (cached 10 min) ──────────────────────────────
@st.cache_data(ttl=600)
def get_intelligence_brief() -> dict:
    """Auto-computes anomaly + combo + market risk — no user prompt needed."""
    return generate_proactive_brief()

# ─── Copilot Agent singleton ───────────────────────────────────────────────────
@st.cache_resource
def get_copilot() -> CopilotAgent:
    return CopilotAgent(llm=get_llm())

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QAFFEINE Analytics",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE    = _BASE_DIR
DB_PATH = resolve_db_path(BASE)

# ─── LLM Dual-Engine (Gemini primary → OpenRouter backup) ────────────────────
# Instantiated once at startup; shared across all Streamlit reruns via cache.
@st.cache_resource
def get_llm() -> LLMManager:
    return LLMManager()

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    min-height: 100vh;
}
.main .block-container { padding: 1.5rem 2.5rem 2rem; max-width: 1400px; }

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    border-right: 1px solid rgba(255,255,255,0.08);
}
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
[data-testid="stSidebar"] label {
    color: #94a3b8 !important; font-size: 0.78rem;
    font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"]  {
    background: rgba(255,255,255,0.04);
    border-radius: 12px; padding: 4px; gap: 4px;
    border: 1px solid rgba(255,255,255,0.08);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px; padding: 0.45rem 1.4rem;
    font-weight: 600; font-size: 0.85rem; color: #94a3b8;
    background: transparent; border: none;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg,#f59e0b,#f97316) !important;
    color: #fff !important;
}

/* ── KPI Cards ── */
.kpi-card {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 16px; padding: 1.4rem 1.6rem 1.2rem;
    backdrop-filter: blur(12px);
    transition: transform .2s, box-shadow .2s;
}
.kpi-card:hover { transform: translateY(-3px); box-shadow: 0 12px 32px rgba(0,0,0,.4); }
.kpi-icon  { font-size: 1.8rem; margin-bottom: .4rem; }
.kpi-label { font-size: .72rem; font-weight: 700; letter-spacing: .1em;
             text-transform: uppercase; color: #94a3b8; margin-bottom: .3rem; }
.kpi-value { font-size: 1.6rem; font-weight: 800; color: #f1f5f9; line-height: 1.1; }
.kpi-sub   { font-size: .75rem; color: #64748b; margin-top: .25rem; }

/* ── Section headers ── */
.section-header {
    font-size: 1rem; font-weight: 700; color: #cbd5e1;
    letter-spacing: .06em; text-transform: uppercase;
    padding: .6rem 0 .4rem;
    border-bottom: 1px solid rgba(255,255,255,.08); margin-bottom: .8rem;
}
.custom-divider {
    height: 1px;
    background: linear-gradient(90deg,transparent,rgba(255,255,255,.15),transparent);
    margin: 1.5rem 0;
}
.page-title { font-size: 2.2rem; font-weight: 800; color: #f8fafc; line-height: 1.1; }
.page-sub   { font-size: .9rem; color: #94a3b8; margin-top: .2rem; }

/* ── Chat bubbles ── */
.chat-user {
    background: linear-gradient(135deg,#3b82f6,#6366f1);
    border-radius: 16px 16px 4px 16px;
    padding: .8rem 1.1rem; margin: .5rem 0; color:#fff;
    font-size:.9rem; max-width:80%; margin-left:auto; text-align:right;
}
.chat-ai {
    background: rgba(255,255,255,.06);
    border: 1px solid rgba(255,255,255,.1);
    border-radius: 4px 16px 16px 16px;
    padding: .8rem 1.1rem; margin: .5rem 0; color:#e2e8f0;
    font-size:.9rem; max-width:85%;
}
.sql-block {
    background: #0f172a; border: 1px solid rgba(99,102,241,.4);
    border-radius: 10px; padding: .8rem 1rem;
    font-family: 'Courier New', monospace; font-size: .8rem;
    color: #a5b4fc; margin: .5rem 0;
}
.insight-block {
    background: linear-gradient(135deg,rgba(16,185,129,.1),rgba(6,182,212,.1));
    border: 1px solid rgba(16,185,129,.3);
    border-radius: 10px; padding: .8rem 1rem;
    font-size: .88rem; color: #d1fae5; margin: .5rem 0;
}
.ai-thinking {
    color: #64748b; font-size: .78rem;
    font-style: italic; padding: .3rem 0;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background: rgba(255,255,255,.04) !important;
    border: 1px solid rgba(255,255,255,.08) !important;
    border-radius: 12px !important;
}
</style>
""", unsafe_allow_html=True)

# ─── DB helpers ───────────────────────────────────────────────────────────────
@st.cache_resource
def get_conn():
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)

def qry(sql, params=()):
    return pd.read_sql_query(sql, get_conn(), params=params)

# ─── DB Schema for prompt ─────────────────────────────────────────────────────
DB_SCHEMA = """
DATABASE: AI_DATABASE.DB (SQLite)
Tables and columns (with data types):

1. AI_TEST_TAXCHARGED_REPORT  — Item-level POS transactions. Every bill line item.
   - DT                     DATETIME      (format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
   - LOCATION_NAME          VARCHAR(100)  (e.g. 'CAKE NATION BASERA', 'TANSEN RESTAURANT', 'GUFAA')
   - BRAND_NAME             VARCHAR(100)
   - PRODUCT_NAME           VARCHAR(100)  (menu item name)
   - NET_AMT                NUMERIC       (net sale amount in INR for this line)
   - QTY                    NUMERIC       (units sold)
   - ORDERTYPE_NAME         VARCHAR(100)  ('Dine-In/Eat-In', 'Delivery', etc.)
   - TRNNO                  VARCHAR(25)   (unique bill identifier)
   - GROUP_NAME             VARCHAR(100)  (menu category group)
   - SPLCATEGORY            VARCHAR(100)  (special category, e.g. 'BEVERAGES', 'FOOD')
   - BASICRATE              NUMERIC       (base price per unit)
   - CGSTAMT                NUMERIC       (CGST tax amount)
   - SGSTAMT                NUMERIC       (SGST tax amount)
   - GSTAMT_TOTAL           NUMERIC       (total GST)
   - ORDER_STARTTIME        DATETIME      (order start timestamp)
   - CITY_NAME              VARCHAR(20)

2. AI_TEST_INVOICEBILLREGISTER — Top-level invoice billing data.
   - DT                 DATETIME
   - LOCATION_NAME      VARCHAR(50)
   - BRAND_NAME         VARCHAR(50)
   - TRNNO              VARCHAR(25)     (join with AI_TEST_TAXCHARGED_REPORT)
   - NETAMT             NUMERIC
   - ORDER_TYPE         VARCHAR(100)
   - TOTAL_SETTLEMENT   NUMERIC
   - DISCOUNT           NUMERIC
   - CUSTOMER_NAME      VARCHAR(200)
   - STORE_CITY         VARCHAR(20)
   - BILL_AMT           NUMERIC
   - CASH_AMT           NUMERIC
   - CARD_AMT           NUMERIC
   - PAYMENT_UPI        NUMERIC
   - PAX                NUMERIC

3. AI_TEST_ONLINEORDER — Delivery lifecycle data.
   - ORDERTIME          DATETIME
   - RIDER_NAME         VARCHAR(250)
   - ISORDERAPPROVED    NUMERIC(1)
   - CANCEL_REMARK      VARCHAR(500)
   - ORDERDELIVERED_DT  DATETIME
   - FOODPREPTIME       INTEGER

Indexed columns (fast): DT, LOCATION_NAME, PRODUCT_NAME (where present), TRNNO.
All monetary values are in Indian Rupees (INR / ₹)."""

# ─── External Factors (mock enrichment for root-cause context) ─────────────────
EXTERNAL_FACTORS = {
    "2025-12-01": "QAFFEINE brand launch week opening promotions across all outlets.",
    "2025-12-02": "Regular trading day. No external events recorded.",
    "2025-12-03": "IT corridor (Hitech City) — tech conference at HITEX nearby, higher footfall.",
    "2025-12-04": "Midweek — typical slower day for dine-in across QSR chains.",
    "2025-12-05": "Friday — pre-weekend footfall pickup, especially carry-out.",
    "2025-12-06": "Saturday — Local music festival near Banjara Hills; peak trading day of the week.",
    "2025-12-07": "Sunday — Early store closure (documented operational issue: power disruption at 3 outlets after 4 PM). Revenue significantly lower than Saturday.",
}

def get_external_context(question: str, result_summary: str) -> str:
    """Return relevant external factor lines if the question or data mentions specific dates."""
    import re
    mentioned = []
    # Pull any dates found in question or result
    for date, note in EXTERNAL_FACTORS.items():
        short_date = date[5:]  # MM-DD
        day_num    = date[-2:]  # DD
        if (date in question or date in result_summary
                or short_date in question or day_num in question
                or any(m in question.lower() for m in ["why", "reason", "cause", "explain", "lower", "higher", "peak", "drop"])):
            mentioned.append(f"  {date}: {note}")
    if not mentioned:
        # Inject all if a 'why' question and no specific date detected
        if any(w in question.lower() for w in ["why", "reason", "cause", "explain"]):
            mentioned = [f"  {d}: {n}" for d, n in EXTERNAL_FACTORS.items()]
    return "\n".join(mentioned)

# ─── NL → SQL prompt ──────────────────────────────────────────────────────────
def build_sql_prompt(user_question: str) -> str:
    return textwrap.dedent(f"""
    You are a SQLite expert for a multi-outlet restaurant chain called QAFFEINE.
    Given a natural language question, return ONLY a single, valid SQLite SELECT statement.
    Do NOT explain anything. Do NOT use markdown code fences. Output raw SQL only.

    Rules:
    - Use only the tables and columns defined in the schema below.
    - Always ROUND monetary values to 2 decimal places.
    - Use LIMIT 20 unless the user specifies otherwise.
    - For date filtering, dates are in 'YYYY-MM-DD' string format.
    - For top-N queries, use ORDER BY … DESC LIMIT N.
    - Prefer AI_TEST_TAXCHARGED_REPORT for item/bill-level questions.
    - Prefer AI_TEST_INVOICEBILLREGISTER for daily/top-level bill questions.
    - Prefer AI_TEST_ONLINEORDER for delivery/rider questions.

    SCHEMA:
    {DB_SCHEMA}

    QUESTION: {user_question}
    SQL:
    """).strip()

# ─── Insight prompt ───────────────────────────────────────────────────────────
def build_insight_prompt(question: str, sql: str, result_md: str) -> str:
    ext_ctx = get_external_context(question, result_md)
    ext_section = ""
    if ext_ctx:
        ext_section = f"""
EXTERNAL CONTEXT (documented real-world events that may explain the data):
{ext_ctx}
Use this context to explain 'why' patterns if relevant."""
    return textwrap.dedent(f"""
    You are a senior business analyst for QAFFEINE, a multi-outlet coffee & food chain in Hyderabad.
    A manager asked: "{question}"
    The query returned the following data:

    {result_md}
    {ext_section}

    In 2-4 clear, concise sentences, provide a business insight interpreting this data.
    - Mention specific numbers (₹ values, percentages, item names, outlet names) wherever relevant.
    - If external context is provided and relevant, cite it as the reason for the pattern.
    - Highlight what is notable, surprising, or actionable.
    - Keep the tone professional but conversational.
    - Do NOT mention SQL, tables, or technical details.
    """).strip()

# ─── Execute SQL safely ───────────────────────────────────────────────────────
def run_sql(sql: str):
    """Return (DataFrame, error_string). Only SELECT allowed."""
    sql_clean = sql.strip().rstrip(";")
    if not re.match(r"(?i)^\s*SELECT\b", sql_clean):
        return None, "Only SELECT queries are permitted."
    try:
        df = pd.read_sql_query(sql_clean, get_conn())
        return df, None
    except Exception as e:
        return None, str(e)

# ─── LLM calls via dual-engine LLMManager ────────────────────────────────────
def _llm_call(prompt: str) -> tuple[str, str, str, str]:
    """
    Call LLMManager and return a tuple of:
      (response_text, engine, model_name, error_string | None)

    Engine is one of: "Gemini" | "OpenRouter" | "none"
    Automatically retries Gemini models, then falls back to OpenRouter
    on any 429 / 500 / RESOURCE_EXHAUSTED error — no manual intervention needed.
    """
    try:
        result = get_llm().generate(prompt)
        if result.engine == "none":
            return "", "none", "none", result.text   # text contains the error msg
        return result.text, result.engine, result.model, None
    except Exception as exc:
        return "", "none", "none", str(exc)


@st.cache_data(ttl=3600, show_spinner=False)
def gemini_nl_to_sql(question: str) -> tuple[str, str, str, str]:
    """Cached NL→SQL.  Returns (sql, engine, model, error)."""
    raw, engine, model, err = _llm_call(build_sql_prompt(question))
    if err:
        return "", engine, model, err
    # Strip accidental code fences
    raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE).strip().rstrip("`").strip()
    return raw, engine, model, None


def gemini_insight(question: str, sql: str, df: pd.DataFrame) -> tuple[str, str, str]:
    """Returns (insight_text, engine, model). NOT cached (depends on live df)."""
    try:
        result_md = df.head(15).to_markdown(index=False)
        prompt    = build_insight_prompt(question, sql, result_md)
        text, engine, model, err = _llm_call(prompt)
        if err:
            return f"(Insight unavailable: {err})", engine, model
        return text, engine, model
    except Exception as exc:
        return f"(Insight unavailable: {exc})", "none", "unknown"

# ─── Load sidebar filter data ─────────────────────────────────────────────────
all_outlets = qry("SELECT DISTINCT LOCATION_NAME AS outlet_name FROM AI_TEST_INVOICEBILLREGISTER ORDER BY LOCATION_NAME;")["outlet_name"].tolist()
dates_df    = qry("SELECT SUBSTR(MIN(DT), 1, 10) AS mn, SUBSTR(MAX(DT), 1, 10) AS mx FROM AI_TEST_INVOICEBILLREGISTER;")
# Apply safe fallbacks around dates so Pandas doesn't crash on empty DB 
min_date    = pd.to_datetime(dates_df["mn"].iloc[0]).date() if not dates_df["mn"].isna().all() else pd.to_datetime("2026-01-01").date()
max_date    = pd.to_datetime(dates_df["mx"].iloc[0]).date() if not dates_df["mx"].isna().all() else pd.to_datetime("2026-03-31").date()

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='text-align:center;padding:.8rem 0 1rem'>
        <div style='font-size:2.6rem'>☕</div>
        <div style='font-size:1.1rem;font-weight:800;color:#f1f5f9'>QAFFEINE</div>
        <div style='font-size:.7rem;color:#64748b;letter-spacing:.15em'>ANALYTICS · QAFFEINE COPILOT</div>
    </div>
    """, unsafe_allow_html=True)

    # ══ JARVIS INTELLIGENCE BRIEF ════════════════════════════════════════
    brief = get_intelligence_brief()
    anomaly = brief.get("revenue_anomaly", {})
    z       = anomaly.get("z_score", 0)
    acolor  = "#ef4444" if z < -1 else ("#10b981" if z > 1 else "#f59e0b")
    combo = brief.get("top_power_combo", {})
    risk = brief.get("market_risk", {})
    risk_label = risk.get('label', 'Run universal_context.py')[:110]

    st.markdown(f"""
    <div style='background:linear-gradient(135deg,rgba(245,158,11,.15),rgba(249,115,22,.1));
                border:1px solid rgba(245,158,11,.35);border-radius:14px;
                padding:.8rem 1rem;margin-bottom:.9rem'>
        <div style='font-size:.72rem;font-weight:800;color:#f59e0b;
                    letter-spacing:.1em;text-transform:uppercase;margin-bottom:.5rem'>
            ⚡ QAFFEINE Intelligence Brief
        </div>
        <div style='margin-bottom:.6rem'>
            <div style='font-size:.68rem;color:#94a3b8;font-weight:700;
                        letter-spacing:.06em;text-transform:uppercase'>📊 Revenue Anomaly</div>
            <div style='font-size:.78rem;color:{acolor};font-weight:600;
                        margin-top:.15rem;line-height:1.4'>{anomaly.get('label','Computing…')}</div>
        </div>
        <div style='margin-bottom:.6rem;
                    border-top:1px solid rgba(255,255,255,.07);padding-top:.55rem'>
            <div style='font-size:.68rem;color:#94a3b8;font-weight:700;
                        letter-spacing:.06em;text-transform:uppercase'>🎯 Top Bundle Opportunity</div>
            <div style='font-size:.78rem;color:#a5b4fc;font-weight:600;
                        margin-top:.15rem;line-height:1.4'>{combo.get('label','Run basket_analysis.py')}</div>
        </div>
        <div style='border-top:1px solid rgba(255,255,255,.07);padding-top:.55rem'>
            <div style='font-size:.68rem;color:#94a3b8;font-weight:700;
                        letter-spacing:.06em;text-transform:uppercase'>🌐 Latest Market Signal</div>
            <div style='font-size:.75rem;color:#cbd5e1;margin-top:.15rem;
                        line-height:1.45'>{risk_label}{'…' if len(risk.get('label',''))>110 else ''}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Filters ───────────────────────────────────────────────────────────
    outlet_choice = st.multiselect("Select Outlet", options=all_outlets,
                                   default=all_outlets)
    date_range = st.date_input("Date Range", value=(min_date, max_date),
                               min_value=min_date, max_value=max_date)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ══ COMMUNICATION CENTER ═════════════════════════════════════════════
    st.markdown("""
    <div style='border-top:1px solid rgba(255,255,255,.06);padding-top:.8rem;margin-top:.4rem'>
        <div style='font-size:.72rem;font-weight:800;color:#a78bfa;
                    letter-spacing:.1em;text-transform:uppercase;margin-bottom:.5rem'>
            🔔 Communication Center
        </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("📧 Send Manual Morning Brief", use_container_width=True, type="primary"):
        st.session_state["trigger_morning_brief"] = True
        st.rerun()

    # Show last 5 alerts
    alert_history = load_notification_history(last_n=5)
    if alert_history:
        st.markdown("""
        <div style='font-size:.68rem;font-weight:700;color:#64748b;
                    letter-spacing:.06em;text-transform:uppercase;margin-top:.6rem;
                    margin-bottom:.3rem'>Recent Alerts</div>
        """, unsafe_allow_html=True)
        import pandas as _pd_sidebar
        hist_df = _pd_sidebar.DataFrame(alert_history)
        if "timestamp" in hist_df.columns:
            display_cols = [c for c in ["timestamp", "anomaly_count", "email_status", "root_cause_summary"] if c in hist_df.columns]
            st.dataframe(
                hist_df[display_cols],
                use_container_width=True,
                hide_index=True,
                height=min(len(hist_df) * 40 + 40, 220),
            )
    else:
        st.markdown(
            "<div style='font-size:.72rem;color:#475569;margin-top:.4rem'>"
            "No alerts sent yet.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── Demo Mode ─────────────────────────────────────────────────────────
    DEMO_QUESTIONS = [
        "Why did revenue drop on Dec 7th at HITECH CITY? Check weather and news.",
        "What are the top 3 selling items at QAFFEINE HITECH CITY?",
        "Which outlet had the highest revenue on Dec 6th and why?",
        "Compare dine-in vs carry-out vs delivery revenue per outlet",
        "Recommend the best bundle offers based on our basket data",
    ]

    st.markdown("""
    <div style='border-top:1px solid rgba(255,255,255,.06);padding-top:.6rem;margin-top:.4rem'>
        <div style='font-size:.72rem;font-weight:700;color:#f59e0b;letter-spacing:.08em;
                    text-transform:uppercase;margin-bottom:.5rem'>🎤 Demo Mode</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("🚀 Launch Demo (5 Questions)", use_container_width=True):
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        for q in DEMO_QUESTIONS:
            already = any(e["question"] == q for e in st.session_state.chat_history)
            if not already:
                st.session_state.chat_history.append({
                    "question": q, "tool_calls": [],
                    "response": "⏳ Queued — open the AI Copilot tab to execute.",
                    "engine": "", "model": "", "monologue": [], "demo": True,
                })
        st.success("5 questions queued! Open the 🤖 AI Copilot tab.")
        st.rerun()
    st.markdown("""
    <div style='font-size:.7rem;color:#475569;padding-top:.5rem;
                border-top:1px solid rgba(255,255,255,.06)'>
        Data: 2026 · QAFFEINE Copilot v2.0<br>
        Gemini 2.0 Flash ↩ OpenRouter/Llama-3.3-70B
    </div>
    """, unsafe_allow_html=True)

if len(outlet_choice) == 0 or not isinstance(date_range, (tuple, list)) or len(date_range) < 2:
    st.warning("Please select at least one outlet and a valid date range.")
    st.stop()

date_start   = str(date_range[0])
date_end     = str(date_range[1])
outlet_ph    = ",".join("?" * len(outlet_choice))
filter_params = outlet_choice + [date_start, date_end]

# ─── Page header ──────────────────────────────────────────────────────────────
st.markdown(f"""
<div class='page-title'>☕ QAFFEINE Analytics</div>
<div class='page-sub'>Multi-Outlet Dashboard · {date_start} → {date_end} · {len(outlet_choice)} outlet(s)</div>
""", unsafe_allow_html=True)
st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

# ─── TABS ───────────────────────────────────────────────────────────────────
tab_dash, tab_ai, tab_strat, tab_notify, tab_sim, tab_health = st.tabs(
    ["📊  KPI Dashboard", "🤖  AI Copilot", "🧠  Strategic Insights",
     "🔔  Notifications", "🔮  Simulator", "🛡️  System Health"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — KPI DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    # ── KPI queries ───────────────────────────────────────────────────────────
    # We query AI_TEST_INVOICEBILLREGISTER directly instead of fact_sales for speed
    kpi = qry(f"""
        SELECT IFNULL(ROUND(SUM(NETAMT),2), 0) AS total_revenue,
               COUNT(DISTINCT TRNNO)           AS total_orders,
               IFNULL(ROUND(SUM(NETAMT)/NULLIF(COUNT(DISTINCT TRNNO),0),2), 0) AS aov,
               IFNULL(SUM(CAST(PAX AS INTEGER)), 0) AS total_pax,
               IFNULL(SUM(CASH_AMT), 0) AS cash,
               IFNULL(SUM(CARD_AMT), 0) AS card,
               IFNULL(SUM(PAYMENT_UPI), 0) AS upi
        FROM AI_TEST_INVOICEBILLREGISTER
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
    """, filter_params)

    top5 = qry(f"""
        SELECT PRODUCT_NAME AS item_name,
               IFNULL(ROUND(SUM(NET_AMT),2), 0) AS revenue,
               SUM(CAST(QTY AS REAL))           AS qty
        FROM AI_TEST_TAXCHARGED_REPORT
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
          AND PRODUCT_NAME IS NOT NULL
        GROUP BY PRODUCT_NAME ORDER BY revenue DESC LIMIT 5
    """, filter_params)

    by_outlet = qry(f"""
        SELECT LOCATION_NAME AS outlet_name, IFNULL(ROUND(SUM(NETAMT),2), 0) AS revenue,
               COUNT(DISTINCT TRNNO) AS orders
        FROM AI_TEST_INVOICEBILLREGISTER
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
        GROUP BY LOCATION_NAME ORDER BY revenue DESC
    """, filter_params)

    daily = qry(f"""
        SELECT SUBSTR(DT, 1, 10) AS date, IFNULL(ROUND(SUM(NETAMT),2), 0) AS revenue,
               COUNT(DISTINCT TRNNO) AS orders
        FROM AI_TEST_INVOICEBILLREGISTER
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
        GROUP BY SUBSTR(DT, 1, 10) ORDER BY SUBSTR(DT, 1, 10)
    """, filter_params)

    raw_df = qry(f"""
        SELECT SUBSTR(DT, 1, 10) AS date, LOCATION_NAME AS outlet_name, PRODUCT_NAME AS item_name, NET_AMT AS net_revenue, QTY AS quantity,
               ORDERTYPE_NAME AS channel, TRNNO AS bill_no, GROUP_NAME AS product_group, ORDER_STARTTIME AS kot_time
        FROM AI_TEST_TAXCHARGED_REPORT
        WHERE LOCATION_NAME IN ({outlet_ph}) AND SUBSTR(DT, 1, 10) BETWEEN ? AND ?
        ORDER BY SUBSTR(DT, 1, 10), LOCATION_NAME
    """, filter_params)

    total_revenue = float(kpi["total_revenue"].iloc[0]) if not kpi["total_revenue"].isna().all() else 0.0
    total_orders  = int(kpi["total_orders"].iloc[0])    if not kpi["total_orders"].isna().all() else 0
    aov           = float(kpi["aov"].iloc[0])           if not kpi["aov"].isna().all() else 0.0
    total_pax     = int(kpi["total_pax"].iloc[0])       if not kpi["total_pax"].isna().all() else 0
    upi           = float(kpi["upi"].iloc[0])           if not kpi["upi"].isna().all() else 0.0

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    def kpi_card(col, icon, label, value, sub):
        col.markdown(f"""
        <div class='kpi-card'>
            <div class='kpi-icon'>{icon}</div>
            <div class='kpi-label'>{label}</div>
            <div class='kpi-value'>{value}</div>
            <div class='kpi-sub'>{sub}</div>
        </div>""", unsafe_allow_html=True)

    kpi_card(c1,"💰","Revenue", f"₹{total_revenue:,.0f}", f"{len(outlet_choice)} outlet(s)")
    kpi_card(c2,"🧾","Orders", f"{total_orders:,}", "Unique bills")
    kpi_card(c3,"📈","AOV", f"₹{aov:,.0f}", "Revenue/bill")
    kpi_card(c4,"👥","PAX", f"{total_pax:,}", "Total guests")
    kpi_card(c5,"💳","UPI %", f"{(upi/total_revenue*100) if total_revenue else 0:.1f}%", "Cashless share")

    st.markdown("<div style='height:1.4rem'></div>", unsafe_allow_html=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    cl, cr = st.columns([5, 4], gap="medium")

    with cl:
        st.markdown("<div class='section-header'>📈 Daily Revenue Trend</div>", unsafe_allow_html=True)
        if not daily.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=daily["date"], y=daily["revenue"],
                mode="lines+markers", name="Revenue",
                line=dict(color="#f59e0b", width=3),
                marker=dict(size=8, color="#f97316", line=dict(color="#fff", width=1.5)),
                fill="tozeroy", fillcolor="rgba(245,158,11,0.12)",
                hovertemplate="<b>%{x}</b><br>₹%{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Bar(x=daily["date"], y=daily["orders"], name="Orders",
                yaxis="y2", marker_color="rgba(139,92,246,0.35)",
                hovertemplate="<b>%{x}</b><br>%{y} orders<extra></extra>"))
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0,r=0,t=10,b=0), height=310,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=11)),
                xaxis=dict(showgrid=False, tickfont=dict(size=11)),
                yaxis=dict(title="Revenue (₹)", showgrid=True, gridcolor="rgba(255,255,255,.06)",
                           tickformat=",.0f", tickfont=dict(size=11)),
                yaxis2=dict(title="Orders", overlaying="y", side="right", showgrid=False),
                hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

    with cr:
        st.markdown("<div class='section-header'>🏪 Revenue by Outlet</div>", unsafe_allow_html=True)
        if not by_outlet.empty:
            COLORS = ["#f59e0b","#10b981","#3b82f6","#8b5cf6","#ef4444","#06b6d4"]
            shorts = by_outlet["outlet_name"].str.replace("QAFFEINE","Q",regex=False)
            fig2 = go.Figure(go.Bar(
                x=by_outlet["revenue"], y=shorts, orientation="h",
                marker=dict(color=COLORS[:len(by_outlet)]),
                text=[f"₹{v:,.0f}" for v in by_outlet["revenue"]],
                textposition="outside", textfont=dict(size=11,color="#e2e8f0"),
                hovertemplate="<b>%{y}</b><br>₹%{x:,.0f}<extra></extra>"))
            fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=0,r=60,t=10,b=0), height=310,
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,.06)", tickformat=",.0f"),
                yaxis=dict(showgrid=False, tickfont=dict(size=10.5)))
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

    # ── Bottom row ────────────────────────────────────────────────────────────
    bl, br = st.columns(2, gap="medium")

    with bl:
        st.markdown("<div class='section-header'>🏆 Top 5 Items by Revenue</div>", unsafe_allow_html=True)
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣"]
        for i, row in top5.iterrows():
            pct = (row["revenue"] / top5["revenue"].iloc[0]) * 100
            st.markdown(f"""
            <div style='margin-bottom:.7rem;padding:.65rem .9rem;background:rgba(255,255,255,.04);
                        border-radius:10px;border:1px solid rgba(255,255,255,.07)'>
                <div style='display:flex;justify-content:space-between;align-items:center'>
                    <span style='font-size:.88rem;font-weight:600;color:#f1f5f9'>
                        {medals[i]} {row['item_name']}</span>
                    <span style='font-size:.88rem;font-weight:700;color:#f59e0b'>₹{row['revenue']:,.0f}</span>
                </div>
                <div style='margin-top:5px;background:rgba(255,255,255,.08);border-radius:4px;height:4px'>
                    <div style='width:{pct:.1f}%;background:linear-gradient(90deg,#f59e0b,#f97316);
                                height:4px;border-radius:4px'></div>
                </div>
                <div style='font-size:.68rem;color:#64748b;margin-top:2px'>
                    Qty sold: {int(row['qty']) if pd.notna(row['qty']) else "—"}
                </div>
            </div>""", unsafe_allow_html=True)

    with br:
        st.markdown("<div class='section-header'>📋 Outlet Performance Summary</div>", unsafe_allow_html=True)
        disp = by_outlet.copy()
        disp.columns = ["Outlet","Revenue (₹)","Orders"]
        disp["Revenue (₹)"] = disp["Revenue (₹)"].apply(lambda x: f"₹{x:,.2f}")
        st.dataframe(disp, use_container_width=True, hide_index=True, height=280)

    st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

    with st.expander("🗃️  View Raw Fact Sales Data", expanded=False):
        st.markdown(f"<div style='font-size:.8rem;color:#64748b;margin-bottom:.5rem'>"
                    f"<b style='color:#f1f5f9'>{len(raw_df):,}</b> rows</div>",
                    unsafe_allow_html=True)
        st.dataframe(raw_df, use_container_width=True, height=360)
        st.download_button("⬇️ Download CSV",
                           data=raw_df.to_csv(index=False).encode(),
                           file_name=f"qaffeine_{date_start}_{date_end}.csv",
                           mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — QAFFEINE COPILOT  (Agentic Multi-Tool)
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.markdown("""
    <div style='padding:.6rem 0 1rem'>
        <div style='font-size:1.5rem;font-weight:800;color:#f1f5f9'>🤖 QAFFEINE Copilot — AI Business Partner</div>
        <div style='font-size:.85rem;color:#64748b;margin-top:.2rem'>
            Agentic reasoning engine. The Copilot autonomously calls SQL, Weather, Holiday & Basket
            tools — backed by the context_intelligence DB — to find the <em>why</em> behind every number.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Suggested questions ─────────────────────────────────────────────────
    st.markdown(
        "<div style='font-size:.75rem;color:#64748b;font-weight:600;"
        "letter-spacing:.08em;text-transform:uppercase;margin-bottom:.5rem'>"
        "Try asking the Copilot:</div>",
        unsafe_allow_html=True,
    )
    suggestions = [
        "Why did revenue drop on Dec 7th? Check weather and news.",
        "Which outlet is underperforming and why?",
        "What bundles should we promote this week?",
        "Compare Hitech City vs Secunderabad revenue on Dec 6th",
        "Tell me about the Hitech City dip — investigate everything.",
        "Which items should we remove from the menu?",
    ]
    sc1, sc2, sc3 = st.columns(3)
    for i, col in enumerate([sc1, sc2, sc3, sc1, sc2, sc3]):
        if i < len(suggestions):
            col.markdown(f"""
            <div style='background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.2);
                        border-radius:8px;padding:.45rem .7rem;font-size:.75rem;color:#a5b4fc;
                        margin-bottom:.4rem;cursor:default'>
                🤖 {suggestions[i]}
            </div>""", unsafe_allow_html=True)

    st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

    # ── Chat state ───────────────────────────────────────────────────────────
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # ── Render chat history ──────────────────────────────────────────────────
    for entry in st.session_state.chat_history:
        safe_question = html.escape(str(entry.get("question", "")))
        st.markdown(
            f"<div class='chat-user'>💬 {safe_question}</div>",
            unsafe_allow_html=True,
        )

        if entry.get("error"):
            st.error(f"Copilot error: {entry['error']}")
            continue

        # ── Engine badge ──────────────────────────────────────────────────
        eng   = entry.get("engine", "")
        model = entry.get("model", "").replace("models/", "")
        if eng == "Gemini":
            badge_color, badge_icon = "#86efac", "✅"
            engine_label = f"Gemini / {model}"
        elif eng == "OpenRouter":
            badge_color, badge_icon = "#fbbf24", "⚠️"
            engine_label = f"OpenRouter ↩ {model}"
        else:
            badge_color, badge_icon = "#94a3b8", "⚡"
            engine_label = model or "QAFFEINE Copilot"

        # ── Tool calls summary ────────────────────────────────────────────
        tool_calls = entry.get("tool_calls", [])
        if tool_calls:
            tools_used = " · ".join(
                f"{tc.get('emoji','🔧')} {html.escape(str(tc.get('tool','?')))}"
                for tc in tool_calls
            )
            safe_engine_label = html.escape(engine_label)
            st.markdown(
                f"<div style='font-size:.68rem;color:#64748b;margin:.2rem 0 .3rem'>"
                f"{badge_icon} <b style='color:{badge_color}'>{safe_engine_label}</b>"
                f" &nbsp;·&nbsp; Tools: {tools_used}</div>",
                unsafe_allow_html=True,
            )

            with st.expander("🧪 View Copilot Thought Process", expanded=False):
                for step in entry.get("monologue", []):
                    icon = "✅" if step.startswith("✅") else (
                           "❌" if step.startswith("❌") else
                           "   " if step.startswith(" ") else "")
                    safe_step = html.escape(step)
                    st.markdown(
                        f"<div style='font-family:monospace;font-size:.75rem;"
                        f"color:#94a3b8;padding:.1rem 0'>{safe_step}</div>",
                        unsafe_allow_html=True,
                    )
                for tc in tool_calls:
                    with st.expander(
                        f"{tc.get('emoji','🔧')} {tc.get('tool','?')} — result",
                        expanded=False,
                    ):
                        st.code(tc.get("result", ""), language="markdown")
        elif engine_label.strip():
            safe_engine_label = html.escape(engine_label)
            st.markdown(
                f"<div style='font-size:.68rem;color:#64748b;margin:.2rem 0 .3rem'>"
                f"{badge_icon} <b style='color:{badge_color}'>{safe_engine_label}</b></div>",
                unsafe_allow_html=True,
            )

        # ── Copilot Response ───────────────────────────────────────────────
        if entry.get("response"):
            safe_response = html.escape(str(entry["response"])).replace("\n", "<br>")
            st.markdown(f"""
            <div class='chat-ai'>
                <div style='font-size:.7rem;color:#6ee7b7;font-weight:700;
                            letter-spacing:.08em;text-transform:uppercase;margin-bottom:.4rem'>
                    🤖 QAFFEINE Copilot Analysis
                </div>
                {safe_response}
            </div>""", unsafe_allow_html=True)

    # ── Chat input ───────────────────────────────────────────────────────────
    user_q = st.chat_input("Ask the Copilot anything about your business…")

    if user_q:
        entry = {"question": user_q, "tool_calls": [], "monologue": [],
                 "response": "", "engine": "", "model": "", "error": ""}

        with st.status("🤖 QAFFEINE Copilot is investigating…", expanded=True) as status:
            st.write(f'🔍 Received: "{user_q[:80]}"')

            try:
                copilot = get_copilot()
                result  = copilot.investigate(user_q)

                # Stream monologue steps into st.status
                for step in result.monologue:
                    if step.strip():
                        st.write(step)

                # Populate entry for storage
                entry["engine"]   = result.engine
                entry["model"]    = result.model
                entry["response"] = result.response
                entry["monologue"] = result.monologue
                entry["error"]    = result.error

                # Serialise tool_calls (ToolCall dataclass → plain dict)
                entry["tool_calls"] = [
                    {
                        "tool"   : tc.tool,
                        "args"   : tc.args,
                        "result" : tc.result,
                        "success": tc.success,
                        "emoji"  : tc.emoji,
                        "label"  : tc.label,
                    }
                    for tc in result.tool_calls
                ]

                n_tools = len(result.tool_calls)
                label   = (
                    f"✅ Done — {n_tools} tool{'s' if n_tools!=1 else ''} called "
                    f"via {result.engine}/{result.model.split('/')[-1]}"
                ) if not result.error else f"⚠️ Partial — {result.error[:60]}"
                status.update(label=label, state="complete", expanded=False)

            except Exception as exc:
                entry["error"] = str(exc)
                status.update(label=f"❌ Error: {exc}", state="error")

        st.session_state.chat_history.append(entry)
        st.rerun()

    # ── Clear button ─────────────────────────────────────────────────────────
    if st.session_state.chat_history:
        if st.button("🗑️  Clear chat", type="secondary"):
            st.session_state.chat_history = []
            st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — STRATEGIC INSIGHTS
# ═════════════════════════════════════════════════════════════════════════════
with tab_strat:
    import json as _json
    import pandas as pd

    st.markdown("""
    <div style='padding:.6rem 0 1rem'>
        <div style='font-size:1.5rem;font-weight:800;color:#f1f5f9'>🧠 Strategic Insights</div>
        <div style='font-size:.85rem;color:#64748b;margin-top:.2rem'>
            Market Basket Analysis · Menu Engineering Matrix · Power Combo Opportunities
        </div>
    </div>
    """, unsafe_allow_html=True)

    basket = load_basket_results()

    if not basket:
        st.warning(
            "📂 No analysis data found. Run `python scripts/basket_analysis.py` first — "
            "it will generate `database/basket_results.json`."
        )
        st.code("python QAFFEINE_Prototype/scripts/basket_analysis.py", language="bash")
    else:
        gen_at = basket.get("generated_at", "unknown")[: 19].replace("T", "  ")
        st.markdown(
            f"<div style='font-size:.72rem;color:#475569;margin-bottom:1rem'>" 
            f"Last computed: <b style='color:#94a3b8'>{gen_at}</b> · "
            f"{basket.get('total_bills',0):,} bills · "
            f"{basket.get('multi_item_bills',0):,} multi-item "
            f"({basket.get('multi_item_bills',0)/max(basket.get('total_bills',1),1)*100:.1f}%)"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ───────────────────────────────────────────────────────────────
        # SECTION 1 — Menu Engineering Scatter (4-quadrant)
        # ───────────────────────────────────────────────────────────────
        st.markdown("<div class='section-header'>📐 Menu Engineering Matrix</div>",
                    unsafe_allow_html=True)

        matrix_rows = basket.get("menu_matrix", [])
        if matrix_rows:
            df_mx = pd.DataFrame(matrix_rows)

            COLOR_MAP = {
                "Star"      : "#10b981",
                "Puzzle"    : "#3b82f6",
                "Plowhorse" : "#f59e0b",
                "Dog"       : "#ef4444",
            }
            ICON_MAP = {
                "Star": "⭐", "Puzzle": "🔮",
                "Plowhorse": "🐴", "Dog": "🐕",
            }

            # Medians for quadrant lines
            med_qty   = df_mx["total_qty"].median()
            med_price = df_mx["avg_price"].median()

            # Shorten item names for scatter labels
            df_mx["label"] = df_mx["item_name"].str[:28]
            df_mx["color"] = df_mx["quadrant"].map(COLOR_MAP)
            df_mx["icon"]  = df_mx["quadrant"].map(ICON_MAP)
            df_mx["display"] = df_mx["icon"] + " " + df_mx["quadrant"]

            fig_mx = go.Figure()

            for quad, color in COLOR_MAP.items():
                sub = df_mx[df_mx["quadrant"] == quad]
                fig_mx.add_trace(go.Scatter(
                    x=sub["total_qty"],
                    y=sub["avg_price"],
                    mode="markers",
                    name=f"{ICON_MAP[quad]} {quad}",
                    text=sub["label"],
                    textfont=dict(size=9, color="#e2e8f0"),
                    marker=dict(
                        size=sub["total_revenue"].apply(
                            lambda v: min(max(8, v / 3000), 40)
                        ),
                        color=color,
                        opacity=0.85,
                        line=dict(color="rgba(255,255,255,0.3)", width=1),
                    ),
                    hovertemplate=(
                        "<b>%{text}</b><br>"
                        "Qty sold: %{x}<br>"
                        "Avg price: ₹%{y:.0f}<br>"
                        "<extra></extra>"
                    ),
                ))

            # Quadrant divider lines
            fig_mx.add_vline(x=med_qty,   line_dash="dash",
                             line_color="rgba(255,255,255,0.2)", line_width=1)
            fig_mx.add_hline(y=med_price, line_dash="dash",
                             line_color="rgba(255,255,255,0.2)", line_width=1)

            # Quadrant labels
            x_max = df_mx["total_qty"].max() * 1.05
            y_max = df_mx["avg_price"].max() * 1.05
            y_min = df_mx["avg_price"].min() * 0.95
            for txt, xf, yf, col in [
                ("⭐ STARS\nHigh Pop · High Profit",   0.85, 0.95, "#10b981"),
                ("🔮 PUZZLES\nLow Pop · High Profit",   0.05, 0.95, "#3b82f6"),
                ("🐴 PLOWHORSES\nHigh Pop · Low Profit",0.85, 0.05, "#f59e0b"),
                ("🐕 DOGS\nLow Pop · Low Profit",       0.05, 0.05, "#ef4444"),
            ]:
                fig_mx.add_annotation(
                    xref="paper", yref="paper",
                    x=xf, y=yf, text=txt,
                    showarrow=False, align="center",
                    font=dict(size=9.5, color=col),
                    bgcolor="rgba(0,0,0,0.4)",
                    bordercolor=col, borderwidth=1, borderpad=4,
                )

            fig_mx.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=20, b=0),
                height=520,
                xaxis=dict(
                    title="Popularity (Qty Sold)",
                    showgrid=True, gridcolor="rgba(255,255,255,.06)",
                ),
                yaxis=dict(
                    title="Profitability (Avg Price ₹)",
                    showgrid=True, gridcolor="rgba(255,255,255,.06)",
                ),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.01,
                    font=dict(size=11),
                ),
                hovermode="closest",
            )
            st.plotly_chart(fig_mx, use_container_width=True)

            # Quadrant summary KPI strip
            qcols = st.columns(4)
            for ci, (quad, icon, color) in enumerate([
                ("Star",     "⭐", "#10b981"),
                ("Puzzle",   "🔮", "#3b82f6"),
                ("Plowhorse","🐴", "#f59e0b"),
                ("Dog",      "🐕", "#ef4444"),
            ]):
                n = len(df_mx[df_mx["quadrant"] == quad])
                rev = df_mx[df_mx["quadrant"] == quad]["total_revenue"].sum()
                qcols[ci].markdown(f"""
                <div style='background:rgba(255,255,255,.04);border:1px solid {color}40;
                            border-radius:12px;padding:.9rem 1rem;text-align:center'>
                    <div style='font-size:1.4rem'>{icon}</div>
                    <div style='font-size:.75rem;font-weight:700;color:{color};
                                letter-spacing:.06em;text-transform:uppercase'>{quad}</div>
                    <div style='font-size:1.3rem;font-weight:800;color:#f1f5f9'>{n}</div>
                    <div style='font-size:.7rem;color:#64748b'>items</div>
                    <div style='font-size:.8rem;color:{color};font-weight:600;
                                margin-top:.2rem'>₹{rev:,.0f}</div>
                    <div style='font-size:.65rem;color:#475569'>revenue</div>
                </div>""", unsafe_allow_html=True)

        st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

        # ───────────────────────────────────────────────────────────────
        # SECTION 2 — Power Combos table
        # ───────────────────────────────────────────────────────────────
        col_combo, col_pairs = st.columns([3, 2], gap="large")

        with col_combo:
            st.markdown("<div class='section-header'>🎯 Top Power Combo Recommendations</div>",
                        unsafe_allow_html=True)

            combos = basket.get("power_combos", [])
            if combos:
                QUAD_COLOR = {
                    "Star": "#10b981", "Puzzle": "#3b82f6",
                    "Plowhorse": "#f59e0b", "Dog": "#ef4444", "Unknown": "#64748b",
                }
                QUAD_ICON = {
                    "Star": "⭐", "Puzzle": "🔮",
                    "Plowhorse": "🐴", "Dog": "🐕", "Unknown": "?",
                }

                df_combo = pd.DataFrame(combos)

                # Styled card for each combo
                for i, c in enumerate(combos, 1):
                    qa, qb = c["quad_a"], c["quad_b"]
                    ca, cb = QUAD_COLOR.get(qa, "#64748b"), QUAD_COLOR.get(qb, "#64748b")
                    ia, ib = QUAD_ICON.get(qa, "?"), QUAD_ICON.get(qb, "?")
                    aov_col = "#10b981" if c["aov_lift_pct"] > 0 else "#ef4444"
                    st.markdown(f"""
                    <div style='background:rgba(255,255,255,.04);
                                border:1px solid rgba(255,255,255,.1);
                                border-radius:14px;padding:1rem 1.2rem;
                                margin-bottom:.8rem'>
                        <div style='display:flex;justify-content:space-between;
                                    align-items:flex-start;margin-bottom:.5rem'>
                            <div style='font-size:.95rem;font-weight:700;
                                        color:#f1f5f9;max-width:70%'>
                                #{i} &nbsp; {c['item_a'][:30]} &nbsp;
                                <span style='color:#64748b'>+</span> &nbsp;
                                {c['item_b'][:30]}
                            </div>
                            <div style='font-size:1rem;font-weight:800;
                                        color:{aov_col};white-space:nowrap'>
                                +{c['aov_lift_pct']:.1f}% AOV
                            </div>
                        </div>
                        <div style='display:flex;gap:.6rem;flex-wrap:wrap;
                                    font-size:.72rem;margin-bottom:.5rem'>
                            <span style='background:{ca}22;color:{ca};
                                         border:1px solid {ca}55;
                                         padding:.15rem .5rem;border-radius:6px'>
                                {ia} {qa}
                            </span>
                            <span style='background:{cb}22;color:{cb};
                                         border:1px solid {cb}55;
                                         padding:.15rem .5rem;border-radius:6px'>
                                {ib} {qb}
                            </span>
                            <span style='background:rgba(255,255,255,.06);
                                         color:#94a3b8;padding:.15rem .5rem;
                                         border-radius:6px'>
                                Lift {c['lift']:.2f}x
                            </span>
                            <span style='background:rgba(255,255,255,.06);
                                         color:#94a3b8;padding:.15rem .5rem;
                                         border-radius:6px'>
                                {c['co_count']}× co-purchased
                            </span>
                        </div>
                        <div style='font-size:.8rem;color:#cbd5e1'>
                            Individual: ₹{c['price_a']:.0f} + ₹{c['price_b']:.0f}
                            &nbsp;→&nbsp;
                            <b style='color:#f59e0b'>Bundle: ₹{c['bundle_price']:.0f}</b>
                            &nbsp; (save ₹{c['regular_aov']-c['bundle_price']:.0f})
                        </div>
                    </div>""", unsafe_allow_html=True)

                # Downloadable table
                display_df = pd.DataFrame([{
                    "Combo": f"{c['item_a'][:24]} + {c['item_b'][:24]}",
                    "Lift":         c["lift"],
                    "Co-purchased": c["co_count"],
                    "Bundle (₹)":   c["bundle_price"],
                    "AOV Lift %":   c["aov_lift_pct"],
                } for c in combos])
                st.download_button(
                    "⬇️ Download Power Combos CSV",
                    display_df.to_csv(index=False).encode(),
                    file_name="power_combos.csv",
                    mime="text/csv",
                )

        # ── Right column: Top Affinity Pairs ──────────────────────────────
        with col_pairs:
            st.markdown("<div class='section-header'>🔗 Top Product Affinities</div>",
                        unsafe_allow_html=True)

            affinity = basket.get("affinity_pairs", [])[:12]
            if affinity:
                for p in affinity:
                    lift      = p["lift"]
                    lift_pct  = min(lift / 15, 1.0)     # normalise bar to max ~15x
                    bar_color = (
                        "#10b981" if lift > 10 else
                        "#f59e0b" if lift > 3  else "#64748b"
                    )
                    a_short = p["item_a"][:26]
                    b_short = p["item_b"][:26]
                    st.markdown(f"""
                    <div style='margin-bottom:.65rem;
                                padding:.55rem .8rem;
                                background:rgba(255,255,255,.03);
                                border-radius:9px;
                                border:1px solid rgba(255,255,255,.06)'>
                        <div style='font-size:.75rem;font-weight:600;
                                    color:#e2e8f0;margin-bottom:.3rem'>
                            {a_short}
                            <span style='color:#64748b'> ⇔ </span>
                            {b_short}
                        </div>
                        <div style='display:flex;align-items:center;gap:.5rem'>
                            <div style='flex:1;background:rgba(255,255,255,.08);
                                        border-radius:4px;height:5px'>
                                <div style='width:{lift_pct*100:.0f}%;
                                            background:{bar_color};
                                            height:5px;border-radius:4px'>
                                </div>
                            </div>
                            <div style='font-size:.72rem;font-weight:700;
                                        color:{bar_color};white-space:nowrap'>
                                {lift:.1f}x lift
                            </div>
                            <div style='font-size:.68rem;color:#475569;
                                        white-space:nowrap'>
                                {p['co_count']}×
                            </div>
                        </div>
                    </div>""", unsafe_allow_html=True)

        st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

        # ───────────────────────────────────────────────────────────────
        # SECTION 3 — Full matrix table
        # ───────────────────────────────────────────────────────────────
        with st.expander("📊  Full Menu Engineering Table (all items)", expanded=False):
            if matrix_rows:
                df_full = pd.DataFrame(matrix_rows)[[
                    "quadrant", "icon", "item_name",
                    "total_qty", "avg_price", "total_revenue", "action",
                ]].copy()
                df_full["Quadrant"]  = df_full["icon"] + " " + df_full["quadrant"]
                df_full["Item"]      = df_full["item_name"]
                df_full["Qty Sold"]  = df_full["total_qty"].astype(int)
                df_full["Avg Price"] = df_full["avg_price"].apply(lambda x: f"₹{x:.0f}")
                df_full["Revenue"]   = df_full["total_revenue"].apply(lambda x: f"₹{x:,.0f}")
                df_full["Action"]    = df_full["action"]
                st.dataframe(
                    df_full[["Quadrant","Item","Qty Sold","Avg Price","Revenue","Action"]],
                    use_container_width=True, hide_index=True, height=420,
                )
                st.download_button(
                    "⬇️ Download Full Matrix CSV",
                    df_full[["Quadrant","Item","Qty Sold","Avg Price","Revenue","Action"]]
                    .to_csv(index=False).encode(),
                    file_name="menu_matrix.csv",
                    mime="text/csv",
                )

        with st.expander("🛠️  Refresh Analysis Data", expanded=False):
            st.markdown(
                "<div style='font-size:.82rem;color:#94a3b8'>" 
                "Run the basket analysis script to recompute all metrics "
                "from the latest sales data:</div>",
                unsafe_allow_html=True,
            )
            st.code(
                "python QAFFEINE_Prototype/scripts/basket_analysis.py",
                language="bash",
            )
            if st.button("🔄  Recompute Now", type="primary"):
                import subprocess, sys as _sys
                script = str(_BASE_DIR / "scripts" / "basket_analysis.py")
                result = subprocess.run(
                    [_sys.executable, script],
                    capture_output=True, text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    st.success("✅ Analysis complete! Refresh the page to see updated data.")
                    load_basket_results.clear()   # bust cache
                else:
                    st.error(f"❌ Script error:\n{result.stderr[:600]}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — NOTIFICATION CENTER
# ══════════════════════════════════════════════════════════════════════════════
with tab_notify:
    import json as _jn
    import datetime as _dt_notify

    st.markdown("""
    <div style='padding:.6rem 0 1rem'>
        <div style='font-size:1.5rem;font-weight:800;color:#f1f5f9'>🔔 Notification Center</div>
        <div style='font-size:.85rem;color:#64748b;margin-top:.2rem'>
            Proactive Diagnostics · Anomaly Engine · Automated Briefings
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Morning Brief Pipeline ────────────────────────────────────────────
    nc1, nc2 = st.columns([3, 2], gap="medium")

    with nc1:
        st.markdown("<div class='section-header'>📧 Morning Brief Pipeline</div>",
                    unsafe_allow_html=True)

        st.markdown("""
        <div style='font-size:.82rem;color:#94a3b8;margin-bottom:1rem;line-height:1.6'>
            The Morning Brief pipeline runs the full diagnostic chain:<br>
            <b style='color:#f59e0b'>①</b> Anomaly Scan (Z-Score) →
            <b style='color:#a78bfa'>②</b> Root-Cause Diagnosis (LLM + Weather/News/Holiday) →
            <b style='color:#10b981'>③</b> Recovery Recommendation (Basket Analysis) →
            <b style='color:#3b82f6'>④</b> HTML Email Dispatch
        </div>
        """, unsafe_allow_html=True)

        send_btn = st.button(
            "📧 Generate & Send Morning Brief",
            use_container_width=True,
            type="primary",
            key="send_brief_main",
        )

        # Also check the sidebar trigger
        sidebar_trigger = st.session_state.pop("trigger_morning_brief", False)

        if send_btn or sidebar_trigger:
            with st.status("🤖 QAFFEINE Copilot — Morning Brief Pipeline", expanded=True) as brief_status:
                import time as _time

                # ── Step 1: Anomaly Scan ───────────────────────────────
                st.write("🔍 **Step 1/4** — Scanning for revenue anomalies...")
                try:
                    anomalies_raw = detect_anomalies_all_outlets()
                    anomalies_dicts = [a.to_dict() for a in anomalies_raw]
                    st.write(f"   Found **{len(anomalies_raw)}** anomal{'y' if len(anomalies_raw)==1 else 'ies'}")
                    if anomalies_raw:
                        st.toast(f"🔍 {len(anomalies_raw)} anomalies detected", icon="📊")
                except Exception as exc:
                    st.error(f"Anomaly scan error: {exc}")
                    anomalies_raw = []
                    anomalies_dicts = []

                # ── Step 2: Root-Cause Diagnosis ───────────────────────
                st.write("🧠 **Step 2/4** — Generating root-cause diagnosis...")
                diagnosis_paragraphs = []
                if anomalies_raw:
                    try:
                        llm = get_llm()
                        diagnosis_paragraphs = generate_anomaly_diagnosis(
                            anomalies_raw, llm=llm
                        )
                        st.write(f"   Generated **{len(diagnosis_paragraphs)}** diagnosis paragraph(s)")
                        st.toast("🧠 Diagnosis complete", icon="✅")
                    except Exception as exc:
                        st.warning(f"Diagnosis generation error: {exc}")
                        diagnosis_paragraphs = []
                else:
                    st.write("   No anomalies to diagnose — all outlets within normal range.")

                # ── Step 3: Recovery Recommendation ────────────────────
                st.write("🎯 **Step 3/4** — Computing recovery bundle recommendations...")
                recommendations = ""
                try:
                    recommendations = _tool_compute_live_basket(
                        outlet_filter="", date_from="", date_to="",
                        group_filter="", top_n=5,
                    )
                    st.write("   Recovery bundles computed ✓")
                    st.toast("🎯 Recovery bundles ready", icon="📦")
                except Exception as exc:
                    st.warning(f"Basket analysis error: {exc}")

                # ── Step 4: Email Dispatch ─────────────────────────────
                st.write("📧 **Step 4/4** — Generating HTML brief & sending email...")
                try:
                    success, msg = send_morning_brief(
                        anomalies            = anomalies_dicts,
                        diagnosis_paragraphs = diagnosis_paragraphs,
                        recommendations      = recommendations,
                    )
                    if success:
                        st.toast("📧 Email sent successfully!", icon="✅")
                        st.write(f"   ✅ {msg}")
                        brief_status.update(
                            label="✅ Morning Brief sent successfully!",
                            state="complete", expanded=False,
                        )
                    else:
                        st.warning(f"📧 {msg}")
                        st.write("   ⚠️ Email not sent — but the brief was generated.")

                        # Still log as generated (even if email failed)
                        log_notification(
                            timestamp=_dt_notify.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            anomaly_count=len(anomalies_dicts),
                            outlets_flagged=", ".join(set(a.get("outlet_name","") for a in anomalies_dicts)),
                            root_cause="; ".join(d.get("diagnosis","")[:60] for d in diagnosis_paragraphs),
                            email_status=f"GENERATED (email: {msg[:60]})",
                        )
                        brief_status.update(
                            label=f"⚠️ Brief generated — email: {msg[:50]}",
                            state="complete", expanded=False,
                        )
                except Exception as exc:
                    st.error(f"Dispatch error: {exc}")
                    brief_status.update(
                        label=f"❌ Error: {exc}",
                        state="error",
                    )

            st.rerun()

    # ── Right column: Live Anomaly Scan ──────────────────────────────────
    with nc2:
        st.markdown("<div class='section-header'>📊 Live Anomaly Scan</div>",
                    unsafe_allow_html=True)

        try:
            live_anomalies = detect_anomalies_all_outlets()
            if live_anomalies:
                for a in live_anomalies[:8]:
                    sev_color = "#ef4444" if a.severity == "CRITICAL" else "#f59e0b"
                    sev_bg    = "#ef444415" if a.severity == "CRITICAL" else "#f59e0b15"
                    st.markdown(f"""
                    <div style='background:{sev_bg};border:1px solid {sev_color}30;
                                border-radius:10px;padding:.65rem .9rem;margin-bottom:.5rem'>
                        <div style='display:flex;justify-content:space-between;align-items:center'>
                            <span style='font-size:.82rem;font-weight:600;color:#f1f5f9'>
                                {a.outlet_name[:22]}
                            </span>
                            <span style='font-size:.72rem;font-weight:700;color:{sev_color};
                                         background:{sev_bg};padding:2px 8px;border-radius:12px;
                                         border:1px solid {sev_color}40'>
                                Z = {a.z_score:.2f}
                            </span>
                        </div>
                        <div style='font-size:.72rem;color:#94a3b8;margin-top:.2rem'>
                            {a.date} · ₹{a.revenue:,.0f} · {a.pct_deviation:+.1f}% vs baseline
                        </div>
                    </div>""", unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style='background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);
                            border-radius:12px;padding:1.2rem;text-align:center'>
                    <div style='font-size:1.4rem;margin-bottom:.3rem'>✅</div>
                    <div style='font-size:.88rem;font-weight:700;color:#10b981'>All Clear</div>
                    <div style='font-size:.75rem;color:#64748b;margin-top:.2rem'>
                        No revenue anomalies detected across outlet network
                    </div>
                </div>""", unsafe_allow_html=True)
        except Exception as exc:
            st.error(f"Anomaly scan error: {exc}")

    st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

    # ── Alert History Table ──────────────────────────────────────────────
    st.markdown("<div class='section-header'>📋 Alert History (Last 5 Sent)</div>",
                unsafe_allow_html=True)

    history = load_notification_history(last_n=5)
    if history:
        hist_df = pd.DataFrame(history)
        display_cols = [c for c in [
            "timestamp", "anomaly_count", "outlets_flagged",
            "root_cause_summary", "email_status",
        ] if c in hist_df.columns]

        # Rename for display
        rename_map = {
            "timestamp": "Time",
            "anomaly_count": "Anomalies",
            "outlets_flagged": "Outlets",
            "root_cause_summary": "Root Cause",
            "email_status": "Status",
        }
        disp = hist_df[display_cols].rename(columns=rename_map)
        st.dataframe(disp, use_container_width=True, hide_index=True, height=240)
    else:
        st.markdown("""
        <div style='background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
                    border-radius:12px;padding:2rem;text-align:center'>
            <div style='font-size:1.2rem;margin-bottom:.3rem'>📭</div>
            <div style='font-size:.85rem;color:#64748b'>No alerts sent yet.</div>
            <div style='font-size:.75rem;color:#475569;margin-top:.3rem'>
                Click "Send Manual Morning Brief" to trigger the first diagnostic run.
            </div>
        </div>""", unsafe_allow_html=True)

    # ── Email Preview (last generated) ──────────────────────────────────
    with st.expander("👁️ Preview Last Email Template", expanded=False):
        preview_path = _BASE_DIR / "logs" / "test_email_preview.html"
        if preview_path.exists():
            st.components.v1.html(
                preview_path.read_text(encoding="utf-8"),
                height=800,
                scrolling=True,
            )
        else:
            st.info("No email preview available. Run the morning brief to generate one.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — SIMULATOR (What-If Situation Room)
# ══════════════════════════════════════════════════════════════════════════════
with tab_sim:
    import datetime as _dt_sim

    st.markdown("""
    <div style='padding:.6rem 0 .4rem'>
        <div style='font-size:1.5rem;font-weight:800;color:#f1f5f9'>🔮 Revenue Situation Room</div>
        <div style='font-size:.85rem;color:#64748b;margin-top:.2rem'>
            ML-powered "What-If" engine · Natural language or manual controls
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not _FORECASTER_READY:
        st.warning("🤖 Forecaster model not trained yet.")
        st.code("python QAFFEINE_Prototype/scripts/forecaster.py", language="bash")
        if st.button("🚀 Train Model Now", type="primary", key="train_model_btn"):
            import subprocess as _sp_sim
            with st.status("🧠 Training revenue forecaster...", expanded=True) as ts:
                script = str(_BASE_DIR / "scripts" / "forecaster.py")
                r = _sp_sim.run([sys.executable, script], capture_output=True, text=True)
                if r.returncode == 0:
                    st.toast("✅ Model trained!", icon="🎯")
                    ts.update(label="✅ Model trained!", state="complete")
                    st.rerun()
                else:
                    st.error(f"Training failed:\n{r.stderr[:500]}")
                    ts.update(label="❌ Training failed", state="error")
    else:
        # ────────────────────────────────────────────────────────────────────
        # SECTION A: Natural Language Scenario Chat
        # ────────────────────────────────────────────────────────────────────
        st.markdown("<div class='section-header'>💬 Scenario Chat</div>",
                    unsafe_allow_html=True)

        scenario_text = st.text_input(
            "Describe a scenario",
            placeholder="e.g. 'Heavy rain on a Friday at Bhooja' or 'Thunderstorm at Hitech City this Saturday'",
            key="scenario_chat_input",
            label_visibility="collapsed",
        )

        # Process natural language scenario
        if scenario_text and scenario_text.strip():
            if scenario_text != st.session_state.get("last_scenario_text", ""):
                with st.status("🧠 QAFFEINE Copilot is interpreting your scenario...", expanded=True) as parse_status:
                    parsed = interpret_scenario_prompt(scenario_text)
                    st.write(f"🏪 **Outlet:** {parsed['outlet']}")
                    st.write(f"🌧️ **Rain:** {parsed['rain_mm']}mm  |  🌡️ **Temp:** {parsed['temp_c']}°C")
                    st.write(f"📅 **Date:** {parsed['date']}  |  🧠 **Parsed via:** {parsed.get('parse_method', 'N/A')}")
                    parse_status.update(label="✅ Scenario parsed!", state="complete")

                # Apply parsed params to session state for the control panel
                st.session_state.last_scenario_text = scenario_text
                
                # Check if outlet exists before applying
                if parsed["outlet"] in FORECAST_OUTLETS:
                    st.session_state.sim_outlet = parsed["outlet"]
                st.session_state.sim_rain = int(parsed["rain_mm"])
                st.session_state.sim_temp = int(parsed["temp_c"])
                try:
                    st.session_state.sim_date = _dt_sim.date.fromisoformat(parsed["date"])
                except Exception:
                    pass
                st.rerun()

        st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

        # ────────────────────────────────────────────────────────────────────
        # SECTION B: Manual Control Panel
        # ────────────────────────────────────────────────────────────────────
        st.markdown("<div class='section-header'>🎮 Manual Controls</div>",
                    unsafe_allow_html=True)

        sim_c1, sim_c2, sim_c3, sim_c4 = st.columns([2, 2, 1.5, 1.5])

        with sim_c1:
            sim_outlet = st.selectbox(
                "🏪 Outlet", options=FORECAST_OUTLETS, key="sim_outlet",
            )
        with sim_c2:
            sim_date = st.date_input("📅 Date", value=_dt_sim.date(2025, 12, 6), key="sim_date")

        with sim_c3:
            sim_rain = st.slider("🌧️ Rainfall (mm)", 0, 50, 0, 1, key="sim_rain")
        with sim_c4:
            sim_temp = st.slider("🌡️ Temperature (°C)", 15, 45, 28, 1, key="sim_temp")

        # Quick presets
        preset_cols = st.columns(5)
        presets = [
            ("☀️ Sunny", 0, 30), ("🌤️ Cloudy", 2, 28),
            ("🌧️ Light Rain", 5, 25), ("⛈️ Storm", 15, 22),
            ("🌊 Heavy Rain", 30, 20),
        ]
        for i, (label, rain, temp) in enumerate(presets):
            if preset_cols[i].button(label, key=f"preset_{i}", use_container_width=True):
                st.session_state.sim_rain = rain
                st.session_state.sim_temp = temp
                st.session_state.last_scenario_text = ""
                st.rerun()

        st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

        # ────────────────────────────────────────────────────────────────────
        # SECTION C: Prediction Results
        # ────────────────────────────────────────────────────────────────────
        date_str = str(sim_date)
        result = predict_revenue(
            sim_outlet, date_str,
            rain_mm=float(sim_rain), temp_c=float(sim_temp)
        )

        if "error" in result:
            st.error(f"Prediction error: {result['error']}")
        else:
            pred  = result["predicted_revenue"]
            base  = result["baseline_revenue"]
            delta = result["delta_pct"]
            cond  = result["conditions"]

            # ── KPI Metrics (standard st.metric) ─────────────────────────────
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(
                "🔮 Predicted Revenue",
                f"₹{pred:,.0f}",
                f"{delta:+.1f}% vs sunny baseline",
                delta_color="inverse" if delta < 0 else "normal",
            )
            m2.metric("☀️ Baseline (Sunny Day)", f"₹{base:,.0f}")

            impact = ("🟢 Low" if abs(delta) < 5
                      else ("🟡 Moderate" if abs(delta) < 15 else "🔴 High"))
            m3.metric("⚡ Impact Level", impact,
                      f"₹{pred - base:+,.0f}",
                      delta_color="inverse" if delta < 0 else "normal")

            day_label = result['day_of_week']
            wkend = "📅 Weekend" if cond['is_weekend'] else ""
            hol   = "🗓️ Holiday" if cond['is_holiday'] else ""
            m4.metric("📆 Day", f"{day_label}", f"{wkend} {hol}".strip() or "Weekday")

            st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

            # ── 24-Hour Trend Area Chart ───────────────────────────────────
            st.markdown("<div class='section-header'>📈 24-Hour Revenue Forecast</div>",
                        unsafe_allow_html=True)

            trend_df = generate_hourly_trend(pred, base, rain_mm=float(sim_rain))
            chart_df = trend_df.set_index("Hour")

            st.area_chart(
                chart_df,
                use_container_width=True,
                height=320,
                color=["#8b5cf6", "#f59e0b"],
            )

            # Legend
            st.markdown("""
            <div style='display:flex;gap:2rem;justify-content:center;margin-top:-.5rem;margin-bottom:1rem'>
                <span style='font-size:.75rem;color:#a78bfa'>● Predicted (Scenario)</span>
                <span style='font-size:.75rem;color:#f59e0b'>● Baseline (Sunny Day)</span>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

            # ── Narrative Analysis ─────────────────────────────────────────
            st.markdown("<div class='section-header'>🧠 QAFFEINE Copilot Narrative Analysis</div>",
                        unsafe_allow_html=True)

            # Build narrative context
            scenario_desc = scenario_text if scenario_text else f"{sim_rain}mm rain, {sim_temp}°C"
            narrative_prompt = f"""You are QAFFEINE Copilot, an elite coffee-chain business strategist.

A revenue simulation was run for {result['outlet']} on {result['day_of_week']}, {date_str}.
Scenario: {scenario_desc}
Conditions: {sim_rain}mm rainfall, {sim_temp}°C temperature.
{'This is a WEEKEND.' if cond['is_weekend'] else 'This is a weekday.'}
{'This is a PUBLIC HOLIDAY.' if cond['is_holiday'] else ''}

Results:
- Predicted Revenue: ₹{pred:,.0f}
- Sunny Baseline: ₹{base:,.0f}
- Delta: {delta:+.1f}%

In 3-4 sentences:
1. Explain WHY this weather scenario impacts revenue (be specific about customer behavior,
   footfall patterns, delivery vs dine-in shifts).
2. Give ONE specific, actionable inventory OR marketing suggestion to mitigate the risk
   (or capitalize on the opportunity if positive).

Be concise, strategic, and data-driven. Use specific numbers from the simulation."""

            @st.cache_data(ttl=120, show_spinner=False)
            def _get_narrative(prompt_text):
                try:
                    llm = LLMManager()
                    r = llm.generate(prompt_text)
                    return r.text, r.engine
                except Exception as exc:
                    return None, str(exc)

            narrative_text, narrative_engine = _get_narrative(narrative_prompt)

            if narrative_text:
                st.markdown(f"""
                <div style='background:rgba(139,92,246,.06);border:1px solid rgba(139,92,246,.2);
                            border-radius:14px;padding:1.2rem 1.5rem;margin-bottom:1rem'>
                    <div style='font-size:.7rem;color:#a78bfa;font-weight:700;
                                letter-spacing:.06em;text-transform:uppercase;
                                margin-bottom:.5rem'>
                        🧠 Copilot Analysis · via {narrative_engine}
                    </div>
                    <div style='font-size:.85rem;color:#e2e8f0;line-height:1.65'>
                        {narrative_text}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Narrative analysis unavailable. LLM could not be reached.")

            # ── Model info expander ───────────────────────────────────────
            with st.expander("🧠 Model Information", expanded=False):
                try:
                    art = load_model()
                    metrics = art.get("metrics", {})
                    st.markdown(f"""
                    - **Model**: RandomForestRegressor (200 trees, max_depth=12)
                    - **CV R² Score**: {metrics.get('cv_r2_mean', 'N/A')}
                    - **Training Samples**: {metrics.get('n_samples', 'N/A')}
                    - **Trained At**: {metrics.get('trained_at', 'N/A')[:19]}
                    - **Top Features**: {', '.join(list(metrics.get('feature_importance', {}).keys())[:5])}
                    """)
                except Exception as exc:
                    st.info(f"Could not load model metadata: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SYSTEM HEALTH
# ══════════════════════════════════════════════════════════════════════════════
with tab_health:
    import time as _time_health

    st.markdown("""
    <div style='padding:.6rem 0 1rem'>
        <div style='font-size:1.5rem;font-weight:800;color:#f1f5f9'>🛡️ System Health & Resilience</div>
        <div style='font-size:.85rem;color:#64748b;margin-top:.2rem'>
            LLM Latency · API Status · Chaos Monkey Results
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── System Vitals ────────────────────────────────────────────────────
    st.markdown("<div class='section-header'>⚡ System Vitals</div>",
                unsafe_allow_html=True)

    v1, v2, v3, v4 = st.columns(4)

    # Database check
    try:
        db_t0 = _time_health.time()
        test_conn = sqlite3.connect(str(DB_PATH), timeout=3)
        test_conn.execute("SELECT 1 FROM AI_TEST_INVOICEBILLREGISTER LIMIT 1").fetchone()
        test_conn.close()
        db_ms = (_time_health.time() - db_t0) * 1000
        v1.markdown(f"""
        <div style='background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);
                    border-radius:12px;padding:1rem;text-align:center'>
            <div style='font-size:1.2rem'>🗄️</div>
            <div style='font-size:.75rem;font-weight:700;color:#10b981'>DATABASE</div>
            <div style='font-size:1.1rem;font-weight:800;color:#f1f5f9'>✅ Online</div>
            <div style='font-size:.7rem;color:#64748b'>{db_ms:.0f}ms latency</div>
        </div>""", unsafe_allow_html=True)
    except Exception as exc:
        v1.markdown(f"""
        <div style='background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.25);
                    border-radius:12px;padding:1rem;text-align:center'>
            <div style='font-size:1.2rem'>🗄️</div>
            <div style='font-size:.75rem;font-weight:700;color:#ef4444'>DATABASE</div>
            <div style='font-size:1.1rem;font-weight:800;color:#ef4444'>❌ Offline</div>
            <div style='font-size:.7rem;color:#64748b'>{str(exc)[:30]}</div>
        </div>""", unsafe_allow_html=True)

    # LLM check (Gemini)
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    gemini_status = "✅ Key Present" if gemini_key else "❌ Missing"
    gemini_color  = "#10b981" if gemini_key else "#ef4444"
    v2.markdown(f"""
    <div style='background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.25);
                border-radius:12px;padding:1rem;text-align:center'>
        <div style='font-size:1.2rem'>🧠</div>
        <div style='font-size:.75rem;font-weight:700;color:#6366f1'>GEMINI (PRIMARY)</div>
        <div style='font-size:1.1rem;font-weight:800;color:{gemini_color}'>{gemini_status}</div>
        <div style='font-size:.7rem;color:#64748b'>gemini-2.0-flash</div>
    </div>""", unsafe_allow_html=True)

    # OpenRouter check
    or_key = os.getenv("OPENROUTER_API_KEY", "")
    or_status = "✅ Key Present" if or_key else "❌ Missing"
    or_color  = "#10b981" if or_key else "#ef4444"
    v3.markdown(f"""
    <div style='background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);
                border-radius:12px;padding:1rem;text-align:center'>
        <div style='font-size:1.2rem'>🔄</div>
        <div style='font-size:.75rem;font-weight:700;color:#f59e0b'>OPENROUTER (BACKUP)</div>
        <div style='font-size:1.1rem;font-weight:800;color:{or_color}'>{or_status}</div>
        <div style='font-size:.7rem;color:#64748b'>llama-3.3-70b</div>
    </div>""", unsafe_allow_html=True)

    # Forecaster check
    model_status = "✅ Loaded" if _FORECASTER_READY else "❌ Not Trained"
    model_color  = "#10b981" if _FORECASTER_READY else "#ef4444"
    v4.markdown(f"""
    <div style='background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.25);
                border-radius:12px;padding:1rem;text-align:center'>
        <div style='font-size:1.2rem'>🔮</div>
        <div style='font-size:.75rem;font-weight:700;color:#8b5cf6'>ML FORECASTER</div>
        <div style='font-size:1.1rem;font-weight:800;color:{model_color}'>{model_status}</div>
        <div style='font-size:.7rem;color:#64748b'>RandomForest</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

    # ── Chaos Monkey ─────────────────────────────────────────────────────
    ch_left, ch_right = st.columns([3, 2], gap="medium")

    with ch_left:
        st.markdown("<div class='section-header'>🐒 Chaos Monkey — Resilience Suite</div>",
                    unsafe_allow_html=True)

        st.markdown("""
        <div style='font-size:.82rem;color:#94a3b8;margin-bottom:1rem;line-height:1.6'>
            The Chaos Monkey injects controlled failures to verify system resilience:<br>
            <b style='color:#ef4444'>A</b> API Blackout (Weather/News → 401/Timeout) ·
            <b style='color:#f59e0b'>B</b> LLM Failover (Gemini → 429 Quota) ·
            <b style='color:#3b82f6'>C</b> Database Lock (5s SQLite lock)
        </div>
        """, unsafe_allow_html=True)

        if _CHAOS_READY:
            if st.button("🐒 Run Chaos Monkey Suite", type="primary",
                         use_container_width=True, key="chaos_btn"):
                with st.status("🐒 Chaos Monkey running...", expanded=True) as cs:
                    try:
                        results = run_all_scenarios()
                        passed = sum(1 for r in results if r.success)
                        total  = len(results)

                        for r in results:
                            icon = "✅" if r.success else "❌"
                            st.write(f"{icon} **{r.scenario}** — {r.recovery}")

                        if passed == total:
                            cs.update(label=f"✅ All {total} scenarios passed!",
                                      state="complete")
                            st.toast("🐒 All chaos tests passed!", icon="✅")
                        else:
                            cs.update(label=f"⚠️ {passed}/{total} passed",
                                      state="complete")
                    except Exception as exc:
                        st.error(f"Chaos Monkey error: {exc}")
                        cs.update(label=f"❌ Error: {exc}", state="error")

                st.rerun()
        else:
            st.warning("Chaos Monkey module not available.")

    with ch_right:
        st.markdown("<div class='section-header'>📋 Last Chaos Events</div>",
                    unsafe_allow_html=True)

        if _CHAOS_READY:
            events = get_chaos_history()
            if events:
                for ev in events:
                    ev_color = "#10b981" if ev["status"] == "PASS" else "#ef4444"
                    ev_bg    = "#10b98110" if ev["status"] == "PASS" else "#ef444410"
                    ev_icon  = "✅" if ev["status"] == "PASS" else "❌"
                    st.markdown(f"""
                    <div style='background:{ev_bg};border:1px solid {ev_color}30;
                                border-radius:10px;padding:.65rem .9rem;margin-bottom:.5rem'>
                        <div style='font-size:.82rem;font-weight:600;color:#f1f5f9'>
                            {ev_icon} {ev['summary'][:80]}
                        </div>
                    </div>""", unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style='background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
                            border-radius:12px;padding:1.5rem;text-align:center'>
                    <div style='font-size:1.2rem;margin-bottom:.3rem'>🐒</div>
                    <div style='font-size:.85rem;color:#64748b'>No chaos tests run yet.</div>
                    <div style='font-size:.75rem;color:#475569;margin-top:.3rem'>
                        Click "Run Chaos Monkey Suite" to test system resilience.
                    </div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("Chaos Monkey not available.")

    # ── Report viewer ───────────────────────────────────────────────────
    report_path = _BASE_DIR / "logs" / "chaos_monkey_report.txt"
    if report_path.exists():
        with st.expander("📝 View Full Chaos Monkey Report", expanded=False):
            st.code(report_path.read_text(encoding="utf-8")[:3000], language="text")

# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("""
<div style='text-align:center;padding:1.5rem 0 .5rem;
            font-size:.72rem;color:#334155;letter-spacing:.05em'>
    QAFFEINE Analytics · QAFFEINE Copilot v2.0 · Gemini 2.0 Flash ↩ OpenRouter/Llama-3.3-70B · ML Forecaster
</div>
""", unsafe_allow_html=True)
