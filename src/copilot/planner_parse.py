"""Extract a JSON tool-call array from LLM planner output (unit-testable without scripts/)."""

from __future__ import annotations

import json
import re


def extract_json_array_fragment(text: str) -> str | None:
    """First top-level `[` … `]` span with rudimentary string-literal awareness."""
    i = text.find("[")
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
    return None


def parse_planner_tool_plan(raw: str) -> list:
    raw2 = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip().strip("`").strip()
    try:
        plan = json.loads(raw2)
        if isinstance(plan, list):
            return plan
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    frag = extract_json_array_fragment(raw2)
    if frag:
        try:
            plan = json.loads(frag)
            if isinstance(plan, list):
                return plan
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return []
