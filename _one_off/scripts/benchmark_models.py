"""
QAFFEINE — OpenRouter Model Benchmarker
========================================
Queries the OpenRouter /models catalogue and ranks all available models
across three dimensions relevant to the QAFFEINE intelligence layer:

  1. Cost-to-Performance  — cheapest total token cost
  2. SQL / Reasoning Accuracy — proxy: large context window + known-good model families
  3. Quota / Rate Limits  — OpenRouter free-tier RPM is standard; we use ctx as proxy

Run from QAFFEINE_Prototype/:
    python scripts/benchmark_models.py

Outputs:
    database/benchmark_models_report.txt
"""

import os, sys, json, requests, datetime
from pathlib import Path
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── Paths & env ──────────────────────────────────────────────────────────────
BASE     = Path(__file__).resolve().parent.parent
ENV_PATH = BASE.parent / ".env"
OUT_PATH = BASE / "database" / "benchmark_models_report.txt"

load_dotenv(ENV_PATH, override=True)
OR_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

LINES: list[str] = []

def log(msg: str = "") -> None:
    print(msg)
    LINES.append(str(msg))

# ── Scoring weights ──────────────────────────────────────────────────────────
# Known high-quality reasoning/instruction models get a quality bonus
QUALITY_BONUS_MODELS = {
    "meta-llama/llama-3.3-70b-instruct"  : 30,
    "meta-llama/llama-3.1-70b-instruct"  : 25,
    "anthropic/claude-3.5-haiku"          : 35,
    "anthropic/claude-3.5-sonnet"         : 40,
    "anthropic/claude-3-haiku"            : 28,
    "mistralai/mistral-small-2603"        : 22,
    "mistralai/mixtral-8x7b-instruct"     : 20,
    "deepseek/deepseek-chat"              : 25,
    "deepseek/deepseek-r1"                : 30,
    "google/gemini-flash-1.5-8b"         : 18,
    "meta-llama/llama-3.2-90b-vision-instruct": 28,
    "qwen/qwen-2.5-72b-instruct"          : 24,
}

# ════════════════════════════════════════════════════════════════════════════
log()
log("=" * 72)
log("  QAFFEINE — OpenRouter Model Benchmark Report")
log(f"  Generated : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("=" * 72)

if not OR_KEY:
    log("\n  [ERROR] OPENROUTER_API_KEY not set in .env — cannot proceed.")
    sys.exit(1)

log(f"\n  API Key   : {OR_KEY[:12]}… (loaded from .env)")
log("  Endpoint  : https://openrouter.ai/api/v1/models")

# ── Fetch models ─────────────────────────────────────────────────────────────
log("\n  Fetching model catalogue …")
try:
    r = requests.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {OR_KEY}"},
        timeout=20,
    )
    log(f"  HTTP Status : {r.status_code}")
    if r.status_code != 200:
        log(f"  [ERROR] API returned {r.status_code}: {r.text[:300]}")
        sys.exit(1)
    models = r.json()["data"]
    log(f"  Total models in catalogue : {len(models)}")
except Exception as exc:
    log(f"  [ERROR] Request failed: {exc}")
    sys.exit(1)

# ── Score every model ────────────────────────────────────────────────────────
scored: list[dict] = []

for m in models:
    mid  = m.get("id", "")
    name = m.get("name", mid)
    ctx  = m.get("context_length", 0)
    p    = m.get("pricing", {})

    try:
        prompt_cost = float(p.get("prompt",     "9999"))
        compl_cost  = float(p.get("completion", "9999"))
    except (ValueError, TypeError):
        continue

    if prompt_cost <= 0 and compl_cost <= 0:
        continue                        # skip "auto" / internal routers
    if prompt_cost > 0.1 or compl_cost > 0.5:
        pass                            # expensive models — still include

    total_cost_per_m = (prompt_cost + compl_cost) * 1_000_000   # $/1M tokens

    # ── Dimension 1: Cost score (0–50) — lower cost = higher score ──────
    if total_cost_per_m <= 0.1:
        cost_score = 50
    elif total_cost_per_m <= 0.5:
        cost_score = 45
    elif total_cost_per_m <= 1.0:
        cost_score = 38
    elif total_cost_per_m <= 2.0:
        cost_score = 30
    elif total_cost_per_m <= 5.0:
        cost_score = 20
    elif total_cost_per_m <= 10.0:
        cost_score = 12
    else:
        cost_score = 5

    # ── Dimension 2: Context / SQL accuracy proxy (0–30) ────────────────
    if ctx >= 128_000:
        ctx_score = 30
    elif ctx >= 32_000:
        ctx_score = 22
    elif ctx >= 8_000:
        ctx_score = 12
    else:
        ctx_score = 5

    # ── Dimension 3: Quality/RPM bonus (0–40) ───────────────────────────
    quality_score = QUALITY_BONUS_MODELS.get(mid, 0)

    total_score = cost_score + ctx_score + quality_score

    scored.append({
        "id"             : mid,
        "name"           : name,
        "ctx_k"          : ctx // 1_000,
        "prompt_usd_1m"  : round(prompt_cost * 1_000_000, 3),
        "compl_usd_1m"   : round(compl_cost  * 1_000_000, 3),
        "total_cost_1m"  : round(total_cost_per_m, 3),
        "cost_score"     : cost_score,
        "ctx_score"      : ctx_score,
        "quality_score"  : quality_score,
        "total_score"    : total_score,
    })

scored.sort(key=lambda x: (-x["total_score"], x["total_cost_1m"]))

# ── Print full rankings ──────────────────────────────────────────────────────
log()
log("─" * 72)
log(f"  {'RANK':<5} {'MODEL ID':<44} {'CTX':>6}  {'$/1M':>7}  {'SCORE':>5}")
log("─" * 72)

for rank, m in enumerate(scored[:30], 1):
    ctx_disp  = f"{m['ctx_k']}k"
    cost_disp = f"${m['total_cost_1m']:.3f}"
    log(f"  {rank:<5} {m['id']:<44} {ctx_disp:>6}  {cost_disp:>7}  {m['total_score']:>5}")

# ── TOP 3 RECOMMENDED ────────────────────────────────────────────────────────
log()
log("=" * 72)
log("  TOP 3 RECOMMENDED  —  QAFFEINE Failover LLM Stack")
log("=" * 72)

TOP3_LABELS = [
    ("🥇 PRIMARY   (Cost-to-Performance)",
     "Best reasoning + cheapest viable model. Handles disruptor analysis well."),
    ("🥈 SECONDARY (SQL Accuracy / Long Context)",
     "Large context window — ideal for multi-headline analysis & context."),
    ("🥉 TERTIARY  (Quota Safety Net)",
     "Known-reliable fallback; separate provider from above."),
]

top3 = scored[:3]

for i, m in enumerate(top3):
    label, rationale = TOP3_LABELS[i]
    log()
    log(f"  {label}")
    log(f"  Model    : {m['id']}")
    log(f"  Name     : {m['name']}")
    log(f"  Context  : {m['ctx_k']}k tokens")
    log(f"  Cost     : ${m['prompt_usd_1m']:.3f}/1M prompt  |  ${m['compl_usd_1m']:.3f}/1M completion")
    log(f"  Score    : {m['total_score']} / 120")
    log(f"  Use-case : {rationale}")

# Also highlight the specific models the LLMManager will use
log()
log("─" * 72)
log("  LLMManager Failover Chain (hardcoded for QAFFEINE):")
log("  1. Gemini 2.0 Flash          — Primary Engine (Google AI Studio)")
log("  2. meta-llama/llama-3.3-70b-instruct — OR Backup 1 (cost-optimal)")
log("  3. mistralai/mistral-small-2603      — OR Backup 2 (long context)")
log("  4. deepseek/deepseek-chat            — OR Backup 3 (last resort)")
log("─" * 72)

# ── Save ─────────────────────────────────────────────────────────────────────
log()
log(f"  Report saved → {OUT_PATH}")

OUT_PATH.write_text("\n".join(LINES), encoding="utf-8")
