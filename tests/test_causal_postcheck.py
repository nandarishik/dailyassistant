from __future__ import annotations

from types import SimpleNamespace

from src.copilot.causal_postcheck import apply_causal_postcheck


def test_causal_postcheck_no_connector() -> None:
    calls = [SimpleNamespace(tool="get_weather_context", result="temp_max_c: 32", success=True)]
    text = "Revenue was flat."
    out, flags = apply_causal_postcheck(text, calls, enabled=True)
    assert flags == []
    assert out == text


def test_causal_postcheck_disabled() -> None:
    calls = [SimpleNamespace(tool="query_sales_db", result="", success=True)]
    text = "Sales dropped because of rain."
    out, flags = apply_causal_postcheck(text, calls, enabled=False)
    assert flags == []
    assert out == text


def test_causal_postcheck_flags_ungrounded_weather_cause() -> None:
    calls = [
        SimpleNamespace(tool="get_weather_context", result="No row", success=True),
    ]
    text = "Revenue fell because of rain and storms in the region."
    out, flags = apply_causal_postcheck(text, calls, enabled=True)
    assert "causal_language_review" in flags
    assert "not proven" in out.lower()
