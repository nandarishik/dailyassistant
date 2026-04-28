"""Lightweight heuristic: causal wording about external drivers vs tool coverage."""

from __future__ import annotations

import re
from typing import Any, Protocol


class _CallLike(Protocol):
    tool: str
    result: str
    success: bool


_CAUSAL = re.compile(
    r"\b(because|due to|caused by|led to|resulted in|driven by|attributed to)\b",
    re.IGNORECASE,
)


def apply_causal_postcheck(
    response: str,
    calls: list[Any],
    *,
    enabled: bool,
) -> tuple[str, list[str]]:
    """
    If the answer uses causal phrasing about weather/holidays/news but the merged
    tool text lacks obvious supporting lines, append a one-line disclaimer.
    """
    flags: list[str] = []
    if not enabled or not (response or "").strip():
        return response, flags
    if not _CAUSAL.search(response):
        return response, flags

    blob = "\n".join(
        str(getattr(c, "result", "") or "")
        for c in calls
        if getattr(c, "success", True)
    ).lower()

    weatherish = bool(re.search(r"\b(weather|rain|precip|storm|temperature)\b", response, re.I))
    holidayish = bool(re.search(r"\b(holiday|festival|public holiday)\b", response, re.I))
    newsish = bool(re.search(r"\b(news|headline|market intelligence)\b", response, re.I))

    had_weather = any(getattr(c, "tool", "") == "get_weather_context" for c in calls)
    had_holiday = any(getattr(c, "tool", "") == "get_holiday_status" for c in calls)
    had_news = any(getattr(c, "tool", "") == "get_news_context" for c in calls)

    suspect = False
    if weatherish and had_weather and "temp" not in blob and "precip" not in blob and "condition" not in blob:
        suspect = True
    if holidayish and had_holiday and "holiday" not in blob:
        suspect = True
    if newsish and had_news and "headline" not in blob and "disruptor" not in blob:
        suspect = True

    if not suspect:
        return response, flags

    flags.append("causal_language_review")
    footer = (
        "\n\n---\n**Note:** Causal links to weather, holidays, or news above are **not proven** "
        "by invoice tables alone; treat them as hypotheses unless a tool explicitly tied them to outcomes."
    )
    return response.rstrip() + footer, flags
