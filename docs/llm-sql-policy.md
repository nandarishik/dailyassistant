# LLM → SQL policy

## Goals

1. **Never** execute write DDL/DML from model text.
2. **Bound** read paths (row limits, progress handler on heavy tool queries).
3. Prefer **template SQL** for recurring intents instead of free-form generation.

## Enforcement layers

| Layer | Code | Behaviour |
| ----- | ---- | ----------- |
| Static guard | [`src/sql/sql_guard.py`](../src/sql/sql_guard.py) | Single `SELECT` only; block `PRAGMA`, `ATTACH`, `sqlite_master`, etc.; append `LIMIT` when missing. |
| Execution | [`src/sql/guarded_execute.py`](../src/sql/guarded_execute.py) | Validates then runs the query; returns markdown or an error string. |
| Intent pipeline | [`src/intent/pipeline.py`](../src/intent/pipeline.py) | Maps a small set of natural phrases to **fixed** `SELECT` templates over known tables. |
| LLM tools | [`scripts/copilot_brain.py`](../scripts/copilot_brain.py) `_tool_query_sales_db` | Delegates to `guarded_execute` for any model-proposed SQL. |

## Chain totals (Copilot synthesis)

- For **“total / chain / all outlets”** questions, the planner should prefer a **single-row** `SELECT ROUND(SUM(NETAMT),0) AS total_revenue …` (see planner examples in `scripts/copilot_brain.py`). Per-outlet `GROUP BY` tables are still valid for breakdowns.
- **`VERIFIED_NUMERIC_FACTS`:** after tools run, Python **parses markdown tables** from `query_sales_db` results and injects **column sums** into the synthesis prompt so the model must not mentally re-sum rows (see [COPILOT_NUMERIC_INTEGRITY_PLAN.md](COPILOT_NUMERIC_INTEGRITY_PLAN.md)).
- **Post-check:** if `COPILOT_NUMERIC_VALIDATION=true`, `numeric_postcheck` appends a footer when the answer cites a **larger** (`numeric_mismatch`) or **materially smaller** (`numeric_mismatch_low`) figure than the digested table sum (`src/copilot/numeric_postcheck.py`).

## Operational toggles

- Disable intent-first routing: `USE_GUARDED_SQL_PIPELINE=false` (see [runbook.md](runbook.md)).
- Copilot still cannot bypass `sql_guard` for `query_sales_db` tool calls.

## Future work

- Expand intent schema + golden suite as new question classes stabilize.
- **Robustness (numbers + demo narrative):** [COPILOT_NUMERIC_INTEGRITY_PLAN.md](COPILOT_NUMERIC_INTEGRITY_PLAN.md) — digests, verified prompt block, validator, multi-tool grounding, baselines, date resolution, strict demo mode, telemetry.

## Trust stack (2026 rollout)

- **Intent SQL** uses bound parameters via `fetch_select_as_markdown_params` (`src/sql/guarded_execute.py`).
- **LLM SQL guard** can optionally block `UNION` and enforce a table allowlist (`sql_guard_block_union`, `sql_guard_table_allowlist` in settings).
- **Premise / scope:** `premise_check` and `data_scope` are merged into Copilot `evidence` and synthesis blocks; see `src/copilot/premise_check.py`, `src/copilot/data_scope.py`.
