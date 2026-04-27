"""
QAFFEINE Forecaster — "What-If" ML Revenue Prediction Engine
==============================================================
Trains a RandomForestRegressor on historical outlet-day revenue data
enriched with temporal, environmental, and categorical features.

    R_pred = f(Outlet, DayOfWeek, IsWeekend, IsHoliday, AvgTemp, Rain_mm)

Usage:
    # Train & save model
    python scripts/forecaster.py

    # Predict from code
    from forecaster import predict_revenue, load_model
    rev = predict_revenue("QAFFEINE HITECH CITY", "2025-12-08", rain_mm=5.0, temp_c=28.0)

Output:
    models/revenue_forecaster.joblib
"""

import os, sys, sqlite3, datetime, json, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass

# Scikit-learn
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import cross_val_score
import joblib
from src.config.settings import resolve_db_path

# Holidays
import holidays as holidays_lib

warnings.filterwarnings("ignore", category=UserWarning)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE       = Path(__file__).resolve().parent.parent
DB_PATH    = resolve_db_path(BASE)
MODEL_DIR  = BASE / "models"
MODEL_PATH = MODEL_DIR / "revenue_forecaster.joblib"

# ── Constants ──────────────────────────────────────────────────────────────────
def get_outlets():
    try:
        conn = sqlite3.connect(str(DB_PATH))
        outlets = sorted([r[0] for r in conn.execute("SELECT DISTINCT LOCATION_NAME FROM AI_TEST_INVOICEBILLREGISTER WHERE LOCATION_NAME IS NOT NULL").fetchall()])
        conn.close()
        return outlets if outlets else ["UNKNOWN"]
    except:
        return ["UNKNOWN"]

OUTLETS = get_outlets()

# Default weather for Hyderabad December (used when API data unavailable)
DEFAULT_TEMP_C   = 27.0
DEFAULT_RAIN_MM  = 0.5

# ══════════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

def _get_holiday_flag(date_obj: datetime.date) -> int:
    """Return 1 if the date is a Telangana/National holiday, else 0."""
    national = holidays_lib.country_holidays("IN", years=date_obj.year)
    state    = holidays_lib.country_holidays("IN", subdiv="TS", years=date_obj.year)
    return 1 if (date_obj in national or date_obj in state) else 0


def build_features(
    outlet_name: str,
    date_obj:    datetime.date,
    temp_c:      float | None = None,
    rain_mm:     float | None = None,
    outlet_encoder: LabelEncoder | None = None,
) -> dict:
    """
    Build the feature vector for a single (outlet, date) pair.

    Returns a dict with feature names as keys.
    """
    dow = date_obj.weekday()  # 0=Mon, 6=Sun

    features = {
        # Temporal
        "day_mon": 1 if dow == 0 else 0,
        "day_tue": 1 if dow == 1 else 0,
        "day_wed": 1 if dow == 2 else 0,
        "day_thu": 1 if dow == 3 else 0,
        "day_fri": 1 if dow == 4 else 0,
        "day_sat": 1 if dow == 5 else 0,
        "day_sun": 1 if dow == 6 else 0,
        "is_weekend": 1 if dow >= 5 else 0,
        "is_holiday": _get_holiday_flag(date_obj),

        # Environmental
        "avg_temp_c":       temp_c  if temp_c  is not None else DEFAULT_TEMP_C,
        "precipitation_mm": rain_mm if rain_mm is not None else DEFAULT_RAIN_MM,

        # Categorical (encoded)
        "outlet_id": 0,  # will be overwritten below
    }

    # Encode outlet
    if outlet_encoder is not None:
        try:
            features["outlet_id"] = int(outlet_encoder.transform([outlet_name])[0])
        except ValueError:
            features["outlet_id"] = 0
    else:
        # Fallback: simple index
        try:
            features["outlet_id"] = OUTLETS.index(outlet_name)
        except ValueError:
            features["outlet_id"] = 0

    return features


FEATURE_ORDER = [
    "outlet_id",
    "day_mon", "day_tue", "day_wed", "day_thu", "day_fri", "day_sat", "day_sun",
    "is_weekend", "is_holiday",
    "avg_temp_c", "precipitation_mm",
]


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING
# ══════════════════════════════════════════════════════════════════════════════

def _load_training_data() -> pd.DataFrame:
    """
    Load outlet-day revenue from outlet_summary, enriched with weather
    from context_intelligence (if available) and holiday flags.
    """
    conn = sqlite3.connect(str(DB_PATH))

    # Base: outlet-day revenue
    df = pd.read_sql_query("""
        SELECT SUBSTR(DT, 1, 10) AS date, LOCATION_NAME AS outlet_name, SUM(NETAMT) AS net_revenue
        FROM AI_TEST_INVOICEBILLREGISTER
        GROUP BY SUBSTR(DT, 1, 10), LOCATION_NAME
        HAVING SUM(NETAMT) > 0
        ORDER BY date, outlet_name
    """, conn)

    # Weather context (may not cover sales dates)
    try:
        wx = pd.read_sql_query("""
            SELECT date, temp_max_c, precipitation_mm
            FROM context_intelligence
            WHERE temp_max_c IS NOT NULL
        """, conn)
        df = df.merge(wx, on="date", how="left")
    except Exception:
        df["temp_max_c"] = None
        df["precipitation_mm"] = None

    conn.close()

    # Fill missing weather with defaults
    df["temp_max_c"]       = df["temp_max_c"].fillna(DEFAULT_TEMP_C)
    df["precipitation_mm"] = df["precipitation_mm"].fillna(DEFAULT_RAIN_MM)

    return df


def _augment_training_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    With only 42 real data points (7 days x 6 outlets), we augment the
    training set with realistic synthetic variations to give the Random
    Forest enough diversity to learn meaningful patterns.
    """
    np.random.seed(42)
    augmented_rows = []

    for _, row in df.iterrows():
        # Original row
        augmented_rows.append(row.to_dict())

        # Generate 8-12 synthetic variations per real data point
        n_aug = np.random.randint(8, 13)
        for _ in range(n_aug):
            new_row = row.to_dict()

            # Perturb revenue by +-15%
            rev_noise = np.random.uniform(-0.15, 0.15)
            new_row["net_revenue"] = row["net_revenue"] * (1 + rev_noise)

            # Perturb weather
            new_row["temp_max_c"] = row["temp_max_c"] + np.random.uniform(-4, 4)
            new_row["precipitation_mm"] = max(0, row["precipitation_mm"]
                                               + np.random.uniform(-2, 15))

            # Simulate rain impact: heavy rain reduces revenue
            if new_row["precipitation_mm"] > 10:
                rain_penalty = np.random.uniform(0.05, 0.20)
                new_row["net_revenue"] *= (1 - rain_penalty)

            augmented_rows.append(new_row)

    return pd.DataFrame(augmented_rows)


def train_model(verbose: bool = True) -> tuple:
    """
    Train the RandomForestRegressor and save to disk.

    Returns (model, label_encoder, metrics_dict).
    """
    if verbose:
        print("=" * 60)
        print("  QAFFEINE Forecaster — Model Training")
        print("=" * 60)

    # Load data
    df = _load_training_data()
    if verbose:
        print(f"\n  Raw data points  : {len(df)} (outlet × day)")
        print(f"  Date range       : {df['date'].min()} → {df['date'].max()}")
        print(f"  Outlets          : {df['outlet_name'].nunique()}")

    # Augment
    df = _augment_training_data(df)
    if verbose:
        print(f"  Augmented dataset: {len(df)} samples")

    # Encode outlet
    le = LabelEncoder()
    le.fit(OUTLETS)

    # Build feature matrix
    X_rows = []
    y = []
    for _, row in df.iterrows():
        date_obj = datetime.date.fromisoformat(str(row["date"])[:10])
        feat = build_features(
            outlet_name=row["outlet_name"],
            date_obj=date_obj,
            temp_c=row["temp_max_c"],
            rain_mm=row["precipitation_mm"],
            outlet_encoder=le,
        )
        X_rows.append([feat[f] for f in FEATURE_ORDER])
        y.append(row["net_revenue"])

    X = np.array(X_rows, dtype=np.float64)
    y = np.array(y, dtype=np.float64)

    if verbose:
        print(f"  Feature matrix   : {X.shape}")
        print(f"  Features         : {FEATURE_ORDER}")

    # Train
    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=12,
        min_samples_split=5,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X, y)

    # Cross-validation
    cv_scores = cross_val_score(model, X, y, cv=min(5, len(X) // 5),
                                scoring="r2")

    # Feature importance
    importances = dict(zip(FEATURE_ORDER, model.feature_importances_))

    metrics = {
        "n_samples"       : len(X),
        "n_features"      : X.shape[1],
        "cv_r2_mean"      : round(float(cv_scores.mean()), 4),
        "cv_r2_std"       : round(float(cv_scores.std()), 4),
        "feature_importance": {k: round(float(v), 4) for k, v in
                               sorted(importances.items(), key=lambda x: -x[1])},
        "trained_at"      : datetime.datetime.now().isoformat(),
    }

    if verbose:
        print(f"\n  CV R² Score      : {metrics['cv_r2_mean']:.4f} "
              f"(±{metrics['cv_r2_std']:.4f})")
        print("\n  Feature Importance:")
        for feat, imp in metrics["feature_importance"].items():
            bar = "█" * int(imp * 50)
            print(f"    {feat:<20} {imp:.4f}  {bar}")

    # Save
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    artifact = {
        "model": model,
        "label_encoder": le,
        "feature_order": FEATURE_ORDER,
        "metrics": metrics,
        "outlets": OUTLETS,
    }
    joblib.dump(artifact, str(MODEL_PATH))

    if verbose:
        print(f"\n  Model saved      : {MODEL_PATH}")
        print(f"  Model size       : {MODEL_PATH.stat().st_size / 1024:.0f} KB")

    return model, le, metrics


# ══════════════════════════════════════════════════════════════════════════════
# PREDICTION
# ══════════════════════════════════════════════════════════════════════════════

_CACHED_ARTIFACT = None

def load_model() -> dict:
    """Load the trained model artifact from disk (cached in memory)."""
    global _CACHED_ARTIFACT
    if _CACHED_ARTIFACT is not None:
        return _CACHED_ARTIFACT
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found at {MODEL_PATH}. Run `python scripts/forecaster.py` first."
        )
    _CACHED_ARTIFACT = joblib.load(str(MODEL_PATH))
    return _CACHED_ARTIFACT


def predict_revenue(
    outlet_name: str,
    date_str:    str,
    rain_mm:     float | None = None,
    temp_c:      float | None = None,
) -> dict:
    """
    Predict daily revenue for a specific outlet under given conditions.

    Returns dict with:
        predicted_revenue, baseline_revenue (sunny day), delta_pct,
        outlet, date, conditions.
    """
    artifact = load_model()
    model    = artifact["model"]
    le       = artifact["label_encoder"]

    try:
        date_obj = datetime.date.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Invalid date: {date_str}. Use YYYY-MM-DD."}

    # Match outlet name (fuzzy)
    matched_outlet = None
    for o in OUTLETS:
        if outlet_name.upper() in o.upper() or o.upper() in outlet_name.upper():
            matched_outlet = o
            break
    if not matched_outlet:
        matched_outlet = outlet_name  # use as-is, encoder will default

    # Build features for the given scenario
    feat = build_features(
        outlet_name=matched_outlet,
        date_obj=date_obj,
        temp_c=temp_c,
        rain_mm=rain_mm,
        outlet_encoder=le,
    )
    X = np.array([[feat[f] for f in FEATURE_ORDER]], dtype=np.float64)
    predicted = float(model.predict(X)[0])

    # Baseline: same day, sunny conditions (0mm rain, 28°C)
    feat_baseline = build_features(
        outlet_name=matched_outlet,
        date_obj=date_obj,
        temp_c=28.0,
        rain_mm=0.0,
        outlet_encoder=le,
    )
    X_base = np.array([[feat_baseline[f] for f in FEATURE_ORDER]], dtype=np.float64)
    baseline = float(model.predict(X_base)[0])

    delta_pct = ((predicted - baseline) / baseline * 100) if baseline > 0 else 0.0

    return {
        "predicted_revenue": round(predicted, 0),
        "baseline_revenue":  round(baseline, 0),
        "delta_pct":         round(delta_pct, 1),
        "outlet":            matched_outlet,
        "date":              date_str,
        "day_of_week":       date_obj.strftime("%A"),
        "conditions": {
            "rain_mm":     rain_mm if rain_mm is not None else DEFAULT_RAIN_MM,
            "temp_c":      temp_c  if temp_c  is not None else DEFAULT_TEMP_C,
            "is_holiday":  _get_holiday_flag(date_obj),
            "is_weekend":  1 if date_obj.weekday() >= 5 else 0,
        },
    }


def simulate_scenario(
    outlet:  str,
    date:    str,
    rain_mm: float = 0.0,
    temp_c:  float = 28.0,
) -> str:
    """
    Simulate a weather scenario and return a formatted comparison string.
    This is the function registered as a Jarvis tool.
    """
    result = predict_revenue(outlet, date, rain_mm=rain_mm, temp_c=temp_c)

    if "error" in result:
        return f"Simulation error: {result['error']}"

    pred   = result["predicted_revenue"]
    base   = result["baseline_revenue"]
    delta  = result["delta_pct"]
    cond   = result["conditions"]

    direction = "decrease" if delta < 0 else "increase"
    emoji     = "📉" if delta < 0 else ("📈" if delta > 0 else "➡️")

    lines = [
        f"Revenue Simulation for {result['outlet']}",
        f"  Date: {result['date']} ({result['day_of_week']})",
        f"  Conditions: {cond['rain_mm']}mm rain, {cond['temp_c']}°C"
        f"{'  🗓️ HOLIDAY' if cond['is_holiday'] else ''}"
        f"{'  📅 Weekend' if cond['is_weekend'] else ''}",
        f"",
        f"  {emoji} Predicted Revenue: ₹{pred:,.0f}",
        f"  ☀️  Baseline (Sunny):    ₹{base:,.0f}",
        f"  Δ:  {delta:+.1f}% {direction}",
        f"",
    ]

    if delta < -10:
        lines.append(f"  ⚠️ ALERT: Significant revenue risk ({delta:+.1f}%). "
                      f"Consider proactive marketing or staffing adjustments.")
    elif delta > 5:
        lines.append(f"  🟢 Opportunity: Conditions favor higher revenue. "
                      f"Consider extending hours or launching promotions.")
    else:
        lines.append(f"  🟡 Moderate impact expected. Monitor conditions closely.")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# HOURLY TREND GENERATOR (for area-chart visualisation)
# ══════════════════════════════════════════════════════════════════════════════

# Typical café hourly revenue distribution (percentage of daily revenue)
_HOURLY_PROFILE = {
    6: 0.02, 7: 0.04, 8: 0.07, 9: 0.08, 10: 0.09, 11: 0.10,
    12: 0.11, 13: 0.09, 14: 0.07, 15: 0.06, 16: 0.06, 17: 0.05,
    18: 0.05, 19: 0.04, 20: 0.04, 21: 0.02, 22: 0.01,
}

def generate_hourly_trend(
    daily_predicted: float,
    daily_baseline:  float,
    rain_mm:         float = 0.0,
) -> pd.DataFrame:
    """
    Generate a synthetic 24-hour revenue curve for both the scenario
    and sunny-day baseline. Rain suppresses morning/evening hours more
    than peak lunch hours.

    Returns a DataFrame with columns: Hour, Baseline, Predicted.
    """
    rows = []
    rain_factor = min(rain_mm / 50.0, 1.0)  # 0-1 scale

    for hour in range(6, 23):
        base_pct = _HOURLY_PROFILE.get(hour, 0.0)

        # Rain suppresses off-peak hours more (morning commute, evening)
        if hour < 10 or hour > 18:
            rain_suppress = 1.0 - (rain_factor * 0.3)
        else:
            rain_suppress = 1.0 - (rain_factor * 0.1)

        rows.append({
            "Hour": f"{hour:02d}:00",
            "Baseline (₹)":  round(daily_baseline  * base_pct, 0),
            "Predicted (₹)": round(daily_predicted * base_pct * rain_suppress, 0),
        })

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# NATURAL LANGUAGE SCENARIO PARSER
# ══════════════════════════════════════════════════════════════════════════════

_SCENARIO_PARSE_PROMPT = """You are a parameter extractor for a café revenue forecasting model.

Given a natural language scenario description, extract these parameters as JSON:
- "outlet": The outlet name. Must be one of: {outlets}
  Match partial names: "Hitech" → "QAFFEINE HITECH CITY", "Bhooja" → "QAFFEINE-BHOOJA",
  "Secunderabad" → "QAFFEINE SECUNDERABAD", "GVK" → "QAFFEINE-GVK-ONE",
  "Phoenix" → "QAFFEINE-PHOENIX", "Musarambagh" → "QAFFFEINE-MUSARAMBAGH"
  If no outlet mentioned, use "QAFFEINE HITECH CITY".
- "rain_mm": Rainfall in mm. Translate descriptions:
  "sunny/clear" → 0, "drizzle/light rain" → 5, "moderate rain" → 10,
  "heavy rain" → 20, "thunderstorm/storm" → 15, "torrential/downpour" → 30, "cyclone" → 40
  If not mentioned, use 0.
- "temp_c": Temperature in Celsius. Translate:
  "cold" → 18, "cool" → 22, "normal" → 27, "warm/hot" → 35, "heatwave" → 42
  If not mentioned, use 27.
- "date": If a day-of-week is mentioned (e.g. "Friday"), use the next upcoming occurrence.
  Format: YYYY-MM-DD. If not mentioned, use "{today}".

User input: "{user_text}"

Return ONLY valid JSON, no markdown fences, no extra text. Example:
{{"outlet": "QAFFEINE HITECH CITY", "rain_mm": 15, "temp_c": 22, "date": "2025-12-06"}}"""


def interpret_scenario_prompt(user_text: str) -> dict:
    """
    Use LLM to parse a natural language scenario description into
    structured parameters for the forecasting model.

    Returns dict with keys: outlet, rain_mm, temp_c, date, raw_text.
    Falls back to rule-based parsing if LLM is unavailable.
    """
    import re

    today = datetime.date.today().strftime("%Y-%m-%d")
    outlets_str = ", ".join(OUTLETS)

    # Try LLM parsing first
    try:
        from universal_context import LLMManager
        llm = LLMManager()
        prompt = _SCENARIO_PARSE_PROMPT.format(
            outlets=outlets_str, today=today, user_text=user_text
        )
        result = llm.generate(prompt)
        text = result.text.strip()

        # Clean markdown fences if present
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        params = json.loads(text)
        params["raw_text"] = user_text
        params["parse_method"] = f"LLM ({result.engine})"

        # Validate and sanitize
        params["rain_mm"] = float(params.get("rain_mm", 0))
        params["temp_c"]  = float(params.get("temp_c", 27))
        if "date" not in params or not params["date"]:
            params["date"] = today

        return params

    except Exception as llm_err:
        pass

    # ── Fallback: rule-based parsing ──────────────────────────────────────
    text_lower = user_text.lower()
    params = {
        "outlet": "QAFFEINE HITECH CITY",
        "rain_mm": 0.0,
        "temp_c": 27.0,
        "date": today,
        "raw_text": user_text,
        "parse_method": "Rule-based fallback",
    }

    # Outlet matching
    outlet_keywords = {o.lower(): o for o in OUTLETS}
    for kw, outlet in outlet_keywords.items():
        if kw in text_lower:
            params["outlet"] = outlet
            break

    # Rain parsing
    rain_keywords = {
        "torrential": 30, "downpour": 30, "cyclone": 40,
        "heavy rain": 20, "thunderstorm": 15, "storm": 15,
        "moderate rain": 10, "rain": 8, "drizzle": 5,
        "light rain": 5, "showers": 8, "sunny": 0, "clear": 0,
    }
    for kw, mm in sorted(rain_keywords.items(), key=lambda x: -len(x[0])):
        if kw in text_lower:
            params["rain_mm"] = mm
            break

    # Temp parsing
    temp_keywords = {
        "heatwave": 42, "scorching": 40, "hot": 35, "warm": 32,
        "cool": 22, "cold": 18, "freezing": 12,
    }
    for kw, tc in temp_keywords.items():
        if kw in text_lower:
            params["temp_c"] = tc
            break

    # Day-of-week parsing
    day_names = ["monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"]
    for i, day_name in enumerate(day_names):
        if day_name in text_lower:
            today_obj = datetime.date.today()
            days_ahead = i - today_obj.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            params["date"] = (today_obj + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            break

    return params


# ══════════════════════════════════════════════════════════════════════════════
# CLI Entrypoint
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    model, le, metrics = train_model(verbose=True)

    print("\n" + "=" * 60)
    print("  PREDICTION TEST")
    print("=" * 60)

    # Test scenarios
    scenarios = [
        ("QAFFEINE HITECH CITY", "2025-12-06", 0.0,  28.0, "Sunny Saturday"),
        ("QAFFEINE HITECH CITY", "2025-12-06", 15.0, 24.0, "Rainy Saturday"),
        ("QAFFEINE HITECH CITY", "2025-12-07", 0.0,  28.0, "Sunny Sunday"),
        ("QAFFEINE HITECH CITY", "2025-12-07", 25.0, 22.0, "Thunderstorm Sunday"),
        ("QAFFEINE-PHOENIX",     "2025-12-04", 0.0,  30.0, "Sunny Thursday"),
        ("QAFFEINE-PHOENIX",     "2025-12-04", 20.0, 23.0, "Rainy Thursday"),
    ]

    for outlet, date, rain, temp, label in scenarios:
        r = predict_revenue(outlet, date, rain_mm=rain, temp_c=temp)
        print(f"\n  {label} @ {outlet[:24]}")
        print(f"    Predicted: ₹{r['predicted_revenue']:,.0f}  |  "
              f"Baseline: ₹{r['baseline_revenue']:,.0f}  |  "
              f"Δ: {r['delta_pct']:+.1f}%")

    print("\n  Done.")
