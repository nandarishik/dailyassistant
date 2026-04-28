"""Lightweight date/year hints for Copilot evidence (plan Phase 12)."""

from __future__ import annotations

import re

_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def build_resolved_query_context(question: str, *, default_year: int = 2026) -> dict:
    """
    Extract ISO dates from the user question; record assumed dataset year.
    Does not validate against DB bounds (sidebar_bounds does that elsewhere).
    """
    dates = sorted(set(_DATE_RE.findall(question)))
    year = default_year
    if dates:
        year = int(dates[0][:4])
    return {
        "dates_found": dates,
        "year_assumption": year,
        "source": "regex_iso_in_question" if dates else "default_dataset_year",
    }
