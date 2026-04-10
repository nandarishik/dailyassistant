"""
QAFFEINE AI Assistant — Automated Test Harness
===============================================
Runs 18 diverse business queries against sales.db,
validates results, and writes testing_log.txt.
"""

import sys, sqlite3, pathlib, textwrap, json
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE     = pathlib.Path(r"c:\Users\Admin\Desktop\BrainPowerInternship\QAFFEINE_Prototype")
DB_PATH  = BASE / "database" / "sales.db"
LOG_PATH = BASE / "database" / "testing_log.txt"

conn = sqlite3.connect(str(DB_PATH))

# ─── Test Suite ───────────────────────────────────────────────────────────────
# Each entry: (id, category, question_nl, sql, expected_check_fn, expected_desc)
# expected_check_fn receives a list of row-dicts and returns (pass: bool, note: str)

def first_val(rows, col):
    return rows[0][col] if rows else None

TESTS = [
    # ── Revenue & KPIs ──────────────────────────────────────────────────────
    {
        "id": "KPI-01", "category": "Revenue KPI",
        "question": "What is the total net revenue across all outlets?",
        "sql": "SELECT ROUND(SUM(net_revenue),2) AS total FROM fact_sales",
        "check": lambda r: (abs(first_val(r,"total") - 830632.86) < 1,
                            f"Total = {first_val(r,'total')} (expected ~830632.86)"),
    },
    {
        "id": "KPI-02", "category": "Revenue KPI",
        "question": "Which outlet had the highest total revenue?",
        "sql": """SELECT outlet_name, ROUND(SUM(net_revenue),2) AS rev
                  FROM fact_sales GROUP BY outlet_name ORDER BY rev DESC LIMIT 1""",
        "check": lambda r: ("HITECH" in (first_val(r,"outlet_name") or ""),
                            f"Top outlet = {first_val(r,'outlet_name')}"),
    },
    {
        "id": "KPI-03", "category": "Revenue KPI",
        "question": "What is the average order value (AOV)?",
        "sql": """SELECT ROUND(SUM(net_revenue)/NULLIF(COUNT(DISTINCT bill_no),0),2) AS aov
                  FROM fact_sales""",
        "check": lambda r: (50 < (first_val(r,"aov") or 0) < 700,
                            f"AOV = {first_val(r,'aov')}"),
    },
    # ── Item Analysis ────────────────────────────────────────────────────────
    {
        "id": "ITEM-01", "category": "Item Analysis",
        "question": "What is the top selling item by revenue?",
        "sql": """SELECT item_name, ROUND(SUM(net_revenue),2) AS rev
                  FROM fact_sales WHERE item_name IS NOT NULL
                  GROUP BY item_name ORDER BY rev DESC LIMIT 1""",
        "check": lambda r: ("CAPPUCCINO" in (first_val(r,"item_name") or "").upper(),
                            f"Top item = {first_val(r,'item_name')}"),
    },
    {
        "id": "ITEM-02", "category": "Item Analysis",
        "question": "What are the top 5 items by quantity sold?",
        "sql": """SELECT item_name, SUM(CAST(quantity AS REAL)) AS qty
                  FROM fact_sales WHERE item_name IS NOT NULL
                  GROUP BY item_name ORDER BY qty DESC LIMIT 5""",
        "check": lambda r: (len(r) == 5 and (first_val(r,"qty") or 0) > 100,
                            f"Top item qty = {first_val(r,'qty')}, rows = {len(r)}"),
    },
    {
        "id": "ITEM-03", "category": "Item Analysis",
        "question": "What is the total revenue from BEVERAGES category?",
        "sql": """SELECT ROUND(SUM(net_revenue),2) AS bev_rev FROM fact_sales
                  WHERE UPPER(spl_category) LIKE '%BEVERAGE%'""",
        "check": lambda r: ((first_val(r,"bev_rev") or 0) > 0,
                            f"Beverage revenue = {first_val(r,'bev_rev')}"),
    },
    # ── Outlet Analysis ──────────────────────────────────────────────────────
    {
        "id": "OUTLET-01", "category": "Outlet Analysis",
        "question": "How many outlets are in the dataset?",
        "sql": "SELECT COUNT(DISTINCT outlet_name) AS outlet_count FROM fact_sales",
        "check": lambda r: (first_val(r,"outlet_count") == 6,
                            f"Outlet count = {first_val(r,'outlet_count')} (expected 6)"),
    },
    {
        "id": "OUTLET-02", "category": "Outlet Analysis",
        "question": "Which outlet has the most unique menu items?",
        "sql": """SELECT outlet_name, COUNT(DISTINCT item_name) AS unique_items
                  FROM fact_sales GROUP BY outlet_name ORDER BY unique_items DESC LIMIT 1""",
        "check": lambda r: ((first_val(r,"unique_items") or 0) >= 88,
                            f"Most items = {first_val(r,'unique_items')} at {first_val(r,'outlet_name')}"),
    },
    {
        "id": "OUTLET-03", "category": "Outlet Analysis",
        "question": "What is the revenue breakdown by channel (Dine-In, Carry-Out, Delivery)?",
        "sql": """SELECT channel, ROUND(SUM(net_revenue),2) AS rev
                  FROM fact_sales WHERE channel IS NOT NULL
                  GROUP BY channel ORDER BY rev DESC""",
        "check": lambda r: (len(r) >= 2,
                            f"Channels found = {[x['channel'] for x in r]}"),
    },
    {
        "id": "OUTLET-04", "category": "Outlet Analysis",
        "question": "What is the total revenue from Carry-Out orders?",
        "sql": """SELECT ROUND(SUM(net_revenue),2) AS co_rev FROM fact_sales
                  WHERE UPPER(channel) LIKE '%CARRY%'""",
        "check": lambda r: ((first_val(r,"co_rev") or 0) > 0,
                            f"Carry-Out revenue = {first_val(r,'co_rev')}"),
    },
    # ── Date / Trend Analysis ────────────────────────────────────────────────
    {
        "id": "DATE-01", "category": "Date Trend",
        "question": "Which date had the highest revenue?",
        "sql": """SELECT date, ROUND(SUM(net_revenue),2) AS rev
                  FROM fact_sales GROUP BY date ORDER BY rev DESC LIMIT 1""",
        "check": lambda r: (first_val(r,"date") == "2025-12-06",
                            f"Peak date = {first_val(r,'date')} (expected 2025-12-06)"),
    },
    {
        "id": "DATE-02", "category": "Date Trend",
        "question": "Show me peak hour revenue for Dec 6th",
        "sql": """SELECT hour_slot, ROUND(SUM(net_revenue),2) AS rev
                  FROM hourly_sales WHERE date = '2025-12-06'
                  GROUP BY hour_slot ORDER BY rev DESC LIMIT 5""",
        "check": lambda r: (len(r) > 0,
                            f"Peak hour on Dec 6 = {first_val(r,'hour_slot')} (₹{first_val(r,'rev')})"),
    },
    {
        "id": "DATE-03", "category": "Date Trend",
        "question": "What was the revenue on Dec 7th?",
        "sql": """SELECT ROUND(SUM(net_revenue),2) AS rev FROM fact_sales
                  WHERE date = '2025-12-07'""",
        "check": lambda r: (abs((first_val(r,"rev") or 0) - 82183.96) < 5,
                            f"Dec 7 revenue = {first_val(r,'rev')} (expected ~82183.96)"),
    },
    {
        "id": "DATE-04", "category": "Date Trend",
        "question": "What is the day-of-week with highest order volume?",
        "sql": """SELECT day_of_week, SUM(CAST(quantity AS INTEGER)) AS orders
                  FROM hourly_sales GROUP BY day_of_week ORDER BY orders DESC LIMIT 1""",
        "check": lambda r: (first_val(r,"day_of_week") is not None,
                            f"Highest day = {first_val(r,'day_of_week')} ({first_val(r,'orders')} orders)"),
    },
    # ── Aggregator / Hourly ──────────────────────────────────────────────────
    {
        "id": "HOURLY-01", "category": "Hourly Analysis",
        "question": "Which hour slot has the most orders overall?",
        "sql": """SELECT hour_slot, SUM(CAST(quantity AS INTEGER)) AS orders
                  FROM hourly_sales WHERE hour_slot IS NOT NULL
                  GROUP BY hour_slot ORDER BY orders DESC LIMIT 1""",
        "check": lambda r: (first_val(r,"hour_slot") is not None,
                            f"Peak hour = {first_val(r,'hour_slot')} ({first_val(r,'orders')} orders)"),
    },
    {
        "id": "HOURLY-02", "category": "Hourly Analysis",
        "question": "What is the most popular aggregator (order type) at Hitech City?",
        "sql": """SELECT order_type, SUM(CAST(quantity AS INTEGER)) AS orders
                  FROM hourly_sales WHERE UPPER(outlet_name) LIKE '%HITECH%'
                    AND order_type IS NOT NULL
                  GROUP BY order_type ORDER BY orders DESC LIMIT 1""",
        "check": lambda r: (first_val(r,"order_type") is not None,
                            f"Top order type at Hitech = {first_val(r,'order_type')}"),
    },
    {
        "id": "DSR-01", "category": "Outlet Summary (DSR)",
        "question": "What is the total discount given across all outlets?",
        "sql": "SELECT ROUND(SUM(total_discount),2) AS disc FROM outlet_summary",
        "check": lambda r: (first_val(r,"disc") is not None,
                            f"Total discount = {first_val(r,'disc')}"),
    },
    {
        "id": "DSR-02", "category": "Outlet Summary (DSR)",
        "question": "Which payment method (cash/card/UPI) is most used?",
        "sql": """SELECT 'Cash' AS method, SUM(cash_amt) AS amt FROM outlet_summary
                  UNION ALL
                  SELECT 'Card', SUM(card_amt) FROM outlet_summary
                  UNION ALL
                  SELECT 'UPI', SUM(upi_amt) FROM outlet_summary
                  ORDER BY amt DESC LIMIT 1""",
        "check": lambda r: (first_val(r,"method") is not None,
                            f"Top payment = {first_val(r,'method')} (₹{first_val(r,'amt')})"),
    },
]

# ─── Run tests ────────────────────────────────────────────────────────────────
print("=" * 70)
print("QAFFEINE AI Assistant — Automated Test Harness")
print(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"DB : {DB_PATH}")
print("=" * 70)

results = []
passed = failed = 0

for t in TESTS:
    try:
        cursor = conn.execute(t["sql"])
        cols   = [d[0] for d in cursor.description]
        rows   = [dict(zip(cols, row)) for row in cursor.fetchall()]
        ok, note = t["check"](rows)
        status = "PASS" if ok else "FAIL"
        if ok: passed += 1
        else:  failed += 1
        row_count = len(rows)
    except Exception as e:
        status, note, row_count = "ERROR", str(e), 0

    result = {
        "id": t["id"], "category": t["category"],
        "question": t["question"], "status": status,
        "rows_returned": row_count, "note": note,
        "sql": t["sql"].strip(),
    }
    results.append(result)

    icon = "OK" if status == "PASS" else ("!!" if status == "FAIL" else "XX")
    print(f"[{icon}] {t['id']:12s} {status:5s} | {t['category']:22s} | {note}")

conn.close()

# ─── Summary ──────────────────────────────────────────────────────────────────
total = len(TESTS)
print()
print(f"Results: {passed}/{total} passed  |  {failed} failed")
print(f"Pass rate: {passed/total*100:.1f}%")

# ─── Write log ────────────────────────────────────────────────────────────────
lines = []
lines.append("=" * 70)
lines.append("QAFFEINE AI Assistant — Automated Test Log")
lines.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
lines.append(f"Database  : {DB_PATH}")
lines.append("=" * 70)
lines.append("")

for r in results:
    icon = "PASS" if r["status"] == "PASS" else r["status"]
    lines.append(f"[{icon}] {r['id']} — {r['category']}")
    lines.append(f"  Question     : {r['question']}")
    lines.append(f"  Status       : {r['status']}")
    lines.append(f"  Rows returned: {r['rows_returned']}")
    lines.append(f"  Validation   : {r['note']}")
    lines.append(f"  SQL          : {r['sql'][:120]}{'...' if len(r['sql'])>120 else ''}")
    lines.append("")

lines.append("-" * 70)
lines.append(f"TOTAL : {total}  |  PASSED : {passed}  |  FAILED : {failed}")
lines.append(f"PASS RATE : {passed/total*100:.1f}%")
lines.append("")
lines.append("Category Breakdown:")
from collections import Counter
cats = Counter(r["category"] for r in results)
pass_cats = Counter(r["category"] for r in results if r["status"] == "PASS")
for cat, cnt in sorted(cats.items()):
    lines.append(f"  {cat:25s} {pass_cats.get(cat,0)}/{cnt}")

with open(LOG_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\nLog written: {LOG_PATH}")
