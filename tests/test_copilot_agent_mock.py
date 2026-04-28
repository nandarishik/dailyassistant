"""
Mocked CopilotAgent.investigate — no real LLM or warehouse required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# `universal_context` pulls deps at import time; allow minimal test envs (e.g. CI without extras).
def _stub_script_deps() -> None:
    import types

    if "feedparser" not in sys.modules:
        sys.modules["feedparser"] = types.ModuleType("feedparser")
    if "holidays" not in sys.modules:
        sys.modules["holidays"] = types.ModuleType("holidays")
    if "google.genai" not in sys.modules:
        genai = types.ModuleType("google.genai")

        class _Client:
            def __init__(self, *a, **k):
                pass

        genai.Client = _Client
        g = sys.modules.get("google")
        if g is None or not hasattr(g, "genai"):
            g = types.ModuleType("google")
            g.genai = genai
            sys.modules["google"] = g
        sys.modules["google.genai"] = genai


_stub_script_deps()

import copilot_brain as cb  # noqa: E402


def _mini_db(tmp: Path) -> None:
    db = tmp / "database" / "AI_DATABASE.DB"
    db.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE AI_TEST_INVOICEBILLREGISTER (
                DT TEXT, LOCATION_NAME TEXT, NETAMT REAL, TRNNO TEXT
            );
            INSERT INTO AI_TEST_INVOICEBILLREGISTER VALUES
              ('2026-01-01T10:00:00','O1',100.0,'t1');
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def copilot_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _mini_db(tmp_path)
    monkeypatch.setenv("APP_DB_PATH", "database/AI_DATABASE.DB")
    monkeypatch.setattr(cb, "BASE", tmp_path)
    from src.config.settings import clear_settings_cache

    clear_settings_cache()
    yield tmp_path
    monkeypatch.delenv("APP_DB_PATH", raising=False)
    clear_settings_cache()


def test_investigate_mock_llm_populates_evidence(copilot_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sql = (
        "SELECT IFNULL(ROUND(NETAMT,0),0) AS revenue "
        "FROM AI_TEST_INVOICEBILLREGISTER LIMIT 1"
    )
    plan = [{"tool": "query_sales_db", "args": {"sql": sql}}]

    class FakeLLM:
        def generate(self, prompt: str, **kwargs):
            from universal_context import LLMManager

            if "=== TOOL RESULTS ===" in prompt:
                text = (
                    "**Data facts:** Verified.\n**Scope:** Local.\n"
                    "**Context (secondary):** None.\n**Possible explanations:** None."
                )
            else:
                text = json.dumps(plan)
            return LLMManager.Result(text, "fake", "mock-model", [])

    monkeypatch.setattr(
        cb,
        "fetch_select_as_markdown",
        lambda _base, _sql, **kw: "| revenue | n |\n| --- | --- |\n| 100 | 1 |\n",
    )

    agent = cb.CopilotAgent(llm=FakeLLM())
    r = agent.investigate("What was revenue on 2026-01-01?")

    assert not r.error
    assert r.tool_calls and r.tool_calls[0].tool == "query_sales_db"
    assert r.evidence.get("data_scope")
    assert "date_window_interpreted" in r.evidence["data_scope"]
    assert r.evidence.get("numeric_facts")
    assert r.response
    assert r.engine == "fake"
