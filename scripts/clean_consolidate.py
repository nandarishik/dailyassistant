"""
QAFFEINE Sales Data Cleaning & Consolidation Script
=====================================================
Extracts, standardises, merges, and validates the 4 primary sales sheets
from 'Sales Report.xlsx' into unified cleaned CSVs.

Output:
  data_processed/cleaned_sales_items.csv   - Item-level fact table (Tax Charge base)
  data_processed/cleaned_outlet_summary.csv - Outlet daily summary (DSR)
  data_processed/cleaned_hourly_items.csv  - Hourly item breakdown
  data_processed/cleaned_aggregator.csv    - Aggregator (Swiggy/Zomato) channel
  data_processed/cleaning_report.txt       - Validation & cleaning log
"""

import sys
import pandas as pd
import numpy as np
import warnings
import os
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE        = Path(__file__).resolve().parent.parent
RAW_DIR     = BASE / "data_raw"
PROCESSED   = BASE / "data_processed"
SCRIPTS_DIR = BASE / "scripts"

_env_xlsx = os.environ.get("SALES_REPORT_XLSX", "").strip()
if _env_xlsx:
    EXCEL_PATH = Path(_env_xlsx).expanduser()
elif len(sys.argv) > 1:
    EXCEL_PATH = Path(sys.argv[1]).expanduser()
else:
    EXCEL_PATH = BASE / "data_raw" / "Sales Report.xlsx"

for d in [RAW_DIR, PROCESSED, SCRIPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not EXCEL_PATH.is_file():
    print(
        f"ERROR: Excel file not found: {EXCEL_PATH}\n"
        "Set env SALES_REPORT_XLSX to the full path, or run:\n"
        "  python scripts/clean_consolidate.py \"/path/to/Sales Report.xlsx\"",
        file=sys.stderr,
    )
    sys.exit(1)

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LINES = []

def log(msg=""):
    print(msg)
    LOG_LINES.append(msg)

log("=" * 70)
log("QAFFEINE SALES DATA CLEANING REPORT")
log(f"Run timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log(f"Source file   : {EXCEL_PATH.name}")
log("=" * 70)

# ─── Load raw Excel once ──────────────────────────────────────────────────────
log("\nLoading workbook...")
xl = pd.ExcelFile(EXCEL_PATH, engine="openpyxl")
log(f"Workbook loaded. Available sheets: {len(xl.sheet_names)}")

# ─── Helper utilities ─────────────────────────────────────────────────────────

def read_sheet(sheet_name, header_row):
    """Read sheet with known header row, strip column names."""
    df = pd.read_excel(xl, sheet_name=sheet_name, header=header_row, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how="all").reset_index(drop=True)

def normalise_col(text):
    return str(text).lower().strip()

def find_col(columns, candidates):
    """Return first matching column name from candidate keywords (case-insensitive)."""
    for cand in candidates:
        for col in columns:
            if cand in normalise_col(col):
                return col
    return None

def safe_date(series):
    """Parse a date series robustly, return YYYY-MM-DD strings."""
    parsed = pd.to_datetime(series, errors="coerce")
    return parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), other=np.nan)

def clean_numeric(series):
    """Coerce a column to numeric, fill NaN with 0."""
    return pd.to_numeric(series, errors="coerce").fillna(0)

def standardise(df, outlet_candidates, item_candidates, revenue_candidates,
                date_candidates, qty_candidates=None, extra_cols=None):
    """
    Map raw columns to standard schema and return cleaned DataFrame.
    Always produces: date, outlet_name, item_name, net_revenue, qty (if available).
    extra_cols: list of (std_name, [candidates]) for additional fields.
    """
    std = pd.DataFrame()

    # Date
    date_col = find_col(df.columns, date_candidates)
    if date_col:
        std["date"] = safe_date(df[date_col])
    else:
        std["date"] = np.nan

    # Outlet name
    outlet_col = find_col(df.columns, outlet_candidates)
    if outlet_col:
        std["outlet_name"] = df[outlet_col].str.strip()
    else:
        std["outlet_name"] = np.nan

    # Item name
    item_col = find_col(df.columns, item_candidates)
    if item_col:
        std["item_name"] = df[item_col].str.strip()
    else:
        std["item_name"] = np.nan

    # Net revenue
    rev_col = find_col(df.columns, revenue_candidates)
    if rev_col:
        std["net_revenue"] = clean_numeric(df[rev_col])
    else:
        std["net_revenue"] = 0.0

    # Quantity (optional)
    if qty_candidates:
        qty_col = find_col(df.columns, qty_candidates)
        if qty_col:
            std["quantity"] = clean_numeric(df[qty_col])
        else:
            std["quantity"] = np.nan

    # Extra columns
    if extra_cols:
        for std_name, candidates in extra_cols:
            col = find_col(df.columns, candidates)
            if col:
                std[std_name] = df[col].str.strip()
            else:
                std[std_name] = np.nan

    return std

def validate_and_save(df, name, csv_path):
    """Validate: fill net_revenue NaN→0, drop rows where outlet_name is missing. Save."""
    before = len(df)

    # Fill any remaining NaN in net_revenue
    df["net_revenue"] = df["net_revenue"].fillna(0)

    # Drop rows with missing outlet_name
    df = df[df["outlet_name"].notna() & (df["outlet_name"].str.strip() != "")]
    after = len(df)

    df.to_csv(csv_path, index=False, encoding="utf-8")

    log(f"\n--- {name} ---")
    log(f"  Rows before validation : {before:,}")
    log(f"  Rows after  validation : {after:,}  (dropped {before - after:,} missing outlet)")
    log(f"  Columns                : {list(df.columns)}")
    log(f"  net_revenue nulls      : 0 (filled)")
    log(f"  Date range             : {df['date'].min()} → {df['date'].max()}")
    if "outlet_name" in df.columns:
        log(f"  Unique outlets         : {df['outlet_name'].nunique()} → {sorted(df['outlet_name'].dropna().unique())[:5]}...")
    if "item_name" in df.columns and df["item_name"].notna().any():
        log(f"  Unique items           : {df['item_name'].nunique()}")
    log(f"  Saved to               : {csv_path}")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TAX CHARGE — Primary item-level fact table
#    Header row 3, 4,140 rows, 54 columns
# ═══════════════════════════════════════════════════════════════════════════════
log("\n\n[1/4] Processing: Tax Charge  (primary item-level fact table)")
log("-" * 60)

tc_raw = read_sheet("Tax Charge", header_row=3)
log(f"  Raw shape : {tc_raw.shape}")

tc = standardise(
    tc_raw,
    outlet_candidates = ["location name", "location"],
    item_candidates   = ["product name", "pos display name", "item"],
    revenue_candidates = ["net amt", "net_amt", "netamt", "total value"],
    date_candidates   = ["date"],
    qty_candidates    = ["sales qty", "qty"],
    extra_cols        = [
        ("brand",           ["brand name", "brand"]),
        ("channel",         ["channel type", "channel"]),
        ("bill_no",         ["bill no", "bill"]),
        ("product_group",   ["product group", "group"]),
        ("spl_category",    ["product special category", "spl category"]),
        ("basic_rate",      ["baiscrate", "basic rate", "rate"]),
        ("cgst",            ["cgst amt"]),
        ("sgst",            ["sgst amt"]),
        ("total_gst",       ["total gst amt"]),
        ("kot_time",        ["kot print time", "kot"]),
        ("city",            ["city"]),
        ("order_taker",     ["order taker"]),
    ],
)

taxi_out = PROCESSED / "cleaned_sales_items.csv"
tc = validate_and_save(tc, "Tax Charge → cleaned_sales_items.csv", taxi_out)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ITEM WISE HOURLY SALE — Hourly item breakdown
#    Header row 3, 3,452 rows, 15 columns
# ═══════════════════════════════════════════════════════════════════════════════
log("\n\n[2/4] Processing: ITEM WISE HOURLY SALE  (hourly item dimensions)")
log("-" * 60)

ih_raw = read_sheet("ITEM WISE HOURLY SALE", header_row=3)
log(f"  Raw shape : {ih_raw.shape}")

ih = standardise(
    ih_raw,
    outlet_candidates  = ["location"],
    item_candidates    = ["product name", "item"],
    revenue_candidates = ["net amt", "netamt"],
    date_candidates    = ["date"],
    qty_candidates     = ["qty"],
    extra_cols         = [
        ("brand",       ["brand name", "brand"]),
        ("wok_id",      ["wok id", "wokid"]),
        ("hour_slot",   ["hours", "hour"]),
        ("order_type",  ["type"]),
        ("basic_amt",   ["basic amt"]),
        ("void_amt",    ["void amt"]),
        ("product_id",  ["productid", "product id"]),
        ("day_no",      ["dayno"]),
        ("day_of_week", ["day of week"]),
    ],
)

ih_out = PROCESSED / "cleaned_hourly_items.csv"
ih = validate_and_save(ih, "ITEM WISE HOURLY SALE → cleaned_hourly_items.csv", ih_out)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DSR — Daily outlet-level revenue summary
#    Header row 6, 46 rows, 43 columns
# ═══════════════════════════════════════════════════════════════════════════════
log("\n\n[3/4] Processing: DSR  (daily outlet summary)")
log("-" * 60)

dsr_raw = read_sheet("DSR", header_row=6)
log(f"  Raw shape : {dsr_raw.shape}")

dsr = standardise(
    dsr_raw,
    outlet_candidates  = ["restaurant name", "restaurant", "location"],
    item_candidates    = ["food sale", "brand name"],      # no item col; food/beverage split
    revenue_candidates = ["total net sale", "net sale", "total net"],
    date_candidates    = ["date"],
    qty_candidates     = ["total order count", "order count"],
    extra_cols         = [
        ("restaurant_id",       ["restaurant id"]),
        ("brand",               ["brand name", "brand"]),
        ("city",                ["city"]),
        ("state",               ["state"]),
        ("gross_sale",          ["total gross sale", "gross sale"]),
        ("total_discount",      ["total discount"]),
        ("dine_in_net",         ["dine in net sale"]),
        ("carry_out_net",       ["carry out net sale"]),
        ("delivery_net",        ["delivery net sale"]),
        ("dine_in_orders",      ["dine in order count"]),
        ("carry_out_orders",    ["carry  out order count", "carry out order count"]),
        ("delivery_orders",     ["delivery order count"]),
        ("pax",                 ["pax count", "pax"]),
        ("cash_amt",            ["cash amt"]),
        ("card_amt",            ["creditcard amt", "card amt"]),
        ("upi_amt",             ["upi amt"]),
        ("void_order_amt",      ["void order amt"]),
        ("cancel_count",        ["cancel count"]),
        ("void_bill_count",     ["void bill count"]),
        ("total_bill_amt",      ["total bill amt"]),
    ],
)

dsr_out = PROCESSED / "cleaned_outlet_summary.csv"
dsr = validate_and_save(dsr, "DSR → cleaned_outlet_summary.csv", dsr_out)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. AGGREGATOR DETAILS — Online delivery channel (Swiggy / Zomato)
#    Header row 1, 35 rows, 11 columns
# ═══════════════════════════════════════════════════════════════════════════════
log("\n\n[4/4] Processing: Aggregator Details  (online delivery channel)")
log("-" * 60)

ag_raw = read_sheet("Aggregator Details", header_row=1)
log(f"  Raw shape : {ag_raw.shape}")

ag = standardise(
    ag_raw,
    outlet_candidates  = ["restaurant name", "restaurant"],
    item_candidates    = ["aggregator name"],             # aggregator = channel/item dimension here
    revenue_candidates = ["net sales", "net sale"],
    date_candidates    = ["date"],
    qty_candidates     = ["order count"],
    extra_cols         = [
        ("restaurant_id",       ["restaurant id"]),
        ("brand",               ["brand name", "brand"]),
        ("aggregator",          ["aggregator name"]),
        ("gst",                 ["gst"]),
        ("delivery_charges",    ["delivery charges"]),
        ("packaging_charges",   ["packaging charges"]),
        ("bill_amt",            ["bill amt"]),
    ],
)

ag_out = PROCESSED / "cleaned_aggregator.csv"
ag = validate_and_save(ag, "Aggregator Details → cleaned_aggregator.csv", ag_out)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. COLUMN ALIGNMENT CHECK — Verify common keys are identical across tables
# ═══════════════════════════════════════════════════════════════════════════════
log("\n\n" + "=" * 70)
log("COLUMN ALIGNMENT CHECK (common keys across all tables)")
log("=" * 70)

tables = {
    "cleaned_sales_items"     : tc,
    "cleaned_hourly_items"    : ih,
    "cleaned_outlet_summary"  : dsr,
    "cleaned_aggregator"      : ag,
}
common_keys = ["date", "outlet_name", "net_revenue"]

for tname, tdf in tables.items():
    present = [k for k in common_keys if k in tdf.columns]
    missing = [k for k in common_keys if k not in tdf.columns]
    log(f"  {tname:<30}  present={present}  missing={missing}")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
log("\n\n" + "=" * 70)
log("FINAL OUTPUT SUMMARY")
log("=" * 70)

total_rows = sum(len(t) for t in tables.values())
csvs = list(PROCESSED.glob("cleaned_*.csv"))
log(f"\n  Output directory  : {PROCESSED}")
log(f"  CSV files created : {len(csvs)}")
for csv in sorted(csvs):
    size_kb = csv.stat().st_size // 1024
    log(f"    {csv.name:<40} {size_kb:>5} KB")
log(f"\n  Total cleaned rows across all tables : {total_rows:,}")
log(f"\n  Primary fact table (cleaned_sales_items.csv) :")
log(f"    Rows    : {len(tc):,}")
log(f"    Columns : {len(tc.columns)}")
log(f"    Outlets : {tc['outlet_name'].nunique()}")
log(f"    Items   : {tc['item_name'].nunique()}")
log(f"    Revenue : INR {tc['net_revenue'].sum():,.2f}")

# ─── Save cleaning report ─────────────────────────────────────────────────────
report_path = PROCESSED / "cleaning_report.txt"
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG_LINES))

log(f"\n  Cleaning report saved : {report_path}")
log("\nDone.")
