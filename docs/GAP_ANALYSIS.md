# Gap analysis (Mark II snapshot)

## Closed in this iteration

- Central **Copilot engine** with `query_id`, optional **evidence** payload, and LLM **timeout**.
- **Intent → SQL** path on by default for a small phrase set (`total_revenue`, `revenue_by_outlet`, `top_items`).
- **KPI input validation** via `KpiTabQuery` (`src/contracts/kpi_tab.py`).
- **Shared guarded execution** for tool SQL + intents.
- **API** stubs: `GET /v1/kpi/revenue-total`, `POST /v1/jobs/morning-brief`.
- **Docs:** runbook, data dictionary, LLM SQL policy, this file.
- **Streamlit:** Copilot suggestion **buttons**, **IntentSQL** badge, truncated tool `st.code` blocks.
- **Basket file** prefers `var/basket_results.json` with legacy fallback.

## Still open (next iterations)

- Full **intent JSON schema** + compiler beyond the three templates; feature-rich **policy engine**.
- **CopilotResponse** `evidence` populated for LLM path (today strongest on intent path).
- Move **orchestration** out of `scripts/copilot_brain.py` into `src/agents/` beyond the façade (`copilot_engine` still uses legacy agent for LLM).
- **Lockfile** (`uv` / `pip-tools`) committed + CI reproducibility.
- **`_one_off/`** shrink: move keepers to `fixtures/` or delete stale outputs.
- **Track U** remainder: `use_container_width` → `width` where Streamlit version allows; optional `st.fragment`; tab file split.
- **Load / SLO** baseline job (deferred in plan).
