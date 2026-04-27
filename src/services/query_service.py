from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from src.contracts.copilot import CopilotResponse


def _load_copilot_agent():
    base_dir = Path(__file__).resolve().parents[2]
    scripts_dir = base_dir / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from copilot_brain import CopilotAgent, LLMManager  # pylint: disable=import-error
    return CopilotAgent(llm=LLMManager())


def run_copilot_query(question: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        agent = _load_copilot_agent()
        result = agent.investigate(question)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response = CopilotResponse(
            status="ok",
            answer_text=result.answer or "",
            tool_calls=result.tool_calls or [],
            guardrail_flags=[],
            latency_ms=elapsed_ms,
            error=None,
        )
        return response.to_dict()
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response = CopilotResponse(
            status="error",
            answer_text="",
            tool_calls=[],
            guardrail_flags=[],
            latency_ms=elapsed_ms,
            error=str(exc),
        )
        return response.to_dict()
