"""Singleton access to the scripts/ Copilot stack (avoids import cycles with copilot_engine)."""

from __future__ import annotations

import sys
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parents[2]
_SCRIPTS = _BASE_DIR / "scripts"
_copilot_agent: object | None = None


def _ensure_scripts_path() -> None:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))


def get_copilot_agent():
    """Process-wide singleton Copilot agent (Streamlit + API share this)."""
    global _copilot_agent
    _ensure_scripts_path()
    if _copilot_agent is None:
        from copilot_brain import CopilotAgent  # pylint: disable=import-error
        from universal_context import LLMManager  # pylint: disable=import-error

        _copilot_agent = CopilotAgent(llm=LLMManager())
    return _copilot_agent


def reset_copilot_agent_for_tests() -> None:
    """Test hook only."""
    global _copilot_agent
    _copilot_agent = None
