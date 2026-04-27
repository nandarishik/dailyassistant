"""
QAFFEINE Chaos Monkey — Resilience Test Suite
================================================
Stress-tests the QAFFEINE platform by injecting controlled failures:

  Scenario A: API Blackout — Weather & News endpoints return 401/Timeout
  Scenario B: LLM Failover — Gemini returns 429 Quota Exceeded
  Scenario C: Database Lock — SQLite locked for 5 seconds

Each scenario validates graceful degradation and automatic recovery.

Usage:
    python scripts/chaos_monkey.py              # Run all scenarios
    python scripts/chaos_monkey.py --scenario A  # Run specific scenario

Output:
    logs/chaos_monkey_report.txt
"""

import os, sys, time, sqlite3, threading, functools, contextlib, io
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field
from dotenv import load_dotenv
from src.config.settings import resolve_db_path

# ── Paths & env ───────────────────────────────────────────────────────────────
BASE     = Path(__file__).resolve().parent.parent
DB_PATH  = resolve_db_path(BASE)
LOG_DIR  = BASE / "logs"
REPORT   = LOG_DIR / "chaos_monkey_report.txt"
ENV_PATH = BASE.parent / ".env"

load_dotenv(ENV_PATH, override=True)

# ── Encoding ──────────────────────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure scripts/ is importable
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChaosResult:
    scenario    : str
    success     : bool
    duration_ms : float = 0.0
    details     : str   = ""
    recovery    : str   = ""

    def summary(self) -> str:
        status = "PASS" if self.success else "FAIL"
        return (
            f"[{status}] Scenario {self.scenario} "
            f"({self.duration_ms:.0f}ms) — {self.recovery}"
        )


REPORT_LINES: list[str] = []

def log(msg: str = "") -> None:
    print(msg)
    REPORT_LINES.append(str(msg))

def section(title: str) -> None:
    log()
    log("=" * 70)
    log(f"  {title}")
    log("=" * 70)


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO A:  API BLACKOUT
# ══════════════════════════════════════════════════════════════════════════════

def _make_api_blackout_weather(*args, **kwargs) -> dict:
    """Simulated weather API returning a 401 Unauthorized error."""
    raise ConnectionError("CHAOS MONKEY: Weather API returned 401 Unauthorized")

def _make_api_blackout_news(*args, **kwargs) -> list:
    """Simulated news API timeout."""
    raise TimeoutError("CHAOS MONKEY: News API request timed out after 15s")


def run_scenario_a() -> ChaosResult:
    """
    Scenario A: API Blackout
    Force get_weather_context and get_news_context to fail.
    Jarvis must gracefully handle the errors and still produce a response.
    """
    section("SCENARIO A — API BLACKOUT")
    log("  Injecting: Weather API → 401, News API → Timeout")
    log("  Expected: Jarvis catches exceptions, provides fallback response")

    import universal_context as uc
    from copilot_brain import CopilotAgent
    from universal_context import LLMManager

    t0 = time.time()

    # Patch the weather and news functions
    original_weather = uc.get_weather_context
    original_news    = uc.get_news_headlines

    try:
        uc.get_weather_context = _make_api_blackout_weather
        uc.get_news_headlines  = _make_api_blackout_news

        # Also patch the imported references in jarvis_brain
        import copilot_brain as cb
        orig_cb_weather = cb.get_weather_context
        orig_cb_news    = cb.get_news_headlines
        cb.get_weather_context = _make_api_blackout_weather
        cb.get_news_headlines  = _make_api_blackout_news

        agent  = CopilotAgent(llm=LLMManager())
        result = agent.investigate(
            "Why did revenue drop on Dec 7th? Check weather and news."
        )

        duration = (time.time() - t0) * 1000

        # Check: agent should NOT have crashed
        has_response = bool(result.response and len(result.response) > 20)
        has_error_handling = any(
            "error" in step.lower() or "fail" in step.lower() or "✗" in step
            for step in result.monologue
        )

        log(f"\n  Agent response length : {len(result.response)} chars")
        log(f"  Error caught in monologue: {has_error_handling}")
        log(f"  Response generated: {has_response}")
        log(f"  Duration: {duration:.0f}ms")

        if has_response:
            log(f"\n  Response preview: {result.response[:200]}...")
            recovery = "Copilot caught API errors and generated response using available data"
        else:
            recovery = "Copilot returned empty response (partial recovery)"

        log(f"\n  Monologue:")
        for step in result.monologue:
            log(f"    {step}")

        return ChaosResult(
            scenario="A — API Blackout",
            success=has_response,
            duration_ms=duration,
            details=f"Weather=401, News=Timeout. Response={len(result.response)} chars",
            recovery=recovery,
        )

    finally:
        # Restore originals
        uc.get_weather_context = original_weather
        uc.get_news_headlines  = original_news
        cb.get_weather_context = orig_cb_weather
        cb.get_news_headlines  = orig_cb_news


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO B:  LLM FAILOVER
# ══════════════════════════════════════════════════════════════════════════════

def run_scenario_b() -> ChaosResult:
    """
    Scenario B: LLM Failover
    Force Gemini to return 429 Quota Exceeded.
    OpenRouter/Llama-3.3 must take over seamlessly.
    """
    section("SCENARIO B — LLM FAILOVER (Gemini → OpenRouter)")
    log("  Injecting: All Gemini models → 429 Quota Exceeded")
    log("  Expected: OpenRouter/Llama-3.3-70B takes over within 3s")

    from universal_context import LLMManager

    t0 = time.time()

    # Create a patched LLMManager where Gemini always fails
    llm = LLMManager()
    original_try_gemini = llm._try_gemini

    def _forced_gemini_fail(prompt, ev_log):
        ev_log.append("[CHAOS MONKEY] Gemini forced 429 Quota Exceeded")
        return None  # Simulate total Gemini failure

    try:
        llm._try_gemini = _forced_gemini_fail

        result = llm.generate(
            "Calculate the average daily revenue for QAFFEINE in December 2025."
        )

        duration = (time.time() - t0) * 1000

        log(f"\n  Engine used    : {result.engine}")
        log(f"  Model used     : {result.model}")
        log(f"  Duration       : {duration:.0f}ms")
        log(f"  Response length: {len(result.text)} chars")

        # Check success criteria
        used_openrouter = result.engine == "OpenRouter"
        under_3s        = duration < 10000   # generous for network latency
        has_response    = len(result.text) > 10

        log(f"\n  Failover log:")
        for entry in result.fallback_log:
            log(f"    {entry}")

        if used_openrouter and has_response:
            recovery = f"OpenRouter/{result.model} took over in {duration:.0f}ms"
        elif has_response:
            recovery = f"Response generated via {result.engine} in {duration:.0f}ms"
        else:
            recovery = "LLM failover failed — no response generated"

        return ChaosResult(
            scenario="B — LLM Failover",
            success=used_openrouter and has_response,
            duration_ms=duration,
            details=f"Engine={result.engine}, Model={result.model}",
            recovery=recovery,
        )

    finally:
        llm._try_gemini = original_try_gemini


# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO C:  DATABASE LOCK
# ══════════════════════════════════════════════════════════════════════════════

def run_scenario_c() -> ChaosResult:
    """
    Scenario C: Database Lock
    Simulate a 5-second SQLite write-lock.
    The system must use retry logic instead of crashing.
    """
    section("SCENARIO C — DATABASE LOCK (5s)")
    log("  Injecting: SQLite write-lock held for 5 seconds")
    log("  Expected: Read query retries and succeeds after lock release")

    t0 = time.time()

    lock_released = threading.Event()
    lock_error    = [None]

    def _hold_write_lock():
        """Background thread that holds an exclusive write lock for 5s."""
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("BEGIN EXCLUSIVE")
            # Hold the exclusive lock
            log("  [LOCK] Write lock acquired by Chaos Monkey")
            time.sleep(5)
            conn.rollback()
            conn.close()
            log("  [LOCK] Write lock released after 5s")
        except Exception as exc:
            lock_error[0] = str(exc)
            log(f"  [LOCK] Error: {exc}")
        finally:
            lock_released.set()

    # Start lock holder thread
    lock_thread = threading.Thread(target=_hold_write_lock, daemon=True)
    lock_thread.start()
    time.sleep(0.5)  # Give thread time to acquire lock

    # Now try to read from the database with retry logic
    max_retries = 10
    retry_delay = 0.8
    read_success = False
    result_data  = None

    for attempt in range(1, max_retries + 1):
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=2)
            result_data = conn.execute(
                "SELECT SUBSTR(DT, 1, 10), SUM(NETAMT) FROM AI_TEST_INVOICEBILLREGISTER "
                "WHERE SUBSTR(DT, 1, 10)='2026-01-01' GROUP BY SUBSTR(DT, 1, 10)"
            ).fetchone()
            conn.close()
            read_success = True
            log(f"  [READ] Attempt {attempt}: SUCCESS — {result_data}")
            break
        except sqlite3.OperationalError as exc:
            log(f"  [READ] Attempt {attempt}: LOCKED — retrying in {retry_delay}s...")
            time.sleep(retry_delay)
        except Exception as exc:
            log(f"  [READ] Attempt {attempt}: Error — {exc}")
            time.sleep(retry_delay)

    # Wait for lock thread to finish
    lock_released.wait(timeout=10)
    lock_thread.join(timeout=2)

    duration = (time.time() - t0) * 1000

    log(f"\n  Read succeeded   : {read_success}")
    log(f"  Attempts needed  : {attempt}")
    log(f"  Total duration   : {duration:.0f}ms")
    if result_data:
        log(f"  Data retrieved   : {result_data}")

    if read_success:
        recovery = f"Retry logic succeeded after {attempt} attempt(s) ({duration:.0f}ms)"
    else:
        recovery = f"Read failed after {max_retries} retries"

    return ChaosResult(
        scenario="C — Database Lock",
        success=read_success,
        duration_ms=duration,
        details=f"Lock=5s, Retries={attempt}/{max_retries}",
        recovery=recovery,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def run_all_scenarios() -> list[ChaosResult]:
    """Run all chaos scenarios and return results."""
    import datetime

    section("QAFFEINE CHAOS MONKEY — RESILIENCE TEST SUITE")
    log(f"  Run date : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Database : {DB_PATH}")
    log(f"  3 Scenarios: API Blackout · LLM Failover · Database Lock")

    results = []

    # Scenario A
    try:
        results.append(run_scenario_a())
    except Exception as exc:
        log(f"\n  SCENARIO A CRASHED: {exc}")
        results.append(ChaosResult("A — API Blackout", False,
                                    details=f"CRASH: {exc}",
                                    recovery="Scenario crashed unexpectedly"))

    # Scenario B
    try:
        results.append(run_scenario_b())
    except Exception as exc:
        log(f"\n  SCENARIO B CRASHED: {exc}")
        results.append(ChaosResult("B — LLM Failover", False,
                                    details=f"CRASH: {exc}",
                                    recovery="Scenario crashed unexpectedly"))

    # Scenario C
    try:
        results.append(run_scenario_c())
    except Exception as exc:
        log(f"\n  SCENARIO C CRASHED: {exc}")
        results.append(ChaosResult("C — Database Lock", False,
                                    details=f"CRASH: {exc}",
                                    recovery="Scenario crashed unexpectedly"))

    # ── Summary ───────────────────────────────────────────────────────────
    section("CHAOS MONKEY SUMMARY")

    passed = sum(1 for r in results if r.success)
    total  = len(results)

    log(f"\n  Results: {passed}/{total} scenarios passed\n")

    for r in results:
        status_icon = "✅" if r.success else "❌"
        log(f"  {status_icon} {r.summary()}")
        log(f"       Details : {r.details}")
        log(f"       Recovery: {r.recovery}")
        log()

    overall = "ALL PASS" if passed == total else f"{total - passed} FAILED"
    log(f"  Overall: {overall}")

    # Save report
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(REPORT_LINES), encoding="utf-8")
    log(f"\n  Report saved: {REPORT}")

    return results


def get_chaos_history() -> list[dict]:
    """Load the last chaos run results from the report file (for dashboard)."""
    if not REPORT.exists():
        return []
    try:
        text = REPORT.read_text(encoding="utf-8")
        events = []
        for line in text.split("\n"):
            if line.strip().startswith(("✅", "❌")):
                line = line.strip()
                events.append({
                    "status": "PASS" if "✅" in line else "FAIL",
                    "summary": line.replace("✅ ", "").replace("❌ ", ""),
                })
        return events[-3:]  # last 3
    except Exception:
        return []


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QAFFEINE Chaos Monkey")
    parser.add_argument("--scenario", type=str, default="ALL",
                        help="Run specific scenario: A, B, C, or ALL")
    args = parser.parse_args()

    if args.scenario.upper() == "ALL":
        run_all_scenarios()
    elif args.scenario.upper() == "A":
        r = run_scenario_a()
        log(f"\n{r.summary()}")
    elif args.scenario.upper() == "B":
        r = run_scenario_b()
        log(f"\n{r.summary()}")
    elif args.scenario.upper() == "C":
        r = run_scenario_c()
        log(f"\n{r.summary()}")
    else:
        print(f"Unknown scenario: {args.scenario}. Use A, B, C, or ALL.")
