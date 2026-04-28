# Data dictionary (high level)

The app targets a single SQLite database (default `database/AI_DATABASE.DB`). Paths are controlled by `APP_DB_PATH`.

## Core fact tables (KPI + Copilot SQL)

| Table | Purpose |
| ----- | ------- |
| `AI_TEST_INVOICEBILLREGISTER` | Header-level sales: `DT`, `LOCATION_NAME`, `NETAMT`, `TRNNO`, payment splits, `PAX`. Use `SUBSTR(DT, 1, 10)` for calendar dates. |
| `AI_TEST_TAXCHARGED_REPORT` | Line-level items: `DT`, `LOCATION_NAME`, `PRODUCT_NAME`, `NET_AMT`, `QTY`, `ORDERTYPE_NAME`, `TRNNO`, `GROUP_NAME`, `ORDER_STARTTIME`. |

## Context / intelligence

| Table | Purpose |
| ----- | ------- |
| `context_intelligence` | Pre-enriched rows per `date`: holiday flags, weather, news/disruptors (Copilot tools read here first). |

## JSON artifacts (not in SQLite)

| Artifact | Purpose |
| -------- | ------- |
| `var/basket_results.json` (preferred) or `database/basket_results.json` | Basket / combo outputs for sidebar “power combo” signal. |

For column-level profiling of one-off extracts, see archived notes under `_one_off/` (not loaded by the app).
