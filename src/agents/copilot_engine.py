"""
Single entry for Copilot investigation (Mark II).

Order:
1. Optional guarded intent → SQL path (settings.use_guarded_sql_pipeline).
2. Legacy LLM agent (scripts.copilot_brain) with wall-clock timeout.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

from src.agents.legacy_adapter import get_copilot_agent
from src.config.settings import get_settings
from src.intent.pipeline import try_guarded_intent_run

_BASE_DIR = Path(__file__).resolve().parents[2]


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


def _run_legacy_agent(question: str) -> dict[str, Any]:
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


def investigate(question: str) -> dict[str, Any]:
    """
    Full Copilot run; dict shape used by Streamlit and HTTP serialization.
    Adds query_id; merges evidence from intent path when present.
    """
    query_id = str(uuid.uuid4())
    settings = get_settings()

    if settings.use_guarded_sql_pipeline:
        hit = try_guarded_intent_run(question, _BASE_DIR)
        if hit is not None:
            hit = {**hit, "query_id": query_id}
            return hit

    timeout = float(settings.copilot_timeout_seconds)
    if timeout <= 0:
        out = _run_legacy_agent(question)
        out["query_id"] = query_id
        return out

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_run_legacy_agent, question)
        try:
            out = fut.result(timeout=timeout)
        except FuturesTimeout:
            fut.cancel()
            return {
                "question": question,
                "tool_calls": [],
                "response": "",
                "engine": "",
                "model": "",
                "error": f"Copilot timed out after {timeout:.0f}s.",
                "monologue": [f"⏱️ Investigation exceeded {timeout:.0f}s and was stopped."],
                "query_id": query_id,
            }
    out["query_id"] = query_id
    return out
