"""
Parse markdown pipe tables from tool output and compute per-column sums.

Used by Copilot synthesis so chain totals can be machine-checked (see
docs/COPILOT_NUMERIC_INTEGRITY_PLAN.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def _split_md_row(line: str) -> list[str] | None:
    s = line.strip()
    if "|" not in s:
        return None
    parts = [p.strip() for p in s.split("|")]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    if len(parts) < 2:
        return None
    return parts


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    for c in cells:
        t = c.strip()
        if not t:
            return False
        if not re.fullmatch(r":?-{3,}:?", t):
            return False
    return True


def _parse_number(cell: str) -> float | None:
    t = cell.strip().replace(",", "")
    if not t or t == "-":
        return None
    try:
        return float(t)
    except ValueError:
        return None


@dataclass
class TableDigest:
    """Aggregates for one markdown pipe table."""

    headers: list[str]
    row_count: int
    column_sums: dict[str, float] = field(default_factory=dict)
    numeric_columns: list[str] = field(default_factory=list)


def _digest_single_table(headers: list[str], rows: list[list[str]]) -> TableDigest:
    ncols = len(headers)
    col_idx_numeric: list[bool] = [True] * ncols
    sums = [0.0] * ncols
    counts = [0] * ncols

    for row in rows:
        if len(row) != ncols:
            # ragged row: mark all False for strictness
            for j in range(ncols):
                col_idx_numeric[j] = False
            continue
        for j in range(ncols):
            if not col_idx_numeric[j]:
                continue
            val = _parse_number(row[j])
            if val is None:
                col_idx_numeric[j] = False
                sums[j] = 0.0
                counts[j] = 0
            else:
                sums[j] += val
                counts[j] += 1

    column_sums: dict[str, float] = {}
    numeric_columns: list[str] = []
    for j, h in enumerate(headers):
        key = h.strip() or f"col_{j}"
        if col_idx_numeric[j] and counts[j] > 0:
            column_sums[key] = round(sums[j], 6)
            numeric_columns.append(key)

    return TableDigest(
        headers=list(headers),
        row_count=len(rows),
        column_sums=column_sums,
        numeric_columns=numeric_columns,
    )


def _extract_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return list of (headers, data_rows) for each pipe table found."""
    lines = text.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        cells = _split_md_row(line)
        if cells is None or len(cells) < 2:
            i += 1
            continue
        # lookahead for separator
        if i + 1 >= len(lines):
            i += 1
            continue
        sep_cells = _split_md_row(lines[i + 1])
        if sep_cells is None or not _is_separator_row(sep_cells):
            i += 1
            continue
        headers = cells
        ncols = len(headers)
        data_rows: list[list[str]] = []
        j = i + 2
        while j < len(lines):
            row_line = lines[j]
            if not row_line.strip():
                break
            row_cells = _split_md_row(row_line)
            if row_cells is None or len(row_cells) != ncols:
                break
            data_rows.append(row_cells)
            j += 1
        if data_rows:
            tables.append((headers, data_rows))
        i = j
    return tables


def digest_markdown_tables(text: str) -> TableDigest | None:
    """
    Parse the **largest** GFM-style pipe table in `text` (by data row count).

    Returns None if no table, empty data, or text looks like an error message.
    """
    if not text or not text.strip():
        return None
    head = text.lstrip()[:200].upper()
    if head.startswith("ERROR:") or head.startswith("SQL ERROR"):
        return None
    if "QUERY RETURNED 0 ROWS" in text.upper():
        return None

    tables = _extract_tables(text)
    if not tables:
        return None

    headers, rows = max(tables, key=lambda t: len(t[1]))
    if not rows:
        return None
    return _digest_single_table(headers, rows)
