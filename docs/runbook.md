# Runbook — DailyAssistant / QAFFEINE

## Roles

| Surface | Command | Notes |
| -------- | ------- | ----- |
| Streamlit dashboard | `streamlit run app/dashboard.py` | From repo root; requires `database/AI_DATABASE.DB` (or `APP_DB_PATH`). |
| HTTP API | `uvicorn src.api.main:app --reload --port 8000` | Health, Copilot JSON, KPI read, job stubs. |

## Feature flags (Mark II)

| Env | Default | Meaning |
| --- | ------- | ------- |
| `USE_GUARDED_SQL_PIPELINE` | `true` | Try **intent → template SQL** before the LLM planner for Copilot. |
| `USE_NEW_COPILOT_ENGINE` | `true` | Route Copilot through `src/agents/copilot_engine.py` (timeout wrapper + intent). |
| `COPILOT_TIMEOUT_SECONDS` | `120` | Wall-clock limit for the **legacy LLM** loop only. |
| `COPILOT_NUMERIC_VALIDATION` | `true` | Append a **footer** if the answer shows a chain total **larger** than the digested SQL table sum. |
| `COPILOT_STRICT_DEMO_MODE` | `false` | Shorter, sectioned answers for **client demos** (synthesis prompt add-on). |
| `COPILOT_TRACE_JSONL` | `false` | Append JSON lines to **`var/copilot_traces/copilot.jsonl`** for post-demo review. |
| `COPILOT_CAUSAL_POSTCHECK` | `true` | Append a disclaimer when prose uses causal phrasing for weather/holidays/news without clear tool support. |
| `COPILOT_PREMISE_RANK_WINDOW` | `all` | Rank window for `premise_check`: `all`, `month`, or `last90`. |

**Rollback (Copilot misbehaves after deploy):** set `USE_GUARDED_SQL_PIPELINE=false` and/or `USE_NEW_COPILOT_ENGINE=false`, restart Streamlit/API, re-run a smoke question from the Copilot tab.

**Smoke checks:** `GET /health` → `200`; Copilot tab: ask a known intent phrase (e.g. “total chain revenue”) and confirm **Intent SQL** badge; ask an open-ended question and confirm LLM path still runs (or times out with a clear message).

## Artifacts

- Prefer writing basket outputs to **`var/basket_results.json`** (directory is gitignored). The proactive brief still falls back to `database/basket_results.json` if the `var/` file is absent.

## API errors

- **`422`** on `/v1/kpi/revenue-total` when no `outlets` query param is sent.
- **`503`** when the SQLite file is missing, locked, or queries fail — check `APP_DB_PATH` and file permissions.

## Morning Brief

- Async **`POST /v1/jobs/morning-brief`** is a **stub** (returns `not_implemented`). Production briefs today run from the Streamlit **Notifications** tab or internal scripts.

## Lint (CI)

- **`ruff check src tests`** plus **`scripts/copilot_brain.py`**, **`scripts/universal_context.py`**, and **`scripts/anomaly_engine.py`** are enforced in GitHub Actions. `app/dashboard.py` remains excluded (see `pyproject.toml` `extend-exclude`).

## API safety (Copilot)

- **`POST /v1/copilot/query`** (and the Streamlit tab) have **no built-in authentication or rate limiting** in this repo. For production, place the API behind your gateway (API key, OAuth, or mutual TLS) and apply per-tenant rate limits at the edge.
