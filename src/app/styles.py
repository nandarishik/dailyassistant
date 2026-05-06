"""Central dashboard CSS (plan Part 14 — React-portable token names in :root)."""

from __future__ import annotations

# Tokens mirror future CSS variables for a React shell.
DASHBOARD_CSS = """
<style>
:root {
  --color-bg: #0f0c29;
  --color-surface: rgba(255,255,255,0.05);
  --color-border: rgba(255,255,255,0.1);
  --color-text-primary: #ffffff;
  --color-text-muted: #cbd5e1;
  --color-accent: #f59e0b;
  --color-danger: #ef4444;
  --color-success: #10b981;
}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
html, body, .main, .stMarkdown, p, .kpi-value, .chat-ai, .chat-user { 
    font-family: 'Inter', sans-serif; 
    color: #ffffff !important; 
}
.stApp {
    background: linear-gradient(135deg, var(--color-bg) 0%, #302b63 50%, #24243e 100%);
    min-height: 100vh;
}
.main .block-container { padding: 1.5rem 2.5rem 2rem; max-width: 1400px; }

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    border-right: 1px solid rgba(255,255,255,0.12);
}
[data-testid="stSidebar"] * { color: #ffffff !important; }
[data-testid="stSidebar"] label {
    color: #94a3b8 !important; font-size: 0.78rem;
    font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
}

.stTabs [data-baseweb="tab-list"]  {
    background: rgba(255,255,255,0.06);
    border-radius: 12px; padding: 4px; gap: 4px;
    border: 1px solid rgba(255,255,255,0.12);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px; padding: 0.45rem 1.4rem;
    font-weight: 600; font-size: 0.85rem; color: #94a3b8 !important;
    background: transparent; border: none;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg,#f59e0b,#f97316) !important;
    color: #ffffff !important;
}

.kpi-card {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 16px; padding: 1.4rem 1.6rem 1.2rem;
    backdrop-filter: blur(12px);
    transition: transform .2s, box-shadow .2s;
}
.kpi-card:hover { transform: translateY(-3px); box-shadow: 0 12px 32px rgba(0,0,0,.4); }
.kpi-icon  { font-size: 1.8rem; margin-bottom: .4rem; }
.kpi-label { font-size: .72rem; font-weight: 700; letter-spacing: .1em;
             text-transform: uppercase; color: #94a3b8 !important; margin-bottom: .3rem; }
.kpi-value { font-size: 1.6rem; font-weight: 800; color: #ffffff !important; line-height: 1.1; }
.kpi-sub   { font-size: .75rem; color: #94a3b8 !important; margin-top: .25rem; }

.section-header {
    font-size: 1rem; font-weight: 700; color: #ffffff !important;
    letter-spacing: .06em; text-transform: uppercase;
    padding: .6rem 0 .4rem;
    border-bottom: 1px solid rgba(255,255,255,.12); margin-bottom: .8rem;
}
.custom-divider {
    height: 1px;
    background: linear-gradient(90deg,transparent,rgba(255,255,255,.2),transparent);
    margin: 1.5rem 0;
}
.page-title { font-size: 2.2rem; font-weight: 800; color: #ffffff !important; line-height: 1.1; }
.page-sub   { font-size: .9rem; color: #cbd5e1 !important; margin-top: .2rem; }

.chat-user {
    background: linear-gradient(135deg,#3b82f6,#6366f1);
    border-radius: 16px 16px 4px 16px;
    padding: .8rem 1.1rem; margin: .5rem 0; color: #ffffff !important;
    font-size:.9rem; max-width:80%; margin-left:auto; text-align:right;
    border: 1px solid rgba(255,255,255,0.2);
}
.chat-ai {
    background: rgba(255,255,255,.12);
    border: 1px solid rgba(255,255,255,.2);
    border-radius: 4px 16px 16px 16px;
    padding: .8rem 1.1rem; margin: .5rem 0; color: #ffffff !important;
    font-size:.9rem; max-width:85%;
}
.sql-block {
    background: #000000; border: 1px solid rgba(99,102,241,.6);
    border-radius: 10px; padding: .8rem 1rem;
    font-family: 'Courier New', monospace; font-size: .8rem;
    color: #a5b4fc !important; margin: .5rem 0;
}
.insight-block {
    background: linear-gradient(135deg,rgba(16,185,129,.2),rgba(6,182,212,.2));
    border: 1px solid rgba(16,185,129,.4);
    border-radius: 10px; padding: .8rem 1rem;
    font-size: .88rem; color: #ffffff !important; margin: .5rem 0;
}
.ai-thinking {
    color: #94a3b8 !important; font-size: .78rem;
    font-style: italic; padding: .3rem 0;
}

[data-testid="stExpander"] {
    background: rgba(255,255,255,.06) !important;
    border: 1px solid rgba(255,255,255,.12) !important;
    border-radius: 12px !important;
}
</style>
"""
