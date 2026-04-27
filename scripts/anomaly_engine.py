"""
QAFFEINE Anomaly Engine — Statistical Revenue Anomaly Detection
=================================================================
Calculates a 7-day rolling mean (μ) and standard deviation (σ) for each
outlet's daily revenue.  Flags significant dips using Z-Score:

    Z = (x − μ) / σ

Alert Trigger:  Z < −1.5  →  Significant revenue dip.
Sparsity Guard: Zero-revenue days (store closures) are excluded from
                the rolling window to prevent false positives.

Usage:
    from anomaly_engine import detect_anomalies, detect_anomalies_all_outlets
    anomalies = detect_anomalies_all_outlets()   # returns list[dict]
"""

import os, sqlite3, datetime, statistics
from pathlib import Path
from dataclasses import dataclass, field
from src.config.settings import resolve_db_path

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE    = Path(__file__).resolve().parent.parent
DB_PATH = resolve_db_path(BASE)

# ── Configuration ──────────────────────────────────────────────────────────────
ROLLING_WINDOW   = 7       # days
Z_SCORE_THRESHOLD = -1.5   # alert trigger (dips only)


@dataclass
class AnomalyRecord:
    """A single revenue anomaly flagged by the engine."""
    date          : str
    outlet_name   : str
    revenue       : float
    rolling_mean  : float
    rolling_std   : float
    z_score       : float
    pct_deviation : float       # e.g. −18.2 means 18.2% below rolling mean
    severity      : str         # 'CRITICAL' | 'WARNING'

    def to_dict(self) -> dict:
        return {
            "date"          : self.date,
            "outlet_name"   : self.outlet_name,
            "revenue"       : round(self.revenue, 2),
            "rolling_mean"  : round(self.rolling_mean, 2),
            "rolling_std"   : round(self.rolling_std, 2),
            "z_score"       : round(self.z_score, 2),
            "pct_deviation" : round(self.pct_deviation, 1),
            "severity"      : self.severity,
        }


def _fetch_outlet_daily_revenue(conn: sqlite3.Connection) -> dict[str, list[tuple[str, float]]]:
    """
    Returns {outlet_name: [(date, revenue), ...]} sorted by date.
    Uses AI_TEST_INVOICEBILLREGISTER for pre-aggregated daily totals.
    """
    rows = conn.execute("""
        SELECT LOCATION_NAME, SUBSTR(DT, 1, 10) AS date, ROUND(SUM(NETAMT), 2) AS rev
        FROM AI_TEST_INVOICEBILLREGISTER
        GROUP BY LOCATION_NAME, SUBSTR(DT, 1, 10)
        ORDER BY LOCATION_NAME, date
    """).fetchall()

    outlet_data: dict[str, list[tuple[str, float]]] = {}
    for outlet, date, rev in rows:
        if outlet is None:
            continue
        outlet_data.setdefault(outlet, []).append((date, rev or 0.0))

    return outlet_data


def _compute_rolling_stats(
    daily_series: list[tuple[str, float]],
    window: int = ROLLING_WINDOW,
) -> list[dict]:
    """
    For each day in the series, compute the rolling mean and stdev over the
    preceding `window` days.  Zero-revenue days are excluded from the rolling
    window to avoid poisoning the baseline with store-closure days.

    Returns list of dicts with keys:
        date, revenue, rolling_mean, rolling_std, z_score
    """
    results = []

    for i, (date, revenue) in enumerate(daily_series):
        # Collect up to `window` preceding non-zero revenue days
        lookback = []
        for j in range(max(0, i - window), i):
            _, rev_j = daily_series[j]
            if rev_j > 0:   # ← sparsity guard: ignore zero-revenue (closure) days
                lookback.append(rev_j)

        # Include current day's predecessors only (not the current day itself)
        if len(lookback) < 2:
            # Not enough data to compute meaningful rolling stats
            results.append({
                "date"         : date,
                "revenue"      : revenue,
                "rolling_mean" : None,
                "rolling_std"  : None,
                "z_score"      : None,
            })
            continue

        mu    = statistics.mean(lookback)
        sigma = statistics.stdev(lookback)

        if sigma == 0:
            z = 0.0
        else:
            z = (revenue - mu) / sigma

        results.append({
            "date"         : date,
            "revenue"      : revenue,
            "rolling_mean" : mu,
            "rolling_std"  : sigma,
            "z_score"      : z,
        })

    return results


def detect_anomalies(
    outlet_name: str | None = None,
    z_threshold: float = Z_SCORE_THRESHOLD,
    db_path: Path | str | None = None,
) -> list[AnomalyRecord]:
    """
    Detect revenue anomalies for a specific outlet (or all outlets).

    Parameters
    ----------
    outlet_name : str or None
        If None, runs against all outlets.
    z_threshold : float
        Z-score threshold for flagging (default: −1.5).
    db_path : Path, optional
        Override database path.

    Returns
    -------
    list[AnomalyRecord]
        Sorted by z_score ascending (worst first).
    """
    _db = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(_db))

    outlet_data = _fetch_outlet_daily_revenue(conn)
    conn.close()

    if outlet_name:
        # Filter to just the requested outlet
        outlet_data = {k: v for k, v in outlet_data.items()
                       if k.upper() == outlet_name.upper()}

    anomalies: list[AnomalyRecord] = []

    for outlet, daily_series in outlet_data.items():
        stats = _compute_rolling_stats(daily_series)

        for s in stats:
            if s["z_score"] is None:
                continue
            if s["revenue"] == 0:
                continue                       # skip closure days entirely

            if s["z_score"] < z_threshold:
                pct_dev = ((s["revenue"] - s["rolling_mean"]) / s["rolling_mean"]) * 100
                severity = "CRITICAL" if s["z_score"] < -2.5 else "WARNING"

                anomalies.append(AnomalyRecord(
                    date          = s["date"],
                    outlet_name   = outlet,
                    revenue       = s["revenue"],
                    rolling_mean  = s["rolling_mean"],
                    rolling_std   = s["rolling_std"],
                    z_score       = s["z_score"],
                    pct_deviation = pct_dev,
                    severity      = severity,
                ))

    # Sort worst anomalies first
    anomalies.sort(key=lambda a: a.z_score)
    return anomalies


def detect_anomalies_all_outlets(
    z_threshold: float = Z_SCORE_THRESHOLD,
    db_path: Path | str | None = None,
) -> list[AnomalyRecord]:
    """Convenience wrapper: scan every outlet in the DB."""
    return detect_anomalies(outlet_name=None, z_threshold=z_threshold, db_path=db_path)


def get_anomaly_summary_table(anomalies: list[AnomalyRecord]) -> str:
    """Format anomalies as a readable text table for email / log."""
    if not anomalies:
        return "✅ No significant revenue anomalies detected."

    lines = [
        f"{'DATE':<12} {'OUTLET':<28} {'REV':>10} {'μ (MEAN)':>10} "
        f"{'Z-SCORE':>8}  {'Δ%':>6}  SEVERITY",
        "-" * 100,
    ]
    for a in anomalies:
        lines.append(
            f"{a.date:<12} {a.outlet_name:<28} ₹{a.revenue:>9,.0f} "
            f"₹{a.rolling_mean:>9,.0f} {a.z_score:>8.2f}  "
            f"{a.pct_deviation:>5.1f}%  {a.severity}"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# CLI Entrypoint
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  QAFFEINE Anomaly Engine — Revenue Z-Score Scanner")
    print("=" * 70)
    print(f"  Database : {DB_PATH}")
    print(f"  Window   : {ROLLING_WINDOW} days (rolling)")
    print(f"  Threshold: Z < {Z_SCORE_THRESHOLD}")
    print()

    anomalies = detect_anomalies_all_outlets()
    print(f"  Anomalies found: {len(anomalies)}")
    print()
    print(get_anomaly_summary_table(anomalies))
    print()
    print("  Done.")
