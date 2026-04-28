from __future__ import annotations

from src.copilot.numeric_postcheck import (
    apply_numeric_postcheck,
    extract_money_like_numbers,
    primary_verified_table_total,
)


def test_primary_verified_prefers_revenue_column() -> None:
    facts = [
        {
            "column_sums": {"revenue": 3653162.0},
        }
    ]
    v, k = primary_verified_table_total(facts)
    assert v == 3653162.0
    assert k == "revenue"


def test_postcheck_appends_footer_on_inflated_total() -> None:
    facts = [{"column_sums": {"revenue": 3653162.0}}]
    bad = "Total chain revenue was ₹5,318,119 across outlets."
    out, flags = apply_numeric_postcheck(bad, facts, enabled=True)
    assert "numeric_mismatch" in flags
    assert "3,653,162" in out
    assert "5,318,119" in out


def test_postcheck_disabled_noop() -> None:
    facts = [{"column_sums": {"revenue": 100.0}}]
    out, flags = apply_numeric_postcheck("Total ₹999", facts, enabled=False)
    assert flags == []
    assert out == "Total ₹999"


def test_extract_money_numbers() -> None:
    t = "Mix ₹3,653,162 and 5318119 and small 50"
    nums = extract_money_like_numbers(t)
    assert 3653162.0 in nums
    assert 5318119.0 in nums
    assert 50 not in nums  # below 10k threshold


def test_postcheck_flags_understated_total() -> None:
    facts = [{"column_sums": {"total_revenue": 100_000.0}}]
    low = "The chain total was only ₹20,000 on that day."
    out, flags = apply_numeric_postcheck(low, facts, enabled=True)
    assert "numeric_mismatch_low" in flags
    assert "100,000" in out
