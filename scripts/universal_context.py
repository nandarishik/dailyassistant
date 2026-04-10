"""
QAFFEINE Universal Context Engine  v3
=======================================
Programmatically identifies external factors (Weather, Holidays, Market News)
that influence sales performance for the Hyderabad / Telangana region.

Usage:
    python scripts/universal_context.py

Outputs:
    - Upserts rows into  database/context_intelligence  table in sales.db
    - Writes             database/context_engine_log.txt

Environment variables (.env in project root):
    WEATHERAPI_KEY     — WeatherAPI.com key      (history.json endpoint)
    NEWS_API_KEY       — NewsAPI.org key          (optional; RSS fallback if blank)
    GEMINI_API_KEY     — Google Gemini key        (Primary LLM engine)
    OPENROUTER_API_KEY — OpenRouter key            (Backup LLM engine — failover)

All modules degrade gracefully: if a key is missing / the API returns an
error the engine logs a [WARN] / [SKIP] notice and continues — the UPSERT
still fires with whatever data IS available.
"""

import os, sys, sqlite3, json, textwrap, datetime, requests, feedparser
import holidays as holidays_lib
from google import genai
from pathlib import Path
from dotenv import load_dotenv

# ── Encoding ------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── Paths --------------------------------------------------------------------
BASE     = Path(__file__).resolve().parent.parent       # QAFFEINE_Prototype/
DB_PATH  = BASE / "database" / "sales.db"
LOG_PATH = BASE / "database" / "context_engine_log.txt"
ENV_PATH = BASE.parent / ".env"                         # BrainPowerInternship/.env

load_dotenv(ENV_PATH, override=True)

# ── API Keys -----------------------------------------------------------------
WEATHERAPI_KEY  = os.getenv("WEATHERAPI_KEY",     "").strip()
NEWS_API_KEY    = os.getenv("NEWS_API_KEY",        "").strip()
GEMINI_KEY      = os.getenv("GEMINI_API_KEY",      "").strip()
OPENROUTER_KEY  = os.getenv("OPENROUTER_API_KEY",  "").strip()

# ── Constants ----------------------------------------------------------------
CITY        = "Hyderabad"
COUNTRY     = "IN"
SUBDIVISION = "TS"          # Telangana state

# ── Logging harness ----------------------------------------------------------
LOG_LINES: list[str] = []

def log(msg: str = "") -> None:
    """Print to console and buffer for the log file."""
    print(msg)
    LOG_LINES.append(str(msg))

def section(title: str) -> None:
    log()
    log("=" * 70)
    log(f"  {title}")
    log("=" * 70)


# ═══════════════════════════════════════════════════════════════════════════
# ┌─────────────────────────────────────────────────────────────────────────┐
# │  LLMManager — Dual-Engine Wrapper with Automatic Failover               │
# │                                                                         │
# │  Priority chain:                                                         │
# │    1. Gemini 2.0 Flash  (Google AI Studio)           — Primary          │
# │    2. meta-llama/llama-3.3-70b-instruct (OpenRouter) — Backup 1         │
# │    3. mistralai/mistral-small-2603      (OpenRouter) — Backup 2         │
# │    4. deepseek/deepseek-chat            (OpenRouter) — Backup 3         │
# │                                                                         │
# │  Triggers failover on: 429, 500, RESOURCE_EXHAUSTED, quota              │
# └─────────────────────────────────────────────────────────────────────────┘
# ═══════════════════════════════════════════════════════════════════════════

class LLMManager:
    """
    Dual-Engine LLM wrapper for the QAFFEINE Intelligence Layer.

    Tries Gemini models first (Primary Engine).
    On any 429 / 500 / quota error it automatically falls back to
    OpenRouter-hosted models (Backup Engine), logging every decision.

    Usage:
        mgr    = LLMManager()
        result = mgr.generate(prompt)
        # result.text         — response string
        # result.engine       — "Gemini" | "OpenRouter"
        # result.model        — exact model name used
        # result.fallback_log — list of [INFO / WARNING] messages
    """

    # ── Gemini model rotation (tried in order) ──────────────────────────────
    GEMINI_MODELS = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-001",
    ]

    # ── OpenRouter fallback chain (benchmarked 2026-03-18) ─────────────────
    # Ranked by: cost-to-performance × context window × reasoning quality
    OPENROUTER_MODELS = [
        "meta-llama/llama-3.3-70b-instruct",   # #1: cost-optimal, strong reasoning
        "mistralai/mistral-small-2603",          # #2: 262k ctx, long-form analysis
        "deepseek/deepseek-chat",                # #3: 163k ctx, last-resort safety net
    ]

    OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_HDRS = {
        "HTTP-Referer" : "https://qaffeine.ai",
        "X-Title"      : "QAFFEINE Intelligence Layer",
        "Content-Type" : "application/json",
    }

    # Error signals that trigger failover
    FAILOVER_SIGNALS = ("429", "500", "RESOURCE_EXHAUSTED", "quota", "rate_limit",
                        "overloaded", "service_unavailable")

    class Result:
        """Structured return from LLMManager.generate()."""
        def __init__(self, text: str, engine: str, model: str,
                     fallback_log: list[str]):
            self.text         = text
            self.engine       = engine
            self.model        = model
            self.fallback_log = fallback_log

        def log_summary(self) -> str:
            """Single-line log tag for context_engine_log.txt."""
            tag = "[INFO]" if self.engine == "Gemini" else "[WARNING] Quota Hit —"
            src = f"Gemini/{self.model}" if self.engine == "Gemini" \
                  else f"OpenRouter/{self.model}"
            return f"{tag} Source: {src}"

    def __init__(self):
        self._gemini_client = None
        if GEMINI_KEY:
            try:
                self._gemini_client = genai.Client(api_key=GEMINI_KEY)
            except Exception as exc:
                log(f"  [WARN] LLMManager: Gemini client init failed: {exc}")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _is_failover_error(self, err_str: str) -> bool:
        return any(sig in err_str for sig in self.FAILOVER_SIGNALS)

    def _try_gemini(self, prompt: str, ev_log: list[str]) -> tuple[str, str] | None:
        """
        Attempt all Gemini models in order.
        Returns (text, model_name) on success, None if all quota-exhausted.
        """
        if not self._gemini_client:
            ev_log.append("[INFO] Gemini client unavailable — skipping Primary Engine.")
            return None

        for model_name in self.GEMINI_MODELS:
            try:
                resp = self._gemini_client.models.generate_content(
                    model=model_name, contents=prompt
                )
                ev_log.append(f"[INFO] Source: Gemini/{model_name} ✓")
                return resp.text.strip(), model_name
            except Exception as exc:
                err_str = str(exc)
                if self._is_failover_error(err_str):
                    ev_log.append(
                        f"[WARNING] Quota Hit — Gemini/{model_name} returned "
                        f"{'429' if '429' in err_str else '500/quota'}. "
                        f"Trying next Gemini model …"
                    )
                    continue
                # Hard error (401, bad request, etc.) — log but still failover
                ev_log.append(
                    f"[WARNING] Gemini/{model_name} hard error: {err_str[:120]}"
                )
                return None

        ev_log.append("[WARNING] Quota Hit — All Gemini models exhausted. "
                      "Falling back to OpenRouter …")
        return None

    def _try_openrouter(self, prompt: str, ev_log: list[str]) -> tuple[str, str] | None:
        """
        Attempt all OpenRouter fallback models in order.
        Returns (text, model_name) on success, None if all failed.
        """
        if not OPENROUTER_KEY:
            ev_log.append("[WARNING] OPENROUTER_API_KEY not set — backup engine unavailable.")
            return None

        headers = {
            **self.OPENROUTER_HDRS,
            "Authorization": f"Bearer {OPENROUTER_KEY}",
        }

        for model_name in self.OPENROUTER_MODELS:
            payload = {
                "model"    : model_name,
                "messages" : [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.3,
            }
            try:
                resp = requests.post(
                    self.OPENROUTER_BASE, headers=headers,
                    json=payload, timeout=30
                )
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"].strip()
                    ev_log.append(
                        f"[INFO] Falling back to OpenRouter/{model_name} ✓ "
                        f"(HTTP 200)"
                    )
                    return text, model_name

                # Soft retry on 429/500
                err_body = resp.text[:200]
                if resp.status_code in (429, 500, 503):
                    ev_log.append(
                        f"[WARNING] OpenRouter/{model_name} HTTP {resp.status_code} "
                        f"— trying next backup …"
                    )
                    continue

                ev_log.append(
                    f"[WARNING] OpenRouter/{model_name} HTTP {resp.status_code}: "
                    f"{err_body}"
                )
                continue

            except requests.exceptions.Timeout:
                ev_log.append(
                    f"[WARNING] OpenRouter/{model_name} timed out — trying next …"
                )
                continue
            except Exception as exc:
                ev_log.append(
                    f"[WARNING] OpenRouter/{model_name} exception: {str(exc)[:120]}"
                )
                continue

        ev_log.append("[ERROR] All OpenRouter fallback models failed.")
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, prompt: str) -> "LLMManager.Result":
        """
        Generate a response using the dual-engine failover strategy.

        Returns an LLMManager.Result with .text, .engine, .model,
        and .fallback_log for structured logging.
        """
        ev_log: list[str] = []

        # ── Step 1: Try Primary Engine (Gemini) ──────────────────────────
        gemini_result = self._try_gemini(prompt, ev_log)
        if gemini_result:
            text, model = gemini_result
            return self.Result(text, "Gemini", model, ev_log)

        # ── Step 2: Failover to Backup Engine (OpenRouter) ───────────────
        ev_log.append("[WARNING] Quota Hit — Falling back to OpenRouter backup engine.")
        or_result = self._try_openrouter(prompt, ev_log)
        if or_result:
            text, model = or_result
            return self.Result(text, "OpenRouter", model, ev_log)

        # ── Step 3: Total failure — return structured error ───────────────
        ev_log.append("[ERROR] Both Gemini and OpenRouter engines failed.")
        return self.Result(
            text         = "LLM unavailable: both Gemini and OpenRouter engines failed.",
            engine       = "none",
            model        = "none",
            fallback_log = ev_log,
        )


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 1 — REGIONAL CALENDAR  (python-holidays, Telangana/TS)
# ═══════════════════════════════════════════════════════════════════════════

def get_holiday_info(date_obj: datetime.date) -> dict:
    """
    Check if a given date is a public holiday in Telangana, India.
    Returns dict with is_holiday, holiday_name, holiday_type.
    """
    national_cal = holidays_lib.country_holidays(COUNTRY, years=date_obj.year)
    state_cal    = holidays_lib.country_holidays(
        COUNTRY, subdiv=SUBDIVISION, years=date_obj.year
    )
    national_name = national_cal.get(date_obj)
    state_name    = state_cal.get(date_obj)

    if national_name:
        return {"is_holiday": True,  "holiday_name": national_name, "holiday_type": "National"}
    if state_name:
        return {"is_holiday": True,  "holiday_name": state_name,    "holiday_type": "State"}
    return     {"is_holiday": False, "holiday_name": None,           "holiday_type": None}


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 2 — WEATHER  (WeatherAPI.com  /v1/history.json)
# ═══════════════════════════════════════════════════════════════════════════

WEATHERAPI_BASE          = "https://api.weatherapi.com/v1"
_WEATHERAPI_NO_HIST_CODES = {1007, 1008, 9000, 9001, 9002, 9003}


def get_weather_context(date_obj: datetime.date) -> dict:
    """
    Fetch historical weather for Hyderabad via WeatherAPI /v1/history.json.
    Degrades gracefully on error — always returns a complete dict.
    """
    _stub = {
        "temp_max_c"       : None,
        "precipitation_mm" : None,
        "weather_condition": "N/A (no API key)",
        "source"           : "none",
        "api_error_code"   : None,
        "api_error_msg"    : None,
    }
    if not WEATHERAPI_KEY:
        log("  [SKIP] WEATHERAPI_KEY not set — weather unavailable.")
        return _stub

    url    = f"{WEATHERAPI_BASE}/history.json"
    params = {"key": WEATHERAPI_KEY, "q": CITY, "dt": date_obj.strftime("%Y-%m-%d")}

    try:
        resp = requests.get(url, params=params, timeout=15)
        log(f"  [WeatherAPI] HTTP {resp.status_code}")

        if resp.status_code != 200:
            try:
                err   = resp.json().get("error", {})
                ecode = err.get("code")
                emsg  = err.get("message", resp.text[:200])
            except Exception:
                ecode, emsg = None, resp.text[:200]
            log(f"  [WARN] WeatherAPI error — code:{ecode}  {emsg}")
            return {**_stub,
                    "weather_condition": f"Unavailable (API code {ecode})",
                    "source"           : "WeatherAPI",
                    "api_error_code"   : ecode,
                    "api_error_msg"    : emsg}

        day = resp.json()["forecast"]["forecastday"][0]["day"]
        return {
            "temp_max_c"       : round(float(day["avgtemp_c"]),     1),
            "precipitation_mm" : round(float(day["totalprecip_mm"]), 2),
            "weather_condition": str(day["condition"]["text"]),
            "source"           : "WeatherAPI",
            "api_error_code"   : None,
            "api_error_msg"    : None,
        }
    except requests.exceptions.Timeout:
        log("  [WARN] WeatherAPI timed out.")
        return {**_stub, "weather_condition": "Unavailable (timeout)", "source": "WeatherAPI"}
    except Exception as exc:
        log(f"  [WARN] WeatherAPI exception: {exc}")
        return {**_stub, "weather_condition": "Unavailable (exception)", "source": "WeatherAPI"}


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 3 — DYNAMIC MARKET LISTENER  (NewsAPI + RSS feeds)
# ═══════════════════════════════════════════════════════════════════════════

_RSS_FEEDS = [
    "https://timesofindia.indiatimes.com/rss/754048.cms",
    "https://www.thehindu.com/news/cities/Hyderabad/feeder/default.rss",
    "https://news.google.com/rss/search?q=Hyderabad+Business&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Telangana+Infrastructure&hl=en-IN&gl=IN&ceid=IN:en",
]


def _fetch_newsapi(query: str, date_obj: datetime.date) -> list[str]:
    from_str = date_obj.strftime("%Y-%m-%d")
    to_str   = (date_obj + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "from": from_str, "to": to_str,
                    "language": "en", "sortBy": "relevancy",
                    "pageSize": 10, "apiKey": NEWS_API_KEY},
            timeout=12,
        )
        if r.status_code == 200:
            return [
                f"{a.get('title','').strip()} — {a.get('source',{}).get('name','')}"
                for a in r.json().get("articles", []) if a.get("title")
            ]
        log(f"  [WARN] NewsAPI HTTP {r.status_code}")
    except Exception as exc:
        log(f"  [WARN] NewsAPI: {exc}")
    return []


def _fetch_rss_headlines(max_per_feed: int = 5) -> list[str]:
    headlines: list[str] = []
    for feed_url in _RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_per_feed]:
                t = entry.get("title", "").strip()
                if t:
                    headlines.append(t)
        except Exception as exc:
            log(f"  [WARN] RSS ({feed_url[:50]}…): {exc}")
    return headlines[:10]


def get_news_headlines(date_obj: datetime.date) -> list[str]:
    headlines: list[str] = []
    if NEWS_API_KEY:
        log("  [NEWS] Fetching from NewsAPI.org …")
        for q in ["Hyderabad Business", "Telangana Infrastructure"]:
            batch = _fetch_newsapi(q, date_obj)
            headlines.extend(batch)
            log(f"    '{q}' → {len(batch)} headlines")
    else:
        log("  [NEWS] NEWS_API_KEY not set — using RSS fallback …")

    if not headlines:
        log("  [NEWS] Falling back to RSS feeds …")
        headlines = _fetch_rss_headlines()
        log(f"  [NEWS] RSS yielded {len(headlines)} headlines")

    seen, unique = set(), []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique[:10]


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 4 — LLM ANALYSIS  (uses LLMManager for failover)
# ═══════════════════════════════════════════════════════════════════════════

def build_disruptor_prompt(
    date_obj:      datetime.date,
    headlines:     list[str],
    daily_revenue: float | None,
    avg_revenue:   float | None,
) -> str:
    """Build the operational-disruptor prompt passed to LLMManager."""
    anomaly_ctx = ""
    if daily_revenue is not None and avg_revenue and avg_revenue > 0:
        pct   = ((daily_revenue - avg_revenue) / avg_revenue) * 100
        dirn  = "ABOVE" if pct > 0 else "BELOW"
        anomaly_ctx = (
            f"\nSales context: Revenue on {date_obj} was ₹{daily_revenue:,.0f}, "
            f"which is {abs(pct):.1f}% {dirn} the weekly average of ₹{avg_revenue:,.0f}."
        )

    headlines_block = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(headlines))

    return textwrap.dedent(f"""
    You are an operations analyst for QAFFEINE, a premium coffee chain with 6 outlets
    across Hyderabad, India. Identify external "operational disruptors" — events or
    conditions that could meaningfully increase OR reduce footfall and revenue.
    {anomaly_ctx}
    News headlines from {date_obj.strftime('%d %b %Y')} (Hyderabad / Telangana):

    {headlines_block}

    Task:
    1. Identify headlines that could act as an operational disruptor for a coffee-chain
       (road closures, strikes, infrastructure outages, festivals, large events,
       supply chain issues, weather events, political shutdowns, IT corridor events).
    2. For each disruptor: [Disruptor Type] — [Expected Impact] — [Headline #N].
    3. If none: "No significant operational disruptors detected."
    4. Respond in under 200 words. Do not repeat headlines verbatim.

    RESPONSE:
    """).strip()


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 5 — DATABASE SYNC  (context_intelligence table)
# ═══════════════════════════════════════════════════════════════════════════

DDL = """
CREATE TABLE IF NOT EXISTS context_intelligence (
    date               TEXT PRIMARY KEY,
    is_holiday         INTEGER NOT NULL DEFAULT 0,
    holiday_name       TEXT,
    holiday_type       TEXT,
    temp_max_c         REAL,
    precipitation_mm   REAL,
    weather_condition  TEXT,
    weather_source     TEXT,
    weather_api_error  TEXT,
    news_headlines     TEXT,
    news_disruptors    TEXT,
    llm_engine         TEXT,
    gemini_model_used  TEXT,
    updated_at         TEXT NOT NULL
);
"""
CREATE_IDX = "CREATE INDEX IF NOT EXISTS idx_ctx_intel_date ON context_intelligence(date);"


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(DDL)
    conn.execute(CREATE_IDX)
    existing = {
        r[1] for r in conn.execute("PRAGMA table_info(context_intelligence);").fetchall()
    }
    for col, typedef in [
        ("weather_api_error", "TEXT"),
        ("llm_engine",        "TEXT"),
        ("gemini_model_used", "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE context_intelligence ADD COLUMN {col} {typedef};")
            log(f"  [MIGRATE] Added column '{col}'.")
    conn.commit()


def upsert_context(conn: sqlite3.Connection, row: dict) -> None:
    """Resilient UPSERT — always writes the row regardless of weather/LLM errors."""
    sql = """
    INSERT INTO context_intelligence (
        date, is_holiday, holiday_name, holiday_type,
        temp_max_c, precipitation_mm, weather_condition, weather_source,
        weather_api_error,
        news_headlines, news_disruptors,
        llm_engine, gemini_model_used, updated_at
    ) VALUES (
        :date, :is_holiday, :holiday_name, :holiday_type,
        :temp_max_c, :precipitation_mm, :weather_condition, :weather_source,
        :weather_api_error,
        :news_headlines, :news_disruptors,
        :llm_engine, :gemini_model_used, :updated_at
    )
    ON CONFLICT(date) DO UPDATE SET
        is_holiday        = excluded.is_holiday,
        holiday_name      = excluded.holiday_name,
        holiday_type      = excluded.holiday_type,
        temp_max_c        = excluded.temp_max_c,
        precipitation_mm  = excluded.precipitation_mm,
        weather_condition = excluded.weather_condition,
        weather_source    = excluded.weather_source,
        weather_api_error = excluded.weather_api_error,
        news_headlines    = excluded.news_headlines,
        news_disruptors   = excluded.news_disruptors,
        llm_engine        = excluded.llm_engine,
        gemini_model_used = excluded.gemini_model_used,
        updated_at        = excluded.updated_at;
    """
    try:
        conn.execute(sql, row)
        conn.commit()
    except sqlite3.Error as db_err:
        log(f"  [ERROR] DB upsert failed for {row.get('date')}: {db_err}")
        raise


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 6 — ANOMALY HELPER
# ═══════════════════════════════════════════════════════════════════════════

def get_daily_revenue_stats(conn: sqlite3.Connection) -> dict[str, float]:
    cur = conn.execute(
        "SELECT date, ROUND(SUM(net_revenue),2) FROM fact_sales GROUP BY date ORDER BY date"
    )
    return {r[0]: r[1] for r in cur.fetchall() if r[1] is not None}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════

def get_current_week_dates() -> list[datetime.date]:
    today  = datetime.date(2026, 3, 18)
    monday = today - datetime.timedelta(days=today.weekday())
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def run_context_engine() -> None:

    section("QAFFEINE Universal Context Engine  v3  (Dual-Engine LLM)")
    log(f"  Run date/time  : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  City           : {CITY}, Telangana (IN/TS)")
    log(f"  Database       : {DB_PATH}")
    log(f"  Log output     : {LOG_PATH}")
    log(f"  .env loaded    : {ENV_PATH}")
    log()
    log("  API status:")
    log(f"    WeatherAPI     : {'✓ key present' if WEATHERAPI_KEY    else '✗ missing'}")
    log(f"    NewsAPI        : {'✓ key present' if NEWS_API_KEY      else '✗ missing — using RSS fallback'}")
    log(f"    Gemini (Primary)   : {'✓ ' + GEMINI_KEY[:8] + '…'    if GEMINI_KEY     else '✗ missing'}")
    log(f"    OpenRouter (Backup): {'✓ ' + OPENROUTER_KEY[:12] + '…' if OPENROUTER_KEY else '✗ missing'}")
    log()
    log("  LLM Failover Chain:")
    log("    1. Gemini 2.0 Flash             ← Primary Engine")
    log("    2. Gemini 2.0 Flash Lite        ← Primary fallback")
    log("    3. meta-llama/llama-3.3-70b     ← OpenRouter Backup #1")
    log("    4. mistralai/mistral-small-2603 ← OpenRouter Backup #2")
    log("    5. deepseek/deepseek-chat       ← OpenRouter Backup #3")

    # ── DB init ───────────────────────────────────────────────────────
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    init_db(conn)
    log("\n  DB table 'context_intelligence' ready (schema v3).")

    # ── Initialise LLMManager once (shared across all dates) ──────────
    llm = LLMManager()

    # ── Dates ─────────────────────────────────────────────────────────
    dates_to_process = get_current_week_dates()
    section(f"Processing {len(dates_to_process)} dates (current ISO week)")
    for d in dates_to_process:
        log(f"  {d.strftime('%A %Y-%m-%d')}")

    # ── Revenue baseline ──────────────────────────────────────────────
    revenue_by_date = get_daily_revenue_stats(conn)
    avg_revenue     = (
        sum(revenue_by_date.values()) / len(revenue_by_date)
        if revenue_by_date else None
    )
    log(f"\n  Sales data  : {len(revenue_by_date)} trading days in DB")
    if avg_revenue:
        log(f"  Avg revenue : ₹{avg_revenue:,.0f} / day")

    results: list[dict] = []

    for date_obj in dates_to_process:
        date_str = date_obj.strftime("%Y-%m-%d")
        section(f"DATE: {date_str}  ({date_obj.strftime('%A')})")

        # ─ 1. Holidays ────────────────────────────────────────────────
        log("  [1/4] Telangana regional calendar …")
        hol = get_holiday_info(date_obj)
        if hol["is_holiday"]:
            log(f"  ✓ HOLIDAY → {hol['holiday_name']} ({hol['holiday_type']})")
        else:
            log("  — No public holiday.")

        # ─ 2. Weather ─────────────────────────────────────────────────
        log("\n  [2/4] WeatherAPI historical data …")
        weather = get_weather_context(date_obj)
        log(f"  Condition      : {weather['weather_condition']}")
        log(f"  Avg temp       : {weather['temp_max_c']} °C" if weather['temp_max_c'] is not None else "  Avg temp       : N/A")
        log(f"  Precipitation  : {weather['precipitation_mm']} mm" if weather['precipitation_mm'] is not None else "  Precipitation  : N/A")
        log(f"  Source         : {weather['source']}")
        if weather["api_error_code"]:
            log(f"  ⚠ API error    : code={weather['api_error_code']}  {weather['api_error_msg']}")
        weather_api_error_str = (
            json.dumps({"code": weather["api_error_code"], "msg": weather["api_error_msg"]})
            if weather["api_error_code"] is not None else None
        )

        # ─ 3. News ────────────────────────────────────────────────────
        log("\n  [3/4] Market news headlines …")
        headlines = get_news_headlines(date_obj)
        log(f"  Headlines retrieved: {len(headlines)}")
        for i, h in enumerate(headlines, 1):
            log(f"    {i:2d}. {h[:110]}")

        # ─ 4. LLM (Dual-Engine with Failover) ─────────────────────────
        log("\n  [4/4] LLMManager — operational disruptor analysis …")
        daily_rev = revenue_by_date.get(date_str)

        if headlines:
            prompt = build_disruptor_prompt(date_obj, headlines, daily_rev, avg_revenue)
            result = llm.generate(prompt)

            # Print structured failover log
            for entry in result.fallback_log:
                tag = "  [INFO]   " if entry.startswith("[INFO]") else "  [WARNING]"
                log(f"{tag} {entry}")

            log(f"\n  ── LLM Response ({result.engine}/{result.model}) ──")
            for line in result.text.splitlines():
                log(f"  {line}")

            disruptors    = result.text
            llm_engine    = result.engine
            gemini_model  = result.model if result.engine == "Gemini" else f"OpenRouter/{result.model}"

        else:
            disruptors   = "No headlines — LLM analysis skipped."
            llm_engine   = "none"
            gemini_model = "none"
            log("  [SKIP] No headlines to analyse.")

        # ─ Resilient UPSERT ───────────────────────────────────────────
        row = {
            "date"              : date_str,
            "is_holiday"        : 1 if hol["is_holiday"] else 0,
            "holiday_name"      : hol["holiday_name"],
            "holiday_type"      : hol["holiday_type"],
            "temp_max_c"        : weather["temp_max_c"],
            "precipitation_mm"  : weather["precipitation_mm"],
            "weather_condition" : weather["weather_condition"],
            "weather_source"    : weather["source"],
            "weather_api_error" : weather_api_error_str,
            "news_headlines"    : json.dumps(headlines, ensure_ascii=False),
            "news_disruptors"   : disruptors,
            "llm_engine"        : llm_engine,
            "gemini_model_used" : gemini_model,
            "updated_at"        : datetime.datetime.now().isoformat(),
        }
        upsert_context(conn, row)
        log(f"\n  ✓ Upserted → context_intelligence [{date_str}]  engine={llm_engine}")
        results.append(row)

    # ── Summary ───────────────────────────────────────────────────────
    section("CONTEXT ENGINE SUMMARY")
    log(f"  Dates processed: {len(results)}")
    log()
    log(f"  {'DATE':<14} {'HOLIDAY':<26} {'WEATHER':<24} {'HLS':>4}  {'LLM ENGINE'}")
    log(f"  {'-'*14} {'-'*26} {'-'*24} {'-'*4}  {'-'*28}")
    for r in results:
        hol_str = (r["holiday_name"] or "—")[:24]
        wth_str = (r["weather_condition"] or "N/A")[:22]
        n_heads = len(json.loads(r["news_headlines"]))
        eng     = f"{r['llm_engine']}/{r['gemini_model_used']}"[:28]
        log(f"  {r['date']:<14} {hol_str:<26} {wth_str:<24} {n_heads:>4}  {eng}")

    # ── LLM engine tally ──────────────────────────────────────────────
    gemini_count = sum(1 for r in results if r["llm_engine"] == "Gemini")
    or_count     = sum(1 for r in results if r["llm_engine"] == "OpenRouter")
    log()
    log(f"  LLM Engine Usage:")
    log(f"    Gemini (Primary)      : {gemini_count} / {len(results)} queries")
    log(f"    OpenRouter (Backup)   : {or_count} / {len(results)} queries")

    # ── Holiday spotlight ──────────────────────────────────────────────
    holiday_rows = [r for r in results if r["is_holiday"]]
    if holiday_rows:
        log()
        log(f"  HOLIDAY SPOTLIGHT ({len(holiday_rows)} in this week):")
        for r in holiday_rows:
            log(f"    ► {r['date']}  —  {r['holiday_name']}  [{r['holiday_type']}]")

    # ── DB check ──────────────────────────────────────────────────────
    section("DATABASE VERIFICATION")
    total = conn.execute("SELECT COUNT(*) FROM context_intelligence;").fetchone()[0]
    log(f"  Total rows in context_intelligence: {total}")
    rows = conn.execute("""
        SELECT date, holiday_name, temp_max_c, precipitation_mm,
               weather_condition, llm_engine
        FROM context_intelligence ORDER BY date DESC LIMIT 10;
    """).fetchall()
    log(f"\n  {'DATE':<14} {'HOLIDAY':<22} {'TEMP':>6} {'PRECIP':>8}  {'CONDITION':<22}  {'ENGINE'}")
    log(f"  {'-'*14} {'-'*22} {'-'*6} {'-'*8}  {'-'*22}  {'-'*16}")
    for r in rows:
        hol = (r[1] or "—")[:20]
        tmp = f"{r[2]:.1f}°C" if r[2] is not None else "N/A"
        prc = f"{r[3]:.1f}mm" if r[3] is not None else "N/A"
        cnd = (r[4] or "N/A")[:20]
        eng = (r[5] or "—")[:16]
        log(f"  {r[0]:<14} {hol:<22} {tmp:>6} {prc:>8}  {cnd:<22}  {eng}")

    conn.close()

    # ── Write log ─────────────────────────────────────────────────────
    section("LOG FILE")
    LOG_PATH.write_text("\n".join(LOG_LINES), encoding="utf-8")
    log(f"  Log saved → {LOG_PATH}")
    log("\n  Done. QAFFEINE Universal Context Engine v3 completed.")


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_context_engine()
