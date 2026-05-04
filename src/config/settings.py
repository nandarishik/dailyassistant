from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Validated env-backed settings (plan D1 central config)."""

    model_config = SettingsConfigDict(extra="ignore", env_file=None)

    app_db_path: str = "database/AI_DATABASE.DB"
    # Mark II D2: try intent → template SQL before LLM planner (rollback: false).
    use_guarded_sql_pipeline: bool = False
    # Mark II D3: route Copilot through src.agents.copilot_engine (rollback: false).
    use_new_copilot_engine: bool = True
    # Wall-clock cap for the legacy LLM loop (intent path ignores this).
    copilot_timeout_seconds: float = 120.0
    # Append correction footer when prose implies a chain total larger than digest (Phase 4).
    copilot_numeric_validation: bool = False
    # Shorter answers + sectioned structure for client demos (optional).
    copilot_strict_demo_mode: bool = False
    # Append JSONL rows to var/copilot_traces/copilot.jsonl (Phase 14).
    copilot_trace_jsonl: bool = False
    # Premise rank window: all distinct days, same calendar month as target date, or last 90 days.
    copilot_premise_rank_window: str = "all"  # all | month | last90
    # Heuristic scan after numeric postcheck for causal glue (revenue ↔ weather/holiday/news).
    copilot_causal_postcheck: bool = True
    # LLM SQL guard extras (LLM path only; intent templates use parameterized path).
    sql_guard_block_union: bool = False
    sql_guard_table_allowlist: bool = False


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def resolve_db_path(base_dir: Path) -> Path:
    return base_dir / get_settings().app_db_path
