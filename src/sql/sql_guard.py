"""Read-only SQL guard for LLM-originated queries (plan D2 policy baseline)."""

from __future__ import annotations

import re

_SQL_KEYWORDS = frozenset(
    {
        "SELECT",
        "WITH",
        "WHERE",
        "GROUP",
        "ORDER",
        "INNER",
        "LEFT",
        "RIGHT",
        "CROSS",
        "OUTER",
        "JOIN",
        "ON",
        "AS",
        "AND",
        "OR",
        "NOT",
        "NULL",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "FROM",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "UNION",
        "ALL",
        "DISTINCT",
    }
)


def _allowed_table_name(name: str) -> bool:
    t = name.split(".")[-1]
    if t.upper() in _SQL_KEYWORDS:
        return True
    return t.startswith("AI_TEST_") or t.lower() == "context_intelligence"


def _referenced_tables(sql: str) -> list[str]:
    """Naive FROM/JOIN table names (identifiers only; subqueries may false-positive)."""
    out: list[str] = []
    for m in re.finditer(r"(?is)\b(?:FROM|JOIN)\s+([`\"]?)([\w.]+)\1", sql):
        name = m.group(2)
        if name and not name.startswith("("):
            out.append(name)
    return out


def validate_llm_select(
    sql: str,
    *,
    block_union: bool = False,
    enforce_table_allowlist: bool = False,
) -> tuple[bool, str]:
    """
    Return (ok, error_message). Allows a single SELECT only; blocks obvious injection paths.
    """
    query = sql.strip().rstrip(";")
    if not query:
        return False, "Empty SQL"
    if ";" in query:
        return False, "Multiple statements are not allowed"
    if not (
        re.match(r"(?is)^\s*SELECT\b", query) or re.match(r"(?is)^\s*WITH\b", query)
    ):
        return False, "Only SELECT queries are permitted"
    if re.search(
        r"(?is)\b(sqlite_master|sqlite_schema|pragma|attach|detach|load_extension|vacuum)\b",
        query,
    ):
        return False, "Query touches restricted SQLite internals or commands"
    if block_union and re.search(r"(?is)\bUNION\b", query):
        return False, "UNION is not permitted for this query"
    if enforce_table_allowlist:
        for name in _referenced_tables(query):
            if not _allowed_table_name(name):
                return False, f"Disallowed table reference: {name}"
    return True, ""


def ensure_row_limit(sql: str, default_limit: int = 200) -> str:
    """Append LIMIT if missing (bounded scans)."""
    q = sql.strip().rstrip(";")
    if re.search(r"(?is)\bLIMIT\s+\d+\b", q):
        return q
    return f"{q} LIMIT {default_limit}"
