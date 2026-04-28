from __future__ import annotations

import json

import pytest
from src.copilot.planner_parse import parse_planner_tool_plan


def test_parse_planner_prefers_balanced_array() -> None:
    inner = json.dumps([{"tool": "query_sales_db", "args": {"sql": "SELECT 1"}}])
    raw = f"Here you go: {inner} and trailing junk [1, 2]"
    plan = parse_planner_tool_plan(raw)
    assert len(plan) == 1
    assert plan[0]["tool"] == "query_sales_db"


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n[]\n```",
        "[]",
        'prefix [{"tool": "query_sales_db", "args": {}}]',
    ],
)
def test_parse_planner_accepts_empty_or_wrapped(raw: str) -> None:
    plan = parse_planner_tool_plan(raw)
    assert isinstance(plan, list)
