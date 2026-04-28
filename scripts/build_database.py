"""
QAFFEINE SQLite Database Builder
=================================
Creates AI_DATABASE.DB under the project `database/` folder, loads the three
cleaned CSVs, adds indexes, runs verification queries, and saves
schema_info.txt.
"""

import os, sys, sqlite3, pandas as pd
from pathlib import Path
from datetime import datetime
from src.config.env import load_app_dotenv
from src.config.settings import resolve_db_path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE      = Path(__file__).resolve().parent.parent
load_app_dotenv(BASE)
PROC      = BASE / "data_processed"
DB_DIR    = BASE / "database"
DB_PATH   = resolve_db_path(BASE)
SCHEMA_TXT = DB_DIR / "schema_info.txt"

DB_DIR.mkdir(parents=True, exist_ok=True)

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG = []
def log(msg=""):
    print(msg)
    LOG.append(str(msg))

log("=" * 70)
log("QAFFEINE SQLite Database Builder")
log(f"Run       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log(f"Database  : {DB_PATH}")
log("=" * 70)

# ─── Connect ──────────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("PRAGMA journal_mode=WAL;")
log("\nDatabase connection established (WAL mode).")

# ─── Table definitions ────────────────────────────────────────────────────────
# We let pandas infer types via to_sql, then add explicit indexes below.
# A thin DDL wrapper ensures clean re-runs.

TABLES = [
    {
        "table"   : "fact_sales",
        "csv"     : PROC / "cleaned_sales_items.csv",
        "desc"    : "Item-level POS transactions (Tax Charge sheet)",
        "indexes" : ["date", "outlet_name", "item_name"],
    },
    {
        "table"   : "hourly_sales",
        "csv"     : PROC / "cleaned_hourly_items.csv",
        "desc"    : "Item-level hourly breakdown (ITEM WISE HOURLY SALE sheet)",
        "indexes" : ["date", "outlet_name", "item_name"],
    },
    {
        "table"   : "outlet_summary",
        "csv"     : PROC / "cleaned_outlet_summary.csv",
        "desc"    : "Daily outlet-level summary (DSR sheet)",
        "indexes" : ["date", "outlet_name"],
    },
]

# ─── Load & ingest each table ─────────────────────────────────────────────────
for t in TABLES:
    log(f"\n[LOAD] {t['table']}")
    df = pd.read_csv(t["csv"], dtype=str)

    # Coerce numeric columns where possible, leave strings as-is
    for col in df.columns:
        try:
            converted = pd.to_numeric(df[col])
            df[col] = converted
        except (ValueError, TypeError):
            pass

    # Drop & recreate table for idempotency
    cursor.execute(f"DROP TABLE IF EXISTS {t['table']};")
    conn.commit()

    df.to_sql(t["table"], conn, if_exists="replace", index=False)
    rows = cursor.execute(f"SELECT COUNT(*) FROM {t['table']};").fetchone()[0]
    log(f"  Rows loaded  : {rows:,}")
    log(f"  Columns      : {list(df.columns)}")

    # ── Indexes ──────────────────────────────────────────────────────────────
    for col in t["indexes"]:
        if col in df.columns:
            idx_name = f"idx_{t['table']}_{col}"
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {t['table']}({col});"
            )
            log(f"  Index created : {idx_name} ON {t['table']}({col})")
        else:
            log(f"  [SKIP] Index on '{col}' — column not present in {t['table']}")

    conn.commit()

# ─── Verification Queries ─────────────────────────────────────────────────────
log("\n\n" + "=" * 70)
log("VERIFICATION QUERIES")
log("=" * 70)

# Query 1: Top 5 Items by Revenue
log("\n--- Top 5 Items by Revenue (across all outlets) ---")
q1 = """
    SELECT
        item_name,
        ROUND(SUM(net_revenue), 2) AS total_revenue,
        SUM(CAST(quantity AS REAL))  AS total_qty,
        COUNT(*)                     AS transaction_count
    FROM fact_sales
    WHERE item_name IS NOT NULL
    GROUP BY item_name
    ORDER BY total_revenue DESC
    LIMIT 5;
"""
top5 = pd.read_sql_query(q1, conn)
log(top5.to_string(index=False))

# Query 2: Total Revenue per Outlet
log("\n--- Total Revenue per Outlet ---")
q2 = """
    SELECT
        outlet_name,
        ROUND(SUM(net_revenue), 2)  AS total_revenue,
        COUNT(DISTINCT date)        AS trading_days,
        COUNT(*)                    AS line_items,
        COUNT(DISTINCT item_name)   AS unique_items
    FROM fact_sales
    WHERE outlet_name IS NOT NULL
    GROUP BY outlet_name
    ORDER BY total_revenue DESC;
"""
by_outlet = pd.read_sql_query(q2, conn)
log(by_outlet.to_string(index=False))

# Query 3: Revenue trend by date (bonus)
log("\n--- Daily Revenue Trend ---")
q3 = """
    SELECT
        date,
        ROUND(SUM(net_revenue), 2) AS daily_revenue,
        COUNT(*) AS line_items
    FROM fact_sales
    GROUP BY date
    ORDER BY date;
"""
daily = pd.read_sql_query(q3, conn)
log(daily.to_string(index=False))

# ─── Schema Info ──────────────────────────────────────────────────────────────
log("\n\n" + "=" * 70)
log("DATABASE SCHEMA SUMMARY")
log("=" * 70)

schema_lines = []
schema_lines.append("QAFFEINE Prototype | AI_DATABASE.DB Schema Info")
schema_lines.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
schema_lines.append("=" * 70)

all_tables = cursor.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
).fetchall()

for (tbl,) in all_tables:
    row_count = cursor.execute(f"SELECT COUNT(*) FROM {tbl};").fetchone()[0]
    cols_info = cursor.execute(f"PRAGMA table_info({tbl});").fetchall()
    col_names = [c[1] for c in cols_info]
    col_types = [f"{c[1]} ({c[2]})" for c in cols_info]

    block = [
        f"\nTable : {tbl}",
        f"  Rows    : {row_count:,}",
        f"  Columns ({len(col_names)}):",
    ]
    for ct in col_types:
        block.append(f"    - {ct}")

    # Indexes on this table
    idxs = cursor.execute(
        f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='{tbl}';"
    ).fetchall()
    if idxs:
        block.append(f"  Indexes:")
        for idx_name, idx_sql in idxs:
            if idx_sql:                      # skip auto-generated rowid index
                block.append(f"    - {idx_name}")

    schema_lines.extend(block)
    for line in block:
        log(line)

schema_lines.append("\n" + "=" * 70)
schema_lines.append("VERIFICATION RESULTS")
schema_lines.append("=" * 70)
schema_lines.append("\nTop 5 Items by Revenue:")
schema_lines.append(top5.to_string(index=False))
schema_lines.append("\nTotal Revenue per Outlet:")
schema_lines.append(by_outlet.to_string(index=False))
schema_lines.append("\nDaily Revenue Trend:")
schema_lines.append(daily.to_string(index=False))

with open(SCHEMA_TXT, "w", encoding="utf-8") as f:
    f.write("\n".join(schema_lines))

# ─── Close ────────────────────────────────────────────────────────────────────
conn.close()

log(f"\nSchema info saved : {SCHEMA_TXT}")
log(f"Database saved    : {DB_PATH}  ({DB_PATH.stat().st_size // 1024} KB)")
log("\nDone.")
