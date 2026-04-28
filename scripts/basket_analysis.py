"""
QAFFEINE — Market Basket Analysis & Menu Engineering
======================================================
Analyses transactional tables in AI_DATABASE.DB to produce:

  1. Product Affinity pairs      — Support, Confidence, Lift
  2. Menu Engineering Matrix     — Star / Plowhorse / Puzzle / Dog
  3. Power Combo Recommendations — top untapped bundles with AOV lift
  4. Strategic Brief             — written to database/strategic_brief.txt

Run from repository root:
    python scripts/basket_analysis.py
"""

import os, sys, sqlite3, json, itertools, math, datetime
from pathlib import Path
from collections import defaultdict
from src.config.env import load_app_dotenv
from src.config.settings import resolve_db_path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── Paths ────────────────────────────────────────────────────────────────────
BASE      = Path(__file__).resolve().parent.parent
DB_PATH   = resolve_db_path(BASE)
BRIEF_OUT = BASE / "database" / "strategic_brief.txt"
JSON_OUT  = BASE / "database" / "basket_results.json"
load_app_dotenv(BASE)

LINES: list[str] = []
def log(msg: str = "") -> None:
    print(msg);  LINES.append(str(msg))
def section(t: str) -> None:
    log(); log("=" * 68); log(f"  {t}"); log("=" * 68)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 1 — DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════

def load_transactions(conn: sqlite3.Connection) -> tuple[dict, dict, dict, int]:
    """
    Returns:
        bill_items   : {bill_no -> [item_name, ...]}
        item_revenue : {item_name -> total_net_revenue}
        item_qty     : {item_name -> total_quantity}
        total_bills  : int
    """
    # Push GROUP BY to SQLite engine to significantly reduce Python memory footprint
    rows = conn.execute(
        "SELECT TRNNO AS bill_no, PRODUCT_NAME AS item_name, SUM(NET_AMT) AS net_revenue, SUM(QTY) AS quantity FROM AI_TEST_TAXCHARGED_REPORT "
        "WHERE PRODUCT_NAME IS NOT NULL AND PRODUCT_NAME != '' GROUP BY TRNNO, PRODUCT_NAME"
    ).fetchall()

    bill_items:   dict[str, list[str]] = defaultdict(list)
    item_revenue: dict[str, float]     = defaultdict(float)
    item_qty:     dict[str, float]     = defaultdict(float)
    item_price:   dict[str, list]      = defaultdict(list)

    for bill_no, item, rev, qty in rows:
        bill_items[bill_no].append(item)
        item_revenue[item] += (rev or 0)
        item_qty[item]     += (qty or 0)

    # avg basic_rate per item (proxy for margin)
    for item, avg_price in conn.execute(
        "SELECT PRODUCT_NAME AS item_name, AVG(BASICRATE) FROM AI_TEST_TAXCHARGED_REPORT "
        "WHERE PRODUCT_NAME IS NOT NULL GROUP BY PRODUCT_NAME"
    ).fetchall():
        item_price[item] = float(avg_price or 0)

    total_bills = len(bill_items)
    return (dict(bill_items), dict(item_revenue),
            dict(item_qty), dict(item_price), total_bills)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 2 — MARKET BASKET ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def compute_affinity_pairs(
    bill_items:  dict[str, list[str]],
    total_bills: int,
    min_support: int = 3,           # appears in at least N bills
    top_n:       int = 30,
) -> list[dict]:
    """
    Compute Support, Confidence, and Lift for all item pairs.

    Definitions:
      Support(A,B)    = bills_with_A_and_B / total_bills
      Confidence(A→B) = bills_with_A_and_B / bills_with_A
      Lift(A,B)       = Support(A,B) / (Support(A) * Support(B))
                        (> 1 = positively associated)

    Returns top_n pairs sorted by Lift (desc), filtered by min_support.
    """
    # Single-item support counts
    item_bill_count: dict[str, int] = defaultdict(int)
    for items in bill_items.values():
        for item in set(items):          # set → avoid double-counting in same bill
            item_bill_count[item] += 1

    # Pair co-occurrence
    pair_count: dict[tuple, int] = defaultdict(int)
    for items in bill_items.values():
        unique = list(set(items))
        for a, b in itertools.combinations(sorted(unique), 2):
            pair_count[(a, b)] += 1

    results = []
    for (a, b), co_count in pair_count.items():
        if co_count < min_support:
            continue

        sup_a  = item_bill_count[a] / total_bills
        sup_b  = item_bill_count[b] / total_bills
        sup_ab = co_count / total_bills
        conf_ab = sup_ab / sup_a if sup_a > 0 else 0
        conf_ba = sup_ab / sup_b if sup_b > 0 else 0
        lift    = sup_ab / (sup_a * sup_b) if sup_a * sup_b > 0 else 0

        results.append({
            "item_a"     : a,
            "item_b"     : b,
            "co_count"   : co_count,
            "support"    : round(sup_ab,  4),
            "conf_a_b"   : round(conf_ab, 4),
            "conf_b_a"   : round(conf_ba, 4),
            "lift"       : round(lift,    3),
        })

    results.sort(key=lambda x: (-x["lift"], -x["co_count"]))
    return results[:top_n]


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 3 — MENU ENGINEERING MATRIX
# ═══════════════════════════════════════════════════════════════════════════

def compute_menu_matrix(
    item_revenue: dict[str, float],
    item_qty:     dict[str, float],
    item_price:   dict[str, float],
    min_qty:      int = 2,           # filter noise
) -> list[dict]:
    """
    Four-quadrant Menu Engineering:
        ┌──────────────┬─────────────┐
        │  PUZZLE      │  STAR       │  ← High profit margin / price
        │  (Low pop)   │  (High pop) │
        ├──────────────┼─────────────┤
        │  DOG         │  PLOWHORSE  │  ← Low profit margin / price
        │  (Low pop)   │  (High pop) │
        └──────────────┴─────────────┘
           Low qty            High qty

    Popularity threshold : median quantity sold
    Profit threshold     : median average price (proxy for margin)
    """
    items = [
        {
            "item_name"    : name,
            "total_revenue": round(item_revenue.get(name, 0), 2),
            "total_qty"    : item_qty.get(name, 0),
            "avg_price"    : round(item_price.get(name, 0), 2),
        }
        for name in item_revenue
        if item_qty.get(name, 0) >= min_qty
    ]

    if not items:
        return []

    # Medians
    qtys   = sorted(x["total_qty"]  for x in items)
    prices = sorted(x["avg_price"]  for x in items)
    med_qty   = qtys[len(qtys) // 2]
    med_price = prices[len(prices) // 2]

    QUADRANT_MAP = {
        (True,  True):  ("Star",       "⭐", "Maintain — high-volume, high-margin",       "green"),
        (False, True):  ("Puzzle",     "🔮", "Promote — high-margin but under-ordered",   "blue"),
        (True,  False): ("Plowhorse",  "🐴", "Reposition — popular but low-margin",       "orange"),
        (False, False): ("Dog",        "🐕", "Review/Remove — low-volume, low-margin",    "red"),
    }

    for item in items:
        high_pop    = item["total_qty"]  >= med_qty
        high_profit = item["avg_price"]  >= med_price
        quad, icon, action, color = QUADRANT_MAP[(high_pop, high_profit)]
        item["quadrant"] = quad
        item["icon"]     = icon
        item["action"]   = action
        item["color"]    = color

    items.sort(key=lambda x: (-x["total_revenue"]))
    return items


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 4 — POWER COMBO RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_combo_recommendations(
    affinity_pairs:  list[dict],
    menu_matrix:     list[dict],
    item_price:      dict[str, float],
    current_combos:  set[str] | None = None,
    top_n:           int = 5,
) -> list[dict]:
    """
    Identify the top untapped pairings:
      - Strong lift (> 1.2) but not yet an explicit bundle
      - At least one item is a Star or Puzzle (worth promoting)
      - Ranked by projected AOV = price_A + price_B with ~15% bundle discount

    Returns top_n combo recommendations.
    """
    if current_combos is None:
        current_combos = set()

    quad_map = {x["item_name"]: x["quadrant"] for x in menu_matrix}

    combos = []
    for pair in affinity_pairs:
        a, b  = pair["item_a"], pair["item_b"]
        lift  = pair["lift"]
        sup   = pair["support"]

        # Only pairs with real lift and not already a promoted combo
        combo_key = f"{a}|{b}"
        if combo_key in current_combos or pair["co_count"] < 5:
            continue
        if lift <= 1.0:
            continue

        quad_a = quad_map.get(a, "Unknown")
        quad_b = quad_map.get(b, "Unknown")

        # At least one should be in a desirable quadrant
        if quad_a == "Dog" and quad_b == "Dog":
            continue

        price_a = item_price.get(a, 0)
        price_b = item_price.get(b, 0)
        bundle_price  = round((price_a + price_b) * 0.85, 2)   # 15% bundle discount
        current_aov   = round(price_a + price_b, 2)
        aov_lift_pct  = round(
            ((bundle_price - (price_a if price_a > price_b else price_b)) /
             max(price_a, price_b, 1)) * 100, 1
        ) if max(price_a, price_b) > 0 else 0

        combos.append({
            "item_a"          : a,
            "item_b"          : b,
            "lift"            : lift,
            "co_count"        : pair["co_count"],
            "support_pct"     : round(sup * 100, 2),
            "quad_a"          : quad_a,
            "quad_b"          : quad_b,
            "price_a"         : price_a,
            "price_b"         : price_b,
            "bundle_price"    : bundle_price,
            "regular_aov"     : current_aov,
            "aov_lift_pct"    : aov_lift_pct,
            "combo_label"     : f"{a.split('(')[0].strip()[:28]} + {b.split('(')[0].strip()[:28]}",
        })

    combos.sort(key=lambda x: (-x["lift"], -x["co_count"]))
    return combos[:top_n]


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def run_basket_analysis() -> dict:
    section("QAFFEINE — Market Basket Analysis & Menu Engineering")
    log(f"  Run        : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Database   : {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL;")

    # ── Load data ──────────────────────────────────────────────────────
    log("\n  Loading transactions …")
    bill_items, item_revenue, item_qty, item_price, total_bills = load_transactions(conn)
    multi_item_bills = sum(1 for v in bill_items.values() if len(v) > 1)
    log(f"  Total bills       : {total_bills:,}")
    log(f"  Multi-item bills  : {multi_item_bills:,}  ({multi_item_bills/total_bills*100:.1f}%)")
    log(f"  Unique items      : {len(item_revenue):,}")

    # ── MBA ────────────────────────────────────────────────────────────
    section("MODULE 1 — Product Affinity Pairs (MBA)")
    affinity = compute_affinity_pairs(bill_items, total_bills)
    log(f"  Computed {len(affinity)} high-affinity pairs (min support = 3 bills)\n")
    log(f"  {'ITEM A':<36} {'ITEM B':<36} {'COUNT':>5} {'LIFT':>6} {'CONF A→B':>9}")
    log(f"  {'-'*36} {'-'*36} {'-'*5} {'-'*6} {'-'*9}")
    for p in affinity[:15]:
        a = p["item_a"][:34]; b = p["item_b"][:34]
        log(f"  {a:<36} {b:<36} {p['co_count']:>5} {p['lift']:>6.2f} {p['conf_a_b']*100:>8.1f}%")

    # ── Menu Matrix ────────────────────────────────────────────────────
    section("MODULE 2 — Menu Engineering Matrix")
    matrix = compute_menu_matrix(item_revenue, item_qty, item_price)

    quadrant_counts = defaultdict(int)
    for x in matrix:
        quadrant_counts[x["quadrant"]] += 1

    log("  Quadrant population:")
    for q, icon in [("Star","⭐"),("Puzzle","🔮"),("Plowhorse","🐴"),("Dog","🐕")]:
        log(f"    {icon} {q:<12} : {quadrant_counts[q]} items")

    log()
    log(f"  {'QUADRANT':<12} {'ITEM':<44} {'QTY':>6} {'AVG ₹':>7} {'REV ₹':>10}")
    log(f"  {'-'*12} {'-'*44} {'-'*6} {'-'*7} {'-'*10}")
    for q in ["Star", "Puzzle", "Plowhorse", "Dog"]:
        items_in_q = [x for x in matrix if x["quadrant"] == q]
        for x in items_in_q[:5]:    # show top-5 per quadrant
            name = x["item_name"][:42]
            log(f"  {x['icon']+' '+q:<12} {name:<44} {int(x['total_qty']):>6} "
                f"{x['avg_price']:>7.0f} {x['total_revenue']:>10,.0f}")

    # ── Power Combos ───────────────────────────────────────────────────
    section("MODULE 3 — Power Combo Recommendations")
    combos = get_combo_recommendations(affinity, matrix, item_price)
    log(f"  Top {len(combos)} untapped bundle opportunities:\n")

    for i, c in enumerate(combos, 1):
        log(f"  #{i}  {c['combo_label']}")
        log(f"       Lift={c['lift']:.2f}  Co-purchased {c['co_count']}×  "
            f"Support={c['support_pct']:.1f}%")
        log(f"       Quadrants: {c['quad_a']} + {c['quad_b']}")
        log(f"       Individual: ₹{c['price_a']:.0f} + ₹{c['price_b']:.0f} = ₹{c['regular_aov']:.0f}")
        log(f"       Bundle price (15% off): ₹{c['bundle_price']:.0f}  "
            f"AOV Lift: +{c['aov_lift_pct']:.1f}%")
        log()

    conn.close()

    # ── Save JSON for dashboard ────────────────────────────────────────
    results = {
        "generated_at"   : datetime.datetime.now().isoformat(),
        "total_bills"    : total_bills,
        "multi_item_bills": multi_item_bills,
        "affinity_pairs" : affinity,
        "menu_matrix"    : matrix,
        "power_combos"   : combos,
    }
    JSON_OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  JSON saved → {JSON_OUT}")

    # ── Strategic Brief ────────────────────────────────────────────────
    _write_strategic_brief(results)

    return results


def _write_strategic_brief(r: dict) -> None:
    section("STRATEGIC BRIEF")
    now   = datetime.datetime.now().strftime("%d %b %Y")
    stars = [x for x in r["menu_matrix"] if x["quadrant"] == "Star"][:3]
    dogs  = [x for x in r["menu_matrix"] if x["quadrant"] == "Dog"][:3]
    puzzles = [x for x in r["menu_matrix"] if x["quadrant"] == "Puzzle"][:3]
    combos  = r["power_combos"]

    lines = [
        "",
        "=" * 68,
        f"  QAFFEINE — Strategic Menu Brief",
        f"  Generated : {now}",
        "=" * 68,
        "",
        "EXECUTIVE SUMMARY",
        "─" * 68,
        f"  Week analysed : {now}",
        f"  Total bills   : {r['total_bills']:,}  |  "
        f"Multi-item bills: {r['multi_item_bills']:,} "
        f"({r['multi_item_bills']/r['total_bills']*100:.1f}%)",
        f"  Unique items  : {len(r['menu_matrix'])}",
        "",
        "1. MENU STARS — Protect These at All Costs",
        "─" * 68,
    ]
    for s in stars:
        lines.append(
            f"  ⭐ {s['item_name']:<42}  "
            f"Qty={int(s['total_qty'])}  Rev=₹{s['total_revenue']:,.0f}"
        )
    lines += [
        "  → Action: Premium placement, staff upsell training, never discount.",
        "",
        "2. MENU DOGS — Candidates for Removal / Revision",
        "─" * 68,
    ]
    for d in dogs:
        lines.append(
            f"  🐕 {d['item_name']:<42}  "
            f"Qty={int(d['total_qty'])}  Rev=₹{d['total_revenue']:,.0f}"
        )
    lines += [
        "  → Action: Trial removal for 2 weeks. Monitor bill count impact.",
        "    If retained, rename/reposition with higher margin.",
        "",
        "3. MENU PUZZLES — Hidden Profit Gems (Under-Promoted)",
        "─" * 68,
    ]
    for p in puzzles:
        lines.append(
            f"  🔮 {p['item_name']:<42}  "
            f"Qty={int(p['total_qty'])}  AvgPrice=₹{p['avg_price']:.0f}"
        )
    lines += [
        "  → Action: Feature in menu spotlight, train staff to recommend,",
        "    add to social media highlights.",
        "",
        "4. TOP POWER COMBO RECOMMENDATIONS",
        "─" * 68,
        "   These pairs are organically bought together but not yet offered",
        "   as a bundle. Introducing a 15% bundle price would drive AOV:",
        "",
    ]
    for i, c in enumerate(combos[:5], 1):
        lines += [
            f"  #{i}  {c['combo_label']}",
            f"       Lift: {c['lift']:.2f}x  |  Co-purchased: {c['co_count']}×  "
            f"|  Support: {c['support_pct']:.1f}%",
            f"       Bundle price: ₹{c['bundle_price']:.0f}  "
            f"(save ₹{c['regular_aov']-c['bundle_price']:.0f} vs individual)",
            f"       Quadrant mix: {c['quad_a']} + {c['quad_b']}",
            "",
        ]

    lines += [
        "5. HIGHEST-AFFINITY PRODUCT PAIRS (Top 5 by Lift)",
        "─" * 68,
    ]
    for p in r["affinity_pairs"][:5]:
        lines.append(
            f"  Lift {p['lift']:.2f}x  {p['item_a'][:30]:<30}  ↔  {p['item_b'][:30]}"
        )

    lines += [
        "",
        "─" * 68,
        "  PREPARED BY: QAFFEINE Analytics Engine",
        f"  Data source : AI_DATABASE.DB  |  Script: scripts/basket_analysis.py",
        "=" * 68,
        "",
    ]

    brief_text = "\n".join(lines)
    BRIEF_OUT.write_text(brief_text, encoding="utf-8")
    log(f"  Strategic brief saved → {BRIEF_OUT}")
    log()
    for line in lines:
        log(line)


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_basket_analysis()
