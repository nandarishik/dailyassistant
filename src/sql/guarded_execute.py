"""Run LLM-guarded SELECTs and return a compact markdown table (shared by intent pipeline and tools)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

from src.config.settings import get_settings
from src.data.access.db import sqlite_connection
from src.sql.sql_guard import ensure_row_limit, validate_llm_select


def _rows_to_markdown(cols: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return "Query returned 0 rows."
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(" --- " for _ in cols) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def fetch_select_as_markdown(
    base_dir: Path,
    sql: str,
    *,
    row_cap: int = 200,
    progress_nudge: int = 200_000,
    max_progress_callbacks: int = 25,
) -> str:
    """
    Validate SQL, enforce LIMIT, execute, return markdown table or an error string.
    """
    settings = get_settings()
    ok, err = validate_llm_select(
        sql,
        block_union=settings.sql_guard_block_union,
        enforce_table_allowlist=settings.sql_guard_table_allowlist,
    )
    if not ok:
        return f"ERROR: {err}"
    query = ensure_row_limit(sql.strip().rstrip(";"), default_limit=row_cap)
    try:
        with sqlite_connection(base_dir) as conn:
            callback_count = {"n": 0}

            def _progress_abort() -> int:
                callback_count["n"] += 1
                return 1 if callback_count["n"] > max_progress_callbacks else 0

            conn.set_progress_handler(_progress_abort, progress_nudge)
            try:
                cur = conn.execute(query)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(row_cap)
            finally:
                conn.set_progress_handler(None, 0)
    except sqlite3.OperationalError as exc:
        return f"SQL Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"SQL Error: {exc}"

    return _rows_to_markdown(cols, rows)


def fetch_select_as_markdown_params(
    base_dir: Path,
    sql: str,
    params: Sequence[Any],
    *,
    row_cap: int = 200,
    progress_nudge: int = 200_000,
    max_progress_callbacks: int = 25,
) -> str:
    """
    Same as fetch_select_as_markdown but with bound parameters (intent templates).
    """
    settings = get_settings()
    ok, err = validate_llm_select(
        sql,
        block_union=settings.sql_guard_block_union,
        enforce_table_allowlist=settings.sql_guard_table_allowlist,
    )
    if not ok:
        return f"ERROR: {err}"
    query = ensure_row_limit(sql.strip().rstrip(";"), default_limit=row_cap)
    try:
        with sqlite_connection(base_dir) as conn:
            callback_count = {"n": 0}

            def _progress_abort() -> int:
                callback_count["n"] += 1
                return 1 if callback_count["n"] > max_progress_callbacks else 0

            conn.set_progress_handler(_progress_abort, progress_nudge)
            try:
                cur = conn.execute(query, tuple(params))
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(row_cap)
            finally:
                conn.set_progress_handler(None, 0)
    except sqlite3.OperationalError as exc:
        return f"SQL Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"SQL Error: {exc}"

    return _rows_to_markdown(cols, rows)
