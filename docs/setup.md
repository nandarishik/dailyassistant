# QAFFEINE / DailyAssistant — Local setup

**Product roadmap (Mark II):** see [REBUILD_MARK2.md](REBUILD_MARK2.md) for the canonical rebuild plan, baseline status, and remaining tracks.

**Operations:** [runbook.md](runbook.md) (flags, smoke checks, artifacts). **Schema / policy:** [data-dictionary.md](data-dictionary.md), [llm-sql-policy.md](llm-sql-policy.md).

## 1. Python environment

- Python 3.11+ recommended (match your team policy).
- From the repository root (`dailyassistant-copilot_rebase/`):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

If `.venv` already exists, only activate it and run `pip install -r requirements.txt` again when dependencies change.

## 2. Environment variables

- Copy [`.env.example`](../.env.example) to **`.env`** in the **repository root** (same folder as `requirements.txt`).
- Load order at runtime: **`<repo>/.env` first**, then **`<repo>/../.env`** if present (legacy). Keys in the repo `.env` win over the parent file.

Never commit `.env` (it is gitignored).

## 3. Database (required for the Streamlit app)

The dashboard, copilot, anomaly engine, forecaster training, and basket analysis expect **SQLite tables** including:

- `AI_TEST_INVOICEBILLREGISTER`
- `AI_TEST_TAXCHARGED_REPORT`
- `AI_TEST_ONLINEORDER` (if used)
- `context_intelligence` (created/updated by the context engine)

**Canonical file:** `database/AI_DATABASE.DB` (override with env `APP_DB_PATH`).

Place your packaged database (e.g. from zip) at:

```text
dailyassistant-copilot_rebase/database/AI_DATABASE.DB
```

### Important: `build_database.py` vs the app

[`scripts/build_database.py`](../scripts/build_database.py) loads **cleaned CSVs** into tables named `fact_sales`, `hourly_sales`, and `outlet_summary`. The **Streamlit app and agents query `AI_TEST_*` tables**, which that script does **not** create.

- For the current UI and copilot, use the **prebuilt `AI_DATABASE.DB`** that contains `AI_TEST_*` (or extend the build pipeline in a future change).
- Do not assume that running only `build_database.py` will make the dashboard work.

## 4. Optional data pipeline

- **Excel → cleaned CSVs:** [`scripts/clean_consolidate.py`](../scripts/clean_consolidate.py)  
  - Default input: `data_raw/Sales Report.xlsx` under the repo.  
  - Or set `SALES_REPORT_XLSX` to the full path, or pass the path as the first CLI argument.

- **Context / weather / news:** `python scripts/universal_context.py`

- **Basket JSON:** `python scripts/basket_analysis.py` → `database/basket_results.json`

- **Forecaster model:** `python scripts/forecaster.py` → `models/revenue_forecaster.joblib`

## 5. Run the app

From the repository root (so `src` and `scripts` resolve correctly), with the venv activated:

```bash
PYTHONPATH=. streamlit run app/dashboard.py
# or: PYTHONPATH=. .venv/bin/python -m streamlit run app/dashboard.py
```

If imports fail, ensure your current working directory is the repository root and `PYTHONPATH` includes it (e.g. `export PYTHONPATH=.` on Unix).

## 6. Git remote and `copilot_rebase` branch

Canonical GitHub repo: [nandarishik/dailyassistant](https://github.com/nandarishik/dailyassistant). Active development branch for this codebase: **`copilot_rebase`** ([tree view](https://github.com/nandarishik/dailyassistant/tree/copilot_rebase)).

If `origin` is not set yet:

```bash
git remote add origin https://github.com/nandarishik/dailyassistant.git
```

Fetch and work on the remote branch (requires GitHub auth: HTTPS login, credential helper, or SSH):

```bash
git fetch origin copilot_rebase
git checkout -B copilot_rebase origin/copilot_rebase
```

To publish local commits on that branch:

```bash
git push -u origin copilot_rebase
```

If HTTPS prompts fail in your environment, use SSH instead: `git remote set-url origin git@github.com:nandarishik/dailyassistant.git`.

## 7. Tests (optional)

From the repo root, with dev extras from `pyproject.toml`:

```bash
pip install -e ".[dev]"
pytest
```
