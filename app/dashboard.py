"""
QAFFEINE Sales Dashboard — v2 with Gemini AI Assistant
=======================================================
Tabbed Streamlit app: Tab 1 = KPI Dashboard, Tab 2 = AI Assistant
Run: streamlit run app/dashboard.py
"""

import sys, os, pathlib, html
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ─── Path setup (must run before any src.* imports) ──────────────────────────
_BASE_DIR  = pathlib.Path(__file__).parent.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))
if str(_BASE_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(_BASE_DIR / "scripts"))

from src.app.styles import DASHBOARD_CSS
from src.config.env import load_app_dotenv
from src.config.runtime_check import DatabaseConfigError, validate_database_path
from src.config.settings import resolve_db_path
from src.services.kpi_service import load_kpi_tab_data, load_sidebar_filter_options
from src.services.query_service import investigate_copilot_for_ui

# ─── Load .env and import LLMManager from context engine ─────────────────────
load_app_dotenv(_BASE_DIR)

from universal_context import LLMManager
from copilot_brain import generate_proactive_brief, generate_anomaly_diagnosis
from anomaly_engine import detect_anomalies_all_outlets, get_anomaly_summary_table
from mailer import send_morning_brief, load_notification_history, build_email_html, log_notification
from copilot_brain import _tool_analyze_product_mix

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

# ─── Copilot Intelligence Brief (cached 10 min) ──────────────────────────────
@st.cache_data(ttl=600)
def get_intelligence_brief() -> dict:
    """Auto-computes anomaly + combo + market risk — no user prompt needed."""
    return generate_proactive_brief()

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Bajaj DMS Analytics",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE    = _BASE_DIR
DB_PATH = resolve_db_path(BASE)
try:
    validate_database_path(BASE, require_exists=True)
except DatabaseConfigError as exc:
    st.error(str(exc))
    st.stop()

# ─── LLM Dual-Engine (Gemini primary → OpenRouter backup) ────────────────────
# Instantiated once at startup; shared across all Streamlit reruns via cache.
@st.cache_resource
def get_llm() -> LLMManager:
    return LLMManager()

# ─── CSS (design tokens + layout — see src/app/styles.py) ───────────────────
st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)

# ─── Load sidebar filter data ─────────────────────────────────────────────────
_filter_opts = load_sidebar_filter_options(BASE)
all_outlets = _filter_opts.outlets
min_date = _filter_opts.min_date
max_date = _filter_opts.max_date

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='text-align:center;padding:.8rem 0 1rem'>
        <div style='font-size:2.6rem'>🏢</div>
        <div style='font-size:1.1rem;font-weight:800;color:#f1f5f9'>BAJAJ DMS</div>
        <div style='font-size:.7rem;color:#64748b;letter-spacing:.15em'>ANALYTICS · BAJAJ COPILOT</div>
    </div>
    """, unsafe_allow_html=True)

    # (Intelligence Brief removed for clean UI)


    # ── Filters ───────────────────────────────────────────────────────────
    outlet_choice = st.multiselect("Select Zone", options=all_outlets,
                                   default=all_outlets)
    date_range = st.date_input("Date Range", value=(min_date, max_date),
                               min_value=min_date, max_value=max_date)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    st.markdown("""
    <div style='font-size:.7rem;color:#475569;padding-top:.5rem;
                border-top:1px solid rgba(255,255,255,.06)'>
        Data: 2026 · Bajaj Copilot v2.0
    </div>
    """, unsafe_allow_html=True)

if len(outlet_choice) == 0 or not isinstance(date_range, (tuple, list)) or len(date_range) < 2:
    st.warning("Please select at least one outlet and a valid date range.")
    st.stop()

date_start   = str(date_range[0])
date_end     = str(date_range[1])

# ─── Page header ──────────────────────────────────────────────────────────────
st.markdown(f"""
<div class='page-title'>🏢 Bajaj DMS Analytics</div>
<div class='page-sub'>Multi-Zone Dashboard · {date_start} → {date_end} · {len(outlet_choice)} zone(s)</div>
""", unsafe_allow_html=True)
st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

# ─── TABS ───────────────────────────────────────────────────────────────────
tab_dash, tab_ai, tab_sim = st.tabs(
    [
        "📊  KPI Dashboard",
        "🤖  AI Copilot",
        "🔮  Simulator",
    ]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — KPI DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    # ── KPI data via service (no raw SQL in the tab) ───────────────────────────
    _kpi_data = load_kpi_tab_data(BASE, outlet_choice, date_start, date_end)
    kpi = _kpi_data.kpi
    top5 = _kpi_data.top5
    by_outlet = _kpi_data.by_outlet
    daily = _kpi_data.daily
    raw_df = _kpi_data.raw_df

    total_revenue = float(kpi["total_revenue"].iloc[0]) if not kpi["total_revenue"].isna().all() else 0.0
    total_orders  = int(kpi["total_orders"].iloc[0])    if not kpi["total_orders"].isna().all() else 0
    aov           = float(kpi["aov"].iloc[0])           if not kpi["aov"].isna().all() else 0.0
    total_packs   = int(kpi["total_packs"].iloc[0])     if not kpi["total_packs"].isna().all() else 0
    total_vol     = float(kpi["total_volume_ltr"].iloc[0]) if not kpi["total_volume_ltr"].isna().all() else 0.0

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

    kpi_card(c1,"💰","Revenue", f"₹{total_revenue:,.0f}", f"{len(outlet_choice)} zone(s)")
    kpi_card(c2,"🧾","Orders", f"{total_orders:,}", "Unique bills")
    kpi_card(c3,"📈","AOV", f"₹{aov:,.0f}", "Revenue/bill")
    kpi_card(c4,"📦","Packs", f"{total_packs:,}", "Total packs sold")
    kpi_card(c5,"🛢️","Volume", f"{total_vol:,.0f} L", "Total liters billed")

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
            st.plotly_chart(fig, width="stretch")

    with cr:
        st.markdown("<div class='section-header'>🏪 Revenue by Zone</div>", unsafe_allow_html=True)
        if not by_outlet.empty:
            COLORS = ["#f59e0b","#10b981","#3b82f6","#8b5cf6","#ef4444","#06b6d4"]
            shorts = by_outlet["outlet_name"]
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
            st.plotly_chart(fig2, width="stretch")

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
        st.markdown("<div class='section-header'>📋 Zone Performance Summary</div>", unsafe_allow_html=True)
        disp = by_outlet.copy()
        disp.columns = ["Zone","Revenue (₹)","Orders"]
        disp["Revenue (₹)"] = disp["Revenue (₹)"].apply(lambda x: f"₹{x:,.2f}")
        st.dataframe(disp, width="stretch", hide_index=True, height=280)

    st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

    with st.expander("🗃️  View Raw Fact Sales Data", expanded=False):
        st.markdown(f"<div style='font-size:.8rem;color:#64748b;margin-bottom:.5rem'>"
                    f"<b style='color:#f1f5f9'>{len(raw_df):,}</b> rows</div>",
                    unsafe_allow_html=True)
        st.dataframe(raw_df, width="stretch", height=360)
        st.download_button("⬇️ Download CSV",
                           data=raw_df.to_csv(index=False).encode(),
                           file_name=f"qaffeine_{date_start}_{date_end}.csv",
                           mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Bajaj Copilot  (Agentic Multi-Tool)
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.markdown("""
    <div style='padding:.6rem 0 .4rem'>
        <div style='font-size:1.5rem;font-weight:800;color:#f1f5f9'>🤖 Bajaj Copilot — AI Business Partner</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Chat state ───────────────────────────────────────────────────────────
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    pending_q = st.session_state.pop("copilot_question_pending", None)
    if pending_q:
        try:
            with st.status("🤖 Bajaj Copilot is investigating…", expanded=True) as _pending_status:
                st.write(f'🔍 Received: "{pending_q[:80]}"')
                _entry = investigate_copilot_for_ui(pending_q)
                for _step in _entry.get("monologue", []):
                    if _step.strip():
                        st.write(_step)
                _pending_status.update(label="✅ Done", state="complete", expanded=False)
            _entry["question"] = pending_q
            st.session_state.chat_history.append(_entry)
            st.rerun()
        except Exception as exc:
            st.error(f"Copilot investigation failed: {exc}")

    # ── Suggested questions (pill buttons — Mark II Track U) ─────────────────
    st.markdown(
        "<div style='font-size:.75rem;color:#64748b;font-weight:600;"
        "letter-spacing:.08em;text-transform:uppercase;margin-bottom:.5rem'>"
        "Try asking the Copilot:</div>",
        unsafe_allow_html=True,
    )
    suggestions = [
        "Which day of the week has our highest average sales?",
        "Why was revenue so high on Jan 31st?",
        "Rank our top 5 zones by total revenue this year.",
        "What are our top 3 selling items across the entire company?",
        "How is the East Zone performing this month?",
        "Compare our total revenue between February and March.",
    ]
    sg1, sg2, sg3 = st.columns(3)
    for i, col in enumerate([sg1, sg2, sg3, sg1, sg2, sg3]):
        if i < len(suggestions):
            short = suggestions[i] if len(suggestions[i]) <= 52 else suggestions[i][:49] + "…"
            if col.button(short, key=f"copilot_sug_{i}", help=suggestions[i]):
                st.session_state.copilot_question_pending = suggestions[i]
                st.rerun()

    st.markdown("<div class='custom-divider'></div>", unsafe_allow_html=True)

    # ── Render chat history (st.chat_message — plan secondary Copilot UX) ────
    for entry in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(entry.get("question", ""))
        with st.chat_message("assistant"):
            try:
                if entry.get("error"):
                    st.error(f"Copilot error: {entry['error']}")
                else:
                    eng = entry.get("engine", "")
                    model = str(entry.get("model", "")).replace("models/", "")
                    if eng == "Gemini":
                        badge_color, badge_icon = "#86efac", "✅"
                        engine_label = f"Gemini / {model}"
                    elif eng == "OpenRouter":
                        badge_color, badge_icon = "#fbbf24", "⚠️"
                        engine_label = f"OpenRouter ↩ {model}"
                    elif eng == "IntentSQL":
                        badge_color, badge_icon = "#34d399", "🛡️"
                        engine_label = "Intent SQL (guarded template)"
                    else:
                        badge_color, badge_icon = "#94a3b8", "⚡"
                        engine_label = model or "Bajaj Copilot"

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
                                    _res = tc.get("result", "") or ""
                                    if len(_res) > 12000:
                                        _res = (
                                            _res[:12000]
                                            + "\n\n… (truncated for UI; full text in export later)"
                                        )
                                    st.code(_res, language="markdown")
                    elif engine_label.strip():
                        safe_engine_label = html.escape(engine_label)
                        st.markdown(
                            f"<div style='font-size:.68rem;color:#64748b;margin:.2rem 0 .3rem'>"
                            f"{badge_icon} <b style='color:{badge_color}'>{safe_engine_label}</b></div>",
                            unsafe_allow_html=True,
                        )

                    if entry.get("response"):
                        st.markdown("**Bajaj Copilot**")
                        st.markdown(str(entry["response"]))

                    _evc = entry.get("evidence") or {}
                    _pc = _evc.get("premise_check") or {}
                    if _pc.get("premise_conflict"):
                        st.warning(
                            "Trust signal: the warehouse ranks this day among the **best** in the "
                            "comparison window — the question assumed a decline."
                        )
                    _nf = _evc.get("numeric_facts") or []
                    _trust = (
                        _nf
                        or _evc.get("resolved_query_context")
                        or _evc.get("guardrail_flags")
                        or _evc.get("premise_check")
                        or _evc.get("data_scope")
                    )
                    if _trust:
                        with st.expander("Verified numbers & trust signals", expanded=False):
                            st.json(
                                {
                                    "numeric_facts": _nf,
                                    "resolved_query_context": _evc.get("resolved_query_context"),
                                    "guardrail_flags": _evc.get("guardrail_flags"),
                                    "premise_check": _evc.get("premise_check"),
                                    "data_scope": _evc.get("data_scope"),
                                }
                            )
            except Exception as exc:
                st.error(f"Could not render this Copilot reply: {exc}")

    # ── Chat input ───────────────────────────────────────────────────────────
    user_q = st.chat_input("Ask the Copilot anything about your business…")

    if user_q:
        try:
            with st.status("🤖 Bajaj Copilot is investigating…", expanded=True) as status:
                st.write(f'🔍 Received: "{user_q[:80]}"')
                entry = investigate_copilot_for_ui(user_q)
                for step in entry.get("monologue", []):
                    if step.strip():
                        st.write(step)
                n_tools = len(entry.get("tool_calls", []))
                model_tail = str(entry.get("model", "")).split("/")[-1] or "model"
                label = (
                    f"✅ Done — {n_tools} tool{'s' if n_tools != 1 else ''} called "
                    f"via {entry.get('engine')}/{model_tail}"
                )
                if entry.get("error"):
                    label = f"⚠️ Partial — {str(entry['error'])[:60]}"
                status.update(label=label, state="complete", expanded=False)

            st.session_state.chat_history.append(entry)
            st.rerun()
        except Exception as exc:
            st.error(f"Copilot investigation failed: {exc}")

    # ── Clear button ─────────────────────────────────────────────────────────
    if st.session_state.chat_history:
        if st.button("🗑️  Clear chat", type="secondary"):
            st.session_state.chat_history = []
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — NOTIFICATION CENTER (Commented out)
# ══════════════════════════════════════════════════════════════════════════════
if False: # with tab_notify:
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
            with st.status("🤖 Bajaj Copilot — Morning Brief Pipeline", expanded=True) as brief_status:
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
                    recommendations = _tool_analyze_product_mix(
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

    try:
        history = load_notification_history(last_n=5)
    except Exception as exc:
        st.error(f"Could not load alert history: {exc}")
        history = []

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
        st.dataframe(disp, width="stretch", hide_index=True, height=240)
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
# TAB 4 — SIMULATOR (What-If Situation Room)
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
        st.code("python scripts/forecaster.py", language="bash")
        if st.button("🚀 Train Model Now", type="primary", key="train_model_btn"):
            import subprocess as _sp_sim
            with st.status("🧠 Training revenue forecaster...", expanded=True) as ts:
                script = str(_BASE_DIR / "scripts" / "forecaster.py")
                try:
                    r = _sp_sim.run(
                        [sys.executable, script],
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                except _sp_sim.TimeoutExpired:
                    st.error("Training timed out after 10 minutes. Try running `python scripts/forecaster.py` in a terminal.")
                    ts.update(label="❌ Training timed out", state="error")
                else:
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
            placeholder="e.g. 'Heavy rain on a Friday in East Zone' or 'Thunderstorm in West Zone this Saturday'",
            key="scenario_chat_input",
            label_visibility="collapsed",
        )

        # Process natural language scenario
        if scenario_text and scenario_text.strip():
            if scenario_text != st.session_state.get("last_scenario_text", ""):
                try:
                    with st.status(
                        "🧠 Bajaj Copilot is interpreting your scenario...", expanded=True
                    ) as parse_status:
                        parsed = interpret_scenario_prompt(scenario_text)
                        st.write(f"🏪 **Outlet:** {parsed['outlet']}")
                        st.write(
                            f"🌧️ **Rain:** {parsed['rain_mm']}mm  |  🌡️ **Temp:** {parsed['temp_c']}°C"
                        )
                        st.write(
                            f"📅 **Date:** {parsed['date']}  |  🧠 **Parsed via:** "
                            f"{parsed.get('parse_method', 'N/A')}"
                        )
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
                except Exception as exc:
                    st.error(f"Scenario interpretation failed: {exc}")

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
        try:
            date_str = str(sim_date)
            result = predict_revenue(
                sim_outlet,
                date_str,
                rain_mm=float(sim_rain),
                temp_c=float(sim_temp),
            )
        except Exception as exc:
            st.error(f"Simulator prediction failed: {exc}")
            result = {"error": str(exc)}

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
                width="stretch",
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
            st.markdown("<div class='section-header'>🧠 Bajaj Copilot Narrative Analysis</div>",
                        unsafe_allow_html=True)

            # Build narrative context
            scenario_desc = scenario_text if scenario_text else f"{sim_rain}mm rain, {sim_temp}°C"
            narrative_prompt = f"""You are Bajaj Copilot, an elite coffee-chain business strategist.

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
                safe_body = html.escape(str(narrative_text)).replace("\n", "<br/>")
                safe_eng = html.escape(str(narrative_engine))
                st.markdown(f"""
                <div style='background:rgba(139,92,246,.06);border:1px solid rgba(139,92,246,.2);
                            border-radius:14px;padding:1.2rem 1.5rem;margin-bottom:1rem'>
                    <div style='font-size:.7rem;color:#a78bfa;font-weight:700;
                                letter-spacing:.06em;text-transform:uppercase;
                                margin-bottom:.5rem'>
                        🧠 Copilot Analysis · via {safe_eng}
                    </div>
                    <div style='font-size:.85rem;color:#e2e8f0;line-height:1.65'>
                        {safe_body}
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


# ─── Footer ───────────────────────────────────────────────────────────────────
st.markdown("""
<div style='text-align:center;padding:1.5rem 0 .5rem;
            font-size:.72rem;color:#334155;letter-spacing:.05em'>
    QAFFEINE Analytics · Bajaj Copilot v2.0 · Gemini 2.0 Flash ↩ OpenRouter/Llama-3.3-70B · ML Forecaster
</div>
""", unsafe_allow_html=True)
