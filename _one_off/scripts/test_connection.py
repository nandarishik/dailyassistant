"""
QAFFEINE API Connection Tester
================================
Verifies that WeatherAPI and Gemini respond correctly.
Writes results to database/test_connection_log.txt.

Run from QAFFEINE_Prototype/:
    python scripts/test_connection.py
"""

import os, sys, json, datetime, requests
from pathlib import Path
from dotenv import load_dotenv
from google import genai

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── Paths & env ──────────────────────────────────────────────────────────────
BASE     = Path(__file__).resolve().parent.parent
ENV_PATH = BASE.parent / ".env"
LOG_PATH = BASE / "database" / "test_connection_log.txt"

load_dotenv(ENV_PATH, override=True)

WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY", "").strip()
GEMINI_KEY     = os.getenv("GEMINI_API_KEY", "").strip()

LINES: list[str] = []

def log(msg: str = "") -> None:
    print(msg)
    LINES.append(str(msg))

# ════════════════════════════════════════════════════════════════════════════
log()
log("=" * 65)
log("  QAFFEINE API Connection Test")
log(f"  Run : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("=" * 65)

# ── Test 1: WeatherAPI ───────────────────────────────────────────────────────
log()
log("TEST 1 — WeatherAPI  /v1/history.json")
log("-" * 65)

weatherapi_ok   = False
weatherapi_data = {}

if not WEATHERAPI_KEY:
    log("  STATUS : ✗ SKIP — WEATHERAPI_KEY not set in .env")
else:
    test_date = datetime.date(2026, 3, 16)      # earlier this week
    url = "https://api.weatherapi.com/v1/history.json"
    params = {
        "key": WEATHERAPI_KEY,
        "q"  : "Hyderabad",
        "dt" : test_date.strftime("%Y-%m-%d"),
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        log(f"  URL    : {r.url[:100]}")
        log(f"  HTTP   : {r.status_code}")

        if r.status_code == 200:
            weatherapi_ok = True
            data = r.json()
            day  = data["forecast"]["forecastday"][0]["day"]
            weatherapi_data = {
                "avgtemp_c"     : day.get("avgtemp_c"),
                "totalprecip_mm": day.get("totalprecip_mm"),
                "condition"     : day.get("condition", {}).get("text"),
                "maxtemp_c"     : day.get("maxtemp_c"),
                "mintemp_c"     : day.get("mintemp_c"),
            }
            log(f"  STATUS : ✓ 200 OK")
            log(f"  Date   : {test_date}  (Hyderabad)")
            log(f"  Avg °C : {weatherapi_data['avgtemp_c']}")
            log(f"  Precip : {weatherapi_data['totalprecip_mm']} mm")
            log(f"  Cond   : {weatherapi_data['condition']}")
            log(f"  Max °C : {weatherapi_data['maxtemp_c']}")
            log(f"  Min °C : {weatherapi_data['mintemp_c']}")
        else:
            try:
                err = r.json().get("error", {})
                log(f"  STATUS : ✗ HTTP {r.status_code}")
                log(f"  Error  : code={err.get('code')}  msg={err.get('message', '')}")
            except Exception:
                log(f"  STATUS : ✗ HTTP {r.status_code}  body={r.text[:200]}")

    except Exception as exc:
        log(f"  STATUS : ✗ Exception — {exc}")

# ── Test 2: Gemini ───────────────────────────────────────────────────────────
log()
log("TEST 2 — Gemini  /generate_content")
log("-" * 65)

gemini_ok    = False
gemini_model = "none"
gemini_text  = ""

MODELS_TO_TRY = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-001",
]

if not GEMINI_KEY:
    log("  STATUS : ✗ SKIP — GEMINI_API_KEY not set in .env")
else:
    client = genai.Client(api_key=GEMINI_KEY)
    probe  = (
        "Respond with exactly one sentence: confirm you are Gemini and state "
        "today's date as 18 March 2026."
    )

    for model_name in MODELS_TO_TRY:
        log(f"  Trying model: {model_name} …")
        try:
            resp = client.models.generate_content(model=model_name, contents=probe)
            gemini_text  = resp.text.strip()
            gemini_model = model_name
            gemini_ok    = True
            log(f"  STATUS : ✓ 200 OK  (model: {model_name})")
            log(f"  Reply  : {gemini_text[:160]}")
            break
        except Exception as exc:
            err_str = str(exc)
            if any(k in err_str for k in ("429", "RESOURCE_EXHAUSTED", "quota")):
                log(f"  STATUS : ⚠ Quota hit on {model_name} — trying next …")
                continue
            log(f"  STATUS : ✗ Error on {model_name} — {err_str[:200]}")
            break

    if not gemini_ok and gemini_model == "none":
        log("  STATUS : ✗ All models quota-exhausted. Re-run after UTC midnight.")

# ── Summary ──────────────────────────────────────────────────────────────────
log()
log("=" * 65)
log("  CONNECTION TEST SUMMARY")
log("=" * 65)
log(f"  WeatherAPI  : {'✓ PASS' if weatherapi_ok else '✗ FAIL'}")
if weatherapi_ok:
    log(f"    Response  : avgtemp_c={weatherapi_data.get('avgtemp_c')} °C, "
        f"precip={weatherapi_data.get('totalprecip_mm')} mm, "
        f"cond={weatherapi_data.get('condition')!r}")
log(f"  Gemini      : {'✓ PASS (model: ' + gemini_model + ')' if gemini_ok else '✗ FAIL'}")
if gemini_ok:
    log(f"    Response  : {gemini_text[:120]}")
log()

overall = "ALL TESTS PASSED" if (weatherapi_ok and gemini_ok) else "SOME TESTS FAILED (see above)"
log(f"  Overall     : {overall}")
log()

# ── Write log ────────────────────────────────────────────────────────────────
LOG_PATH.write_text("\n".join(LINES), encoding="utf-8")
log(f"  Log saved → {LOG_PATH}")
