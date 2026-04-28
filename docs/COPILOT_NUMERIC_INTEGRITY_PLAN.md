# Copilot robustness plan (numeric integrity + demo-ready responses)

This document is the **single execution plan** for making Copilot answers **trustworthy enough for a client demo**: correct figures, honest limits, and no “confident wrong” narratives. **Part A** is numeric / SQL grounding; **Part B** is everything else that still produces bad or useless answers even when SQL is fine.

---

## Problem statement

The LLM **synthesis** step (`CopilotAgent._synthesise` in `scripts/copilot_brain.py`) receives **markdown tables** from `query_sales_db` and produces prose. Models **mis-sum**, **invent totals**, or **mix numbers across tools** despite instructions like *“Use ONLY numbers… Do NOT invent”* (see `SYNTHESIS_PROMPT_TMPL`). **Markdown is not a structured contract**; the model treats it as narrative.

**Observed failure:** Per-outlet revenue table (29 rows) sums to **₹3,653,162**; the model stated **₹5,318,119** — wrong chain total, invalidating the whole “drop vs average” story.

**Root cause (technical):** No **machine-checked** aggregate is bound to the final answer; the LLM is the last authority on arithmetic.

**Demo risk (product):** Wrong numbers are the worst failure mode, but **useless** answers (vague bullets, over-long prose, invented causality, wrong year, silent truncation) also erode trust during a live demo.

---

## Success criteria (definition of done)

### A — Numbers & SQL

1. **Any stated chain / category total** that maps to a `query_sales_db` markdown table is either:
   - **Equal** to a **server-computed** sum/hash for that table, or  
   - **Absent** from the answer and replaced by the verified figure in a **fixed UI block** (see Phase 4).
2. **API contract** (`CopilotResponse.evidence`) includes **`numeric_facts`** (or equivalent) for UI and downstream clients: verified totals, row counts, SQL fingerprints, mismatch flags.
3. **Regression tests:** golden fixtures where table → sum is known; tests fail if synthesis path drops verified totals (or if post-validator flags drift).
4. **Planner bias:** For “total revenue / chain / all outlets / sum” questions, the **planner** prefers SQL that returns **`SUM(...)` in one row** (or `WITH` + rollup), not only `GROUP BY outlet` unless the user explicitly wants a breakdown.

### B — Demo & narrative quality

5. **Comparisons (“drop”, “vs average”, “underperforming”)** only appear if **tool output** contains both sides of the comparison (or digest extracts two labeled scalars). Otherwise the assistant **states the gap** (“I don’t have a verified baseline in the tool results”) — no invented weekly average.
6. **Multi-tool answers** clearly **attribute** claims (“from sales SQL” vs “from weather API”) and do not **blend unrelated numbers** across tools into one sentence without explicit linkage.
7. **Resolved context** (date range, year, outlet scope) appears in **`evidence`** so the UI and reviewer can see what the assistant actually queried (mitigates “Feb 14 which year?”).
8. **Truncation / limits** are explicit: if `LIMIT` or row cap cuts the result, the user sees a **standard footer** in tool text and synthesis must mention incompleteness where relevant.
9. **Degraded mode:** If LLM or external APIs are missing / failing, the UI shows a **clear banner** and answers are **shorter and abstaining** where data is missing — not confident filler.
10. **Optional “strict demo mode”** (flag): caps length, forces a **Facts → Interpretation (caveated) → Next steps** structure, and turns on validator footers (Phase 4) always.

---

## Architecture: where truth lives

| Layer | Responsibility |
| ----- | ---------------- |
| **SQLite** | Source of truth for raw rows. |
| **`query_sales_db` / `guarded_execute`** | Returns markdown today; **extend** to also return **structured sidecar** (see Phase 1). |
| **`numeric_digest` (new, `src/`)** | Parse tool output **or** consume structured result; compute sums, row counts, column stats; **never** trust LLM for these. |
| **Synthesis prompt** | Receives **`=== VERIFIED_NUMERIC_FACTS ===`** JSON block **appended by Python**; model forbidden to contradict it. |
| **Optional validator** | Compare LLM prose numbers to digest; **flag** or **strip** unsupported totals (policy choice). |
| **Streamlit / API** | Show **Verified figures** expander from `evidence`, not only markdown prose. |

---

## Phase 1 — Structured facts from `query_sales_db` (foundation)

**Goal:** Stop treating the markdown table as the only machine-readable output.

**Options (pick one primary; the other can follow):**

- **1A (recommended):** After `fetch_select_as_markdown`, run the **same query** (or a companion query) via a small internal path that returns **`list[dict]`** + **column types** (pandas `read_sql` or `sqlite3` row factory), capped at row limit. Attach digest: `{ "tool": "query_sales_db", "sql_hash": "...", "rows": N, "columns": [...], "numeric_column_sums": { "revenue": 3653162.0 } }`.  
  - *Note:* Running SELECT twice is acceptable for correctness; cache by `(normalized_sql,)` in-process for one request.

- **1B:** Change tool return type to **`{ "markdown": "...", "frame": {...} }`** — larger refactor for `TOOL_REGISTRY` and UI that expects strings.

**Deliverables:**

- New module e.g. `src/copilot/numeric_digest.py` (or `src/sql/result_digest.py`):
  - `digest_markdown_table(result: str) -> TableDigest | None` for **markdown pipe tables** from existing tool output (regex + parser; handle `|`, headers, numeric cells).
  - `digest_sql_result(rows, cols) -> TableDigest` for structured path.
- Unit tests: your **29-row** fixture → sum **3653162**; empty table; single column; non-numeric column ignored.

**Exit criterion:** Given any `query_sales_db` markdown from tests, digest reproduces Excel-sum for identified numeric columns.

---

## Phase 2 — Wire digest into `CopilotAgent` (no UX change yet)

**Goal:** After `_execute`, build **`NumericFactPack`** per tool call (especially `query_sales_db`).

**Steps:**

1. Extend `ToolCall` (or parallel structure) with optional **`result_digest: dict | None`** — *or* keep `result` as str and store digest on `CopilotResult` keyed by tool index.
2. In `_execute` (or immediately after), for each successful `query_sales_db` call:
   - Parse `call.result` with `digest_markdown_table` **or** use structured capture from Phase 1A.
3. Aggregate into **`evidence["numeric_facts"]`**: list of `{ "tool", "sql_preview", "row_count", "sums": {...}, "warnings": [] }`.

**Exit criterion:** `investigate()` returns digests in memory; log them to monologue in debug mode optional.

---

## Phase 3 — Synthesis prompt contract (hard constraints)

**Goal:** Model sees **non-negotiable** numbers.

**Prompt changes (`SYNTHESIS_PROMPT_TMPL`):**

- Inject a block:

```text
=== VERIFIED_NUMERIC_FACTS (DO NOT CONTRADICT; DO NOT RE-SUM MANUALLY) ===
{verified_json}

Rules:
- For any total / sum / “across all outlets” claim about query_sales_db results, use ONLY the values in VERIFIED_NUMERIC_FACTS.
- If the user asked for a breakdown table, you may list rows but MUST NOT state a chain total unless chain_total appears in VERIFIED_NUMERIC_FACTS.
- If chain_total is missing, say: “Use the per-outlet table; I am not stating a chain total without a SUM query.”
```

- Shorten prose cap if needed to leave room for JSON.

**Planner prompt (`PLANNER_PROMPT_TMPL` / examples):**

- Add explicit rule: *“For chain-wide revenue for one day, prefer `SELECT ROUND(SUM(NETAMT),0) AS total_revenue FROM ... WHERE date = ...` in addition to or instead of GROUP BY outlet.”*

**Exit criterion:** Manual run on “Feb 14 revenue all outlets” — planner often emits a **SUM** row; synthesis cites **only** verified block for totals.

---

## Phase 4 — Post-synthesis validation (safety net)

**Goal:** Catch model drift even with a better prompt.

**Approach:**

1. **Extract numbers** from final `response` (regex for `₹[\d,]+` / plain integers in context of “total” / “sum”) — *heuristic, optional*.
2. **Compare** to `VERIFIED_NUMERIC_FACTS.chain_total` (when present).
3. If mismatch:
   - Set **`guardrail_flags`** += `["numeric_mismatch"]``.
   - **Append** a one-line correction footer: *“Verified chain total from SQL: ₹X,YY,YYY (auto-check flagged a discrepancy in the text above).”*  
   - **Do not** silently rewrite the whole paragraph (auditable); optional v2: structured answer template.

**Exit criterion:** Forced bad synthesis in test double → flag + footer appears.

---

## Phase 5 — Contract + UI (`evidence` / Streamlit)

**Goal:** Users see truth without digging expanders.

1. **`CopilotResult`** (in `copilot_brain.py` today; eventually `src/contracts`): add **`evidence: dict`** mirroring API `CopilotResponse.evidence`.
2. **`query_service` / `investigate_copilot_for_ui`:** pass **`evidence`** through to Streamlit dict (already partially done for intent path).
3. **Streamlit (`app/dashboard.py`):** Under assistant message, render a compact **`st.expander("Verified numbers")`** when `evidence.numeric_facts` present — table of tool, row count, sums, flags.

**Exit criterion:** Feb-14 scenario shows **₹3,653,162** in Verified block even if prose is wrong (until Phase 4/3 tighten prose).

---

## Phase 6 — Golden tests & CI

**Fixtures:**

- `tests/fixtures/copilot_numeric/` — markdown table(s) known sum; multi-tool result string.
- **Integration test** (optional, mocked LLM): inject fixed `tool_calls` + synthesis output with wrong total → validator appends correction + flag.

**CI:** Extend existing pytest job; no new services.

**Exit criterion:** CI fails if digest sum regression or validator removed.

---

## Phase 7 — Policy & SQL patterns (stretch)

- **Allowlist** optional columns for auto-sum (`revenue`, `total_revenue`, `NETAMT` aliases).
- **Reject** synthesis use of “average weekly” unless a tool result contains that exact metric (digest can extract labeled scalars from markdown if second query returns one row).
- Document in **`docs/llm-sql-policy.md`**: “chain total requires SUM row or verified digest.”
- **Align planner examples with rules:** today the **example** for “revenue on date X” is `GROUP BY LOCATION_NAME` only — that nudges the model toward breakdown-only SQL. Add a **second example** that is **one-row `SUM(NETAMT)`** for the same date so demos get chain totals without manual summing.

---

## Phase 8 — Multi-tool grounding & attribution (demo killer for “sounds smart, wrong glue”)

**Goal:** Weather + news + SQL in one answer must not produce **numeric or causal cross-contamination**.

**Plan:**

- Extend synthesis template with explicit **sections**: `Sales facts (from query_sales_db)`, `Context (weather/holiday/news)`, `Interpretation`. Model **must not** put revenue figures in the Context section or weather adjectives in the Sales section.
- **Rule:** No sentence that contains **both** a currency amount **and** a weather claim unless the user question explicitly asks for linkage — even then, phrase as **hypothesis** (“possible factors include…”) not fact.
- Add **`evidence.tool_attribution`** optional list: which numbers came from which tool name (filled from digest keys).

**Exit criterion:** Golden multi-tool transcript reviewed — no blended false arithmetic across tools.

---

## Phase 9 — Baseline & comparison discipline (“drop”, “vs average”)

**Goal:** Never state **relative** performance without **two verified numbers** (or one number + explicit “prior period missing”).

**Plan:**

- **Digest extension:** detect common column names (`total_revenue`, `avg`, `baseline`, `week_avg`, etc.) from markdown single-row results.
- **Validator:** if user query implies comparison (`drop`, `vs`, `below average`, `underperforming`) and digest finds **only one** revenue scalar → synthesis prompt gets `COMPARISON_BASELINE: missing` and model must **abstain** on comparative claims.
- Planner rule: for “drop on date D” → minimum tool set = **revenue for D** + **revenue for same weekday window or previous 7d** (same SQL family as existing CRITICAL SQL RULES) — enforce in post-plan lint **or** second planner nudge.

**Exit criterion:** Feb-14 style question either shows **two** numbers from tools or explicitly refuses the comparison.

---

## Phase 10 — Epistemic voice & system prompt tension

**Goal:** Stop **confident wrong** and **confident unfounded** causal stories.

**Observed tension:** `COPILOT_SYSTEM_PROMPT` encourages “never say I cannot answer” and “specific numbers” — that can **fight** abstention when tools are weak.

**Plan:**

- **Patch system prompt:** add a **priority order**: (1) numerical accuracy / tool grounding, (2) clear limits, (3) personality. “Do not fabricate to satisfy (1).”
- Add **fixed closing line** when evidence flags `numeric_mismatch` or `baseline_missing`: one sentence, plain English.
- **Causality rule:** “Why did revenue drop?” → answer structure: **Facts** → **Non-causal context** (holiday, weather as *context only*) → **Hypotheses** labeled as hypotheses → **Data we’d need next** (one SQL suggestion). No single “because” unless tool shows a mechanism (usually never for weather).

**Exit criterion:** Manual review of 10 demo prompts — no false “because” chain.

---

## Phase 11 — Planner reliability (JSON, retries, limits)

**Goal:** Fewer **empty plans**, **malformed JSON**, or **absurd tool chains** that waste demo time.

**Plan:**

- **Structured output / repair loop:** if `json.loads` fails, **one** repair pass with a tiny model call or deterministic bracket extract (already partial) + **validate** each planned tool exists and args are dicts.
- **Cap** max tools per turn (e.g. 5) with monologue message when truncating.
- **Pre-flight SQL** (optional): lightweight `EXPLAIN QUERY PLAN` or parse-only check before execute — only if cost is acceptable; else skip.
- **simulate_scenario** and other high-latency tools: **demo flag** to skip or shorten (see Phase 13).

**Exit criterion:** Chaos prompt suite (5 adversarial strings) does not crash plan step; monologue explains skips.

---

## Phase 12 — Date, year, and scope resolution

**Goal:** “February 14th” without a year must **not** silently pick the wrong `SUBSTR(DT,1,10)`.

**Plan:**

- **`evidence["resolved_query_context"]`**: `{ "date_start": "...", "date_end": "...", "year_assumption": 2026, "source": "sidebar_range|user_explicit|default_dataset_year" }`.
- Resolver module: merge **Streamlit session** date range (if wired through to service later) or **dataset min/max** from `sidebar_bounds` when year missing.
- **Synthesis injection:** “The assistant interpreted dates as …” in `VERIFIED_*` block so the model uses consistent literals.

**Exit criterion:** Ambiguous date questions log resolved range in evidence; wrong-year incidents go to zero in fixture tests.

---

## Phase 13 — Demo UX, degradation, and “boring is good”

**Goal:** Client sees **professional** behavior when anything is broken or slow.

**Plan:**

- **Env / settings flags:** `COPILOT_STRICT_DEMO_MODE`, `COPILOT_MAX_RESPONSE_WORDS`, optional `COPILOT_DISABLE_SCENARIO_TOOL` for demo builds.
- **Streamlit:** banner when `GEMINI_API_KEY` / `OPENROUTER_API_KEY` missing or last call failed; link to runbook.
- **Curated demo path:** document 5–7 **golden questions** that hit verified SQL + intent path; rehearse order for sales narrative.
- **Response template** in strict mode: max bullets, ban generic “review staffing” unless a tool mentioned staffing data.

**Exit criterion:** Runbook section “Client demo checklist” with dry-run steps.

---

## Phase 14 — Telemetry & post-demo review

**Goal:** After demo, you can **prove** what was said and what tools returned.

**Plan:**

- Append-only **JSONL** under `var/copilot_traces/` (gitignored): `query_id`, timestamps, tool names, `sql_hash`, digest sums, `guardrail_flags`, first-N chars of synthesis (optional redact).
- **PII policy:** no full email contents; truncate SQL args in logs.

**Exit criterion:** One demo session replayable from logs for debugging.

---

## Phase 15 — Intent path expansion (parallel, fast win after Phase 1–3)

**Goal:** More questions **never** hit fragile synthesis for the numeric core.

**Plan:**

- Add intents for: **single-day chain `SUM`**, **single outlet + date range**, **“revenue on {date}”** with explicit ISO in text — each returns markdown + digest the same way as today’s intent path.
- Tie to **`use_guarded_sql_pipeline`**; document in REBUILD Mark II.

**Exit criterion:** Demo script questions 1–3 hit intent SQL with **deterministic** totals.

---

## Rollout order (recommended)

| Order | Phase | Risk | User-visible |
| ----- | ----- | ---- | -------------- |
| 1 | Phase 1 digest + tests | Low | None |
| 2 | Phase 2 wire + Phase 3 prompt + **Phase 7 example fix** | Medium | Better numbers |
| 3 | Phase 4 validator | Low | Footer / flags |
| 4 | Phase 5 UI + API evidence | Low | Verified expander |
| 5 | Phase 9 baseline discipline + **Phase 10** prompt patch | Medium | Honest comparisons |
| 6 | Phase 8 multi-tool sections | Medium | Cleaner structure |
| 7 | Phase 12 date resolution | Medium | Fewer wrong-year answers |
| 8 | Phase 6 goldens + **Phase 14** trace | Low | CI + ops |
| 9 | Phase 11 planner hardening | Medium | Fewer plan failures |
| 10 | Phase 13 strict demo mode | Low | Demo checklist |
| 11 | Phase 15 intent expansion | Medium | More deterministic paths |

**Feature flags (recommended):**

- `COPILOT_NUMERIC_VALIDATION` — Phase 4 footer on/off.
- `COPILOT_STRICT_DEMO_MODE` — Phase 13 template + caps + optional tool disables.

---

## Out of scope (explicit)

- **Perfect causal inference** from weather/news to sales (remain hypothesis-level only).
- **Legal / compliance** review of log retention (caller’s responsibility).
- **Full JSON intent schema** — remains parallel; **Phase 15** is the **thin** intent expansion without full schema machinery.

---

## Gap inventory (symptom → plan)

| Symptom | Primary phase |
| -------- | -------------- |
| Wrong chain total from table | 1–4, 7 |
| “Vs weekly average” invented | 3, 4, 7, **9** |
| Weather + revenue in one causal sentence | **8**, **10** |
| Wrong year / ambiguous date | **12** |
| Table truncated, user thinks it’s complete | 1, **1A footer**, **13** |
| Plan JSON garbage / no tools | **11** |
| Demo nervous breakdown on missing API | **13** |
| Post-demo “what went wrong?” | **14** |
| Still too much LLM for simple totals | **15** |

---

## Ownership summary

| File / area | Changes |
| ----------- | ------- |
| `src/copilot/numeric_digest.py` (new) | Parse / digest / sums |
| `src/copilot/query_context.py` (new, optional) | Date/year resolution for evidence |
| `scripts/copilot_brain.py` | Digests, prompt injection, validator, `CopilotResult.evidence`, planner examples, system prompt patch, multi-tool synthesis sections |
| `src/contracts/copilot.py` | Typed `evidence` / docstring for `numeric_facts`, `resolved_query_context`, flags |
| `src/services/query_service.py` | Bubble full `evidence` from legacy `CopilotResult` |
| `app/dashboard.py` | Verified numbers expander; demo banner; strict mode hooks |
| `src/config/settings.py` | Feature flags for validation + strict demo |
| `tests/test_numeric_digest.py` (new) | Goldens |
| `tests/fixtures/copilot_numeric/` (new) | Markdown + multi-tool fixtures |
| `docs/runbook.md` | Client demo checklist + flags |
| `docs/llm-sql-policy.md` | Link this plan + SUM-row rule |

---

## First implementation ticket (smallest vertical slice)

1. Add **`numeric_digest`** + tests for **markdown pipe table** → correct sum for the 29-outlet fixture.  
2. After `_execute` in `CopilotAgent.investigate`, build **`verified_json`** for `query_sales_db` only.  
3. Append **`VERIFIED_NUMERIC_FACTS`** to synthesis prompt.  

4. **Same PR:** add planner **example** line for **one-row `SUM(NETAMT)`** by date (Phase 7 alignment) so chain totals are less often “29-row mental math.”  
5. Manual retest: same Feb 14 question — expect model to use digest total or abstain; check evidence JSON in logs if Phase 14 exists later.

That slice removes the **worst** class of numeric error; **Phases 8–10 and 12–13** are what make the **whole answer** demo-safe (no fake baselines, no causal mush, no wrong year).

---

## Phases 16–21 — Trust hardening bundle (2026)

| Phase | Topic | Implementation |
| ----- | ----- | ---------------- |
| **16** | Premise / rank | `src/copilot/premise_check.py` — decline wording + one ISO date → SQLite `RANK()` over daily chain revenue; `evidence["premise_check"]`; `copilot_premise_rank_window` setting. |
| **17** | Plan augment + planner | `scripts/copilot_brain.py` — top-days SQL augment for decline + single date; planner comparison rule + JSON example; `parse_planner_tool_plan` + one retry (`src/copilot/planner_parse.py`). |
| **18** | Structured synthesis | Four headings (**Data facts / Scope / Context / Possible explanations**), `PREMISE_CHECK` + `DATA_SCOPE` blocks; system prompt **priority order** (numbers → premise → limits → tone). |
| **19** | Data scope + freshness | `src/copilot/data_scope.py` — `max_invoice_date`, outlet count, not-in-DB list; merged into evidence and synthesis. |
| **20** | UI + tab safety | `app/dashboard.py` — `premise_conflict` warning; trust expander JSON; per-action `try/except` on Copilot chat / morning brief steps / live anomaly column / simulator subpaths where failures are common. |
| **21** | Audit bundle | Parameterized intent SQL (`fetch_select_as_markdown_params`); `numeric_mismatch_low`; `causal_postcheck` + `COPILOT_CAUSAL_POSTCHECK`; optional `sql_guard` UNION block + table allowlist; LLM temperature/token caps; positive-Z anomalies; CI ruff on selected `scripts/`; API safety documented in `docs/runbook.md`. |

---

## Implementation log

| Date | Delivered |
| ---- | --------- |
| 2026-04-27 | **`src/copilot/numeric_digest.py`**: largest GFM pipe-table → per-column sums (`digest_markdown_tables`). **`tests/test_numeric_digest.py`**. **`CopilotAgent`**: after `_execute`, builds `evidence["numeric_facts"]`, injects **`VERIFIED_NUMERIC_FACTS`** JSON + rules into **`SYNTHESIS_PROMPT_TMPL`**. **`CopilotResult.evidence`**. Planner **second example** for one-row `SUM(NETAMT)` chain total. **`query_service` / `copilot_engine`**: bubble `evidence`; **`run_copilot_query`**: `guardrail_flags` includes `numeric_digest` when facts exist. **Streamlit**: expander **Verified numbers**. **`docs/llm-sql-policy.md`**: chain total + verified block section. **Next:** Phase 4 post-synthesis validator, Phase 5 polish, Phases 8–15 per rollout table. |
| 2026-04-27 (b) | **Phase 4** `numeric_postcheck` (inflated total vs digest) + **`COPILOT_NUMERIC_VALIDATION`**. **Phases 8–10** synthesis + **system prompt** non-negotiables. **Phase 11** max **8** tools per plan. **Phase 12** `resolved_query_context` in evidence. **Phase 13** `COPILOT_STRICT_DEMO_MODE`. **Phase 14** `COPILOT_TRACE_JSONL` → `var/copilot_traces/`. **Phase 15** intent **`single_day_chain_revenue`**. Runbook + `.env.example` flags. |
| 2026-04-27 (c) | **Trust hardening:** `premise_check` rank CTE + **`evidence["premise_check"]`** / **`data_scope`** (incl. `max_invoice_date`). Synthesis **`PREMISE_CHECK`** + **`DATA_SCOPE`** blocks and **Data facts / Scope / Context / Possible explanations** headings; **system prompt priority order**; decline+single-date **plan augment** (top days SQL); **`parse_planner_tool_plan`** (balanced JSON extraction + one retry); **`numeric_mismatch_low`**; **`causal_postcheck`** + **`COPILOT_CAUSAL_POSTCHECK`**; **`LLMManager.generate`** temperature/token caps; **`sqlite_connection`** in `copilot_brain`; UI **premise_conflict** warning + trust expander; contracts + API **`premise_conflict`** flag; tests for premise, planner parse, anomaly, causal; CI ruff on selected `scripts/`. |
