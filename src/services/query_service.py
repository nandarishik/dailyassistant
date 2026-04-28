from __future__ import annotations

import time
from typing import Any

from src.config.settings import get_settings
from src.contracts.copilot import CopilotResponse


def get_copilot_agent():
    """Backward-compatible singleton; implementation lives in `src.agents.legacy_adapter`."""
    from src.agents.legacy_adapter import get_copilot_agent as _ga

    return _ga()


def reset_copilot_agent_for_tests() -> None:
    from src.agents.legacy_adapter import reset_copilot_agent_for_tests as _reset

    _reset()


def _tool_calls_as_dicts(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "tool": tc.tool,
            "args": tc.args,
            "result": tc.result,
            "success": tc.success,
            "emoji": tc.emoji,
            "label": tc.label,
        }
        for tc in (result.tool_calls or [])
    ]


def _legacy_investigate_direct(question: str) -> dict[str, Any]:
    """Rollback path: no engine package, no intent layer, no timeout wrapper."""
    try:
        agent = get_copilot_agent()
        result = agent.investigate(question)
        return {
            "question": question,
            "tool_calls": _tool_calls_as_dicts(result),
            "response": result.response or "",
            "engine": result.engine,
            "model": result.model,
            "error": result.error or "",
            "monologue": list(result.monologue or []),
            "evidence": getattr(result, "evidence", None) or {},
        }
    except Exception as exc:  # noqa: BLE001 — surface to UI
        return {
            "question": question,
            "tool_calls": [],
            "response": "",
            "engine": "",
            "model": "",
            "error": str(exc),
            "monologue": [],
        }


def investigate_copilot_for_ui(question: str) -> dict[str, Any]:
    """
    Full Copilot run; returns the dict shape used by the Streamlit chat tab.
    Swallows hard exceptions into entry.error (same UX as before).
    """
    try:
        if get_settings().use_new_copilot_engine:
            from src.agents.copilot_engine import investigate as engine_investigate

            return engine_investigate(question)
        return _legacy_investigate_direct(question)
    except Exception as exc:  # noqa: BLE001
        return {
            "question": question,
            "tool_calls": [],
            "response": "",
            "engine": "",
            "model": "",
            "error": str(exc),
            "monologue": [],
        }


def run_copilot_query(question: str) -> dict[str, Any]:
    """JSON contract for HTTP / CLI; same engine as investigate_copilot_for_ui."""
    started = time.perf_counter()
    entry = investigate_copilot_for_ui(question)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    err_raw = (entry.get("error") or "").strip()
    flags: list[str] = []
    if entry.get("engine") == "IntentSQL":
        flags.append("intent_sql")
    ev = entry.get("evidence") or {}
    if ev.get("numeric_facts"):
        flags.append("numeric_digest")
    for fl in ev.get("guardrail_flags") or []:
        if fl and fl not in flags:
            flags.append(fl)
    pc = ev.get("premise_check") or {}
    if pc.get("premise_conflict") and "premise_conflict" not in flags:
        flags.append("premise_conflict")
    response = CopilotResponse(
        status="ok" if not err_raw else "error",
        answer_text=entry.get("response") or "",
        tool_calls=entry.get("tool_calls") or [],
        guardrail_flags=flags,
        latency_ms=elapsed_ms,
        error=err_raw or None,
        query_id=entry.get("query_id"),
        evidence=entry.get("evidence"),
    )
    return response.to_dict()
