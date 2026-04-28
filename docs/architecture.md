# Architecture (Streamlit → services → agents)

Mid-migration map: KPI reads are fully in **`src/services/kpi_service.py`**. Copilot goes through **`src/services/query_service.py`** → **`src/agents/copilot_engine.py`** (intent layer + legacy **`scripts/copilot_brain.py`** agent).

## Tabs → primary code path

| UI tab | Modules | API / service boundary |
| ------ | ------- | ---------------------- |
| KPI Dashboard | `app/dashboard.py` → `kpi_service` | `GET /v1/kpi/revenue-total` |
| AI Copilot | `app/dashboard.py` → `query_service.investigate_copilot_for_ui` | `POST /v1/copilot/query` |
| Notifications | `app/dashboard.py` → anomaly/mailer/copilot tools | `POST /v1/jobs/morning-brief` (stub) |
| Simulator | `app/dashboard.py` → `forecaster` | _(not exposed on API yet)_ |

## Shared infrastructure

| Concern | Location |
| ------- | -------- |
| Env load order | [`src/config/env.py`](../src/config/env.py) `load_app_dotenv` |
| DB path + flags | [`src/config/settings.py`](../src/config/settings.py) |
| Startup DB check (Streamlit) | [`src/config/runtime_check.py`](../src/config/runtime_check.py) |
| SQLite context manager | [`src/data/access/db.py`](../src/data/access/db.py) |
| Sidebar bounds (no pandas) | [`src/data/sidebar_bounds.py`](../src/data/sidebar_bounds.py) |
| Copilot DTO | [`src/contracts/copilot.py`](../src/contracts/copilot.py) |
| KPI tab validation | [`src/contracts/kpi_tab.py`](../src/contracts/kpi_tab.py) |
| SQL guard + execute | [`src/sql/sql_guard.py`](../src/sql/sql_guard.py), [`src/sql/guarded_execute.py`](../src/sql/guarded_execute.py) |
| Intent templates | [`src/intent/pipeline.py`](../src/intent/pipeline.py) |
| Copilot façade | [`src/agents/copilot_engine.py`](../src/agents/copilot_engine.py) |
| Legacy agent singleton | [`src/agents/legacy_adapter.py`](../src/agents/legacy_adapter.py) |
| HTTP app | [`src/api/main.py`](../src/api/main.py) |

## HTTP routes (v0.2)

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET` | `/health` | Liveness. |
| `POST` | `/v1/copilot/query` | JSON body `{ "question": "..." }` → `CopilotResponse` dict. |
| `GET` | `/v1/kpi/revenue-total` | Query params `date_start`, `date_end`, repeat `outlets`. |
| `POST` | `/v1/jobs/morning-brief` | Stub — see [runbook.md](runbook.md). |

## Single Copilot entry

- **UI:** `investigate_copilot_for_ui()` in [`src/services/query_service.py`](../src/services/query_service.py).
- **Engine:** [`src/agents/copilot_engine.py`](../src/agents/copilot_engine.py) — intent match first (when enabled), then LLM agent with timeout.
- **Jarvis:** [`scripts/jarvis_brain.py`](../scripts/jarvis_brain.py) remains a shim to the same stack.
