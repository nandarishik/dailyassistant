# 📖 The QAFFEINE Project Bible: Bajaj DMS Intelligence Platform

This document serves as the absolute technical reference for the **Bajaj DMS Analytics & AI Copilot** (QAFFEINE). It details the database architecture, agentic reasoning loops, tool integration, and the end-to-end flow of data from raw sales records to AI-driven business insights.

---

## 1. Core Architecture Overview
QAFFEINE is built on a **"Plan → Execute → Synthesise"** agentic pattern. It is designed to act as a Senior Business Analyst that bridges the gap between raw SQL data and strategic context (weather, news, holidays).

### High-Level Component Stack:
*   **UI Layer:** Streamlit (`app/dashboard.py`)
*   **Intelligence Layer:** Copilot Agent (`scripts/copilot_brain.py`)
*   **Context Layer:** Universal Context Engine (`scripts/universal_context.py`)
*   **Data Layer:** SQLite (`AI_DMS_database.db`)
*   **Logic Layer:** Python Services (`src/services/`, `src/data/`)

---

## 2. The Database Schema
The system relies on two primary tables in `AI_DMS_database.db`.

### A. `VIEW_AI_SALES` (The Secondary Sales Engine)
This is a flattened view of all secondary sales transactions for January 2026.
*   **Revenue:** `NET_AMT` (Always use `SUM(NET_AMT)`).
*   **Hierarchy:** `ZONE`, `STATE`, `TOWN`, `SALES_MANAGER`, `ISR`.
*   **Distribution:** `STOCKIEST` (Distributor), `BEAT` (Route), `CUSTOMER` (Retailer).
*   **Product:** `PRODUCT_CLASS` (Category), `CODE` (Brand), `PRODUCT` (SKU).
*   **Discounts:** `SCHEME_AMT` (SKU Level), `GRP_SCHEME_AMT` (Group/Basket Level).

### B. `context_intelligence` (The External Signal Table)
Stores pre-fetched and analysed context for specific dates to avoid repeated API calls.
*   `date`: YYYY-MM-DD
*   `is_holiday`: Boolean flag for Indian regional/national holidays.
*   `weather_condition`: Max Temp / Precipitation.
*   `news_headlines`: Curated business/macro news for that date.

---

## 3. The Copilot Agent (The "Brain")
The logic resides in `scripts/copilot_brain.py` under the `CopilotAgent` class.

### Phase 1: Planning (`_plan`)
The LLM receives the user's query and the `DB_SCHEMA_BRIEF`. It outputs a JSON array of tool calls.
*   **Expert Rules:** If the user asks for "today," the planner anchors the date to **2026-01-31**.
*   **Synonym Logic:** It maps "ECO" to `COUNT(DISTINCT CUSTOMER)` and "DB" to the `STOCKIEST` column.

### Phase 2: Execution (`_execute`)
The system runs the planned tools locally.
*   **`query_sales_db(sql)`**: Executes the SQL and returns a formatted Markdown table.
*   **`get_holiday_status(date)`**: Checks if the date was a holiday (disruption factor).
*   **`get_news_context(date)`**: Fetches headlines to find macro causes for sales trends.
*   **`analyze_product_mix(zone/date)`**: Performs a "What Sells Together" basket analysis.

### Phase 3: Synthesis (`_synthesise`)
The LLM receives the raw tool results + the original query. It uses the **Senior Analyst Voice** to weave a narrative.
*   **Math Guardrail:** It is strictly forbidden from "guessing" totals. It must use the `SUM()` provided by the SQL tool.
*   **Crore Rule:** All figures are converted to "Cr" using a `10,000,000` divisor.

---

## 4. End-to-End Dry Run: "Why did sales drop in East Zone on Jan 15th?"

1.  **UI Entry:** User types the question into the AI Assistant tab.
2.  **Service Call:** `dashboard.py` calls `investigate_copilot_for_ui()`.
3.  **The Plan:** The Planner decides it needs:
    *   `query_sales_db`: Total revenue for East Zone on Jan 15th.
    *   `query_sales_db`: Revenue for East Zone on the 5 days prior (benchmark).
    *   `get_holiday_status`: Check if Jan 15th was a festival (e.g., Makar Sankranti).
    *   `get_news_context`: Check for transport strikes or regional events.
4.  **The Execution:**
    *   SQL reveals a 40% drop vs. the 5-day average.
    *   Holiday tool confirms **Makar Sankranti** in Bihar/West Bengal (East Zone).
    *   News tool identifies regional weather alerts.
5.  **The Synthesis:** The AI generates a response:
    > "East Zone saw a 40% revenue dip on Jan 15th (₹22L vs ₹38L avg). This correlates directly with the Makar Sankranti festival which halted primary distribution, compounded by heavy rain alerts reported in the regional news."

---

## 5. Directory & File Map

| Path | Purpose |
| :--- | :--- |
| `app/dashboard.py` | Main entry point. Handles Tab 1 (KPIs) and Tab 2 (Chat). |
| `scripts/copilot_brain.py` | The core Agentic loop (Plan/Execute/Synthesise). |
| `scripts/universal_context.py` | Fetches News, Weather, and Holidays. Handles LLM Failover. |
| `src/services/query_service.py` | The bridge between the UI and the AI Agent. |
| `src/app/styles.py` | Forces the Dark/Premium theme and UI consistency. |
| `src/data/access/db.py` | Safe SQLite connection management. |
| `scripts/anomaly_engine.py` | Statistical Z-Score detection for revenue drops. |

---

## 6. Key Configuration (Environment)
The system uses `.env` and `st.secrets` to manage:
*   `OPENROUTER_API_KEY`: Primary engine (Llama-3/Claude).
*   `GOOGLE_API_KEY`: Fallback engine (Gemini 1.5 Pro).
*   `NEWS_API_KEY`: For real-time market signals.
*   `WEATHER_API_KEY`: For correlation analysis.

---

## 7. Developer Guardrails
*   **Numeric Truth:** Every number in the chat must be traced back to an SQL result.
*   **No Placeholders:** Never use "Dummy Data" in responses. If data is missing, the AI must state it.
*   **Security:** SQL queries are "Select-Only" and never allow `DROP` or `UPDATE` commands.

---
**Document Status:** Current (Verified May 2026)  
**Maintainer:** QAFFEINE Engineering Team
