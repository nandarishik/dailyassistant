from __future__ import annotations

import pytest
from src.contracts.kpi_tab import KpiTabQuery


def test_kpi_query_valid() -> None:
    m = KpiTabQuery(
        outlets=["A", "B"],
        date_start="2026-01-01",
        date_end="2026-01-31",
    )
    assert m.outlets == ["A", "B"]


def test_kpi_query_rejects_bad_date() -> None:
    with pytest.raises(ValueError):
        KpiTabQuery(
            outlets=["A"],
            date_start="not-a-date",
            date_end="2026-01-31",
        )


def test_kpi_query_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="date_start"):
        KpiTabQuery(
            outlets=["A"],
            date_start="2026-02-01",
            date_end="2026-01-01",
        )
