"""
Post-synthesis checks: inflated totals vs verified column_sums (plan Phase 4).
"""

from __future__ import annotations

import re
from typing import Any

_MONEY = re.compile(
    r"(?:₹\s*|INR\s*|Rs\.?\s*)([\d,]+(?:\.\d+)?)|\b([\d,]{5,}(?:\.\d+)?)\b",
    re.IGNORECASE,
)


def _parse_num(s: str) -> float | None:
    t = s.replace(",", "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def extract_money_like_numbers(text: str, *, min_value: float = 10_000) -> list[float]:
    out: list[float] = []
    for m in _MONEY.finditer(text or ""):
        g = m.group(1) or m.group(2)
        v = _parse_num(g)
        if v is not None and v >= min_value:
            out.append(v)
    return out


def primary_verified_table_total(numeric_facts: list[dict[str, Any]]) -> tuple[float | None, str]:
    """Pick the main revenue-like column sum from digested query_sales_db facts."""
    for f in numeric_facts:
        sums = f.get("column_sums") or {}
        for k, v in sums.items():
            kl = k.lower()
            if "revenue" in kl or "total" in kl or "netamt" in kl:
                try:
                    return float(v), k
                except (TypeError, ValueError):
                    continue
    for f in numeric_facts:
        sums = f.get("column_sums") or {}
        if sums:
            best_k = max(sums, key=lambda kk: float(sums[kk]))
            try:
                return float(sums[best_k]), best_k
            except (TypeError, ValueError):
                continue
    return None, ""


def apply_numeric_postcheck(
    response: str,
    numeric_facts: list[dict[str, Any]],
    *,
    enabled: bool,
) -> tuple[str, list[str]]:
    """
    If the model states a figure larger than the verified table total, append a
    correction footer and return flags.
    """
    flags: list[str] = []
    if not enabled or not numeric_facts or not (response or "").strip():
        return response, flags

    verified, col = primary_verified_table_total(numeric_facts)
    if verified is None or verified <= 0:
        return response, flags

    min_extract = 10_000.0 if verified >= 10_000 else max(500.0, verified * 0.05)
    nums = extract_money_like_numbers(response, min_value=min_extract)
    if not nums:
        return response, flags

    max_n = max(nums)
    # Typical failure: invented chain total larger than true sum of outlet table
    if max_n > verified * 1.02:
        flags.append("numeric_mismatch")
        footer = (
            f"\n\n---\n**Verified (SQL table):** sum of **`{col}`** over the returned rows = "
            f"**₹{verified:,.0f}**. The narrative above included a larger figure "
            f"(**₹{max_n:,.0f}**); use **₹{verified:,.0f}** as the chain total for this query result."
        )
        return response.rstrip() + footer, flags

    # Under-stated total: narrative cites a dominant figure far below verified aggregate
    if verified >= 5_000 and max_n < verified * 0.48:
        flags.append("numeric_mismatch_low")
        footer = (
            f"\n\n---\n**Verified (SQL table):** sum of **`{col}`** over the returned rows = "
            f"**₹{verified:,.0f}**. The narrative above cited **₹{max_n:,.0f}**, which is much lower "
            f"than the verified total—use **₹{verified:,.0f}** for the chain aggregate for this result."
        )
        return response.rstrip() + footer, flags

    return response, flags
