from __future__ import annotations

from src.copilot.numeric_digest import digest_markdown_tables


def test_digest_outlet_revenue_fixture_matches_known_sum() -> None:
    md = """
| LOCATION_NAME | revenue |
| --- | --- |
| TANSEN RESTAURANT | 741807.0 |
| RESIGN SKY BAR | 585834.0 |
| QAFFEINE-PHOENIX | 11371.0 |
"""
    d = digest_markdown_tables(md)
    assert d is not None
    assert d.row_count == 3
    assert d.column_sums["revenue"] == 741807.0 + 585834.0 + 11371.0


def test_digest_picks_largest_table() -> None:
    md = """
| a | b |
| --- | --- |
| 1 | 2 |

| x | y |
| --- | --- |
| 10 | 20 |
| 30 | 40 |
"""
    d = digest_markdown_tables(md)
    assert d is not None
    assert d.row_count == 2
    assert d.column_sums["y"] == 60.0


def test_digest_returns_none_on_error_prefix() -> None:
    assert digest_markdown_tables("ERROR: not allowed") is None


def test_digest_returns_none_on_zero_rows_message() -> None:
    assert digest_markdown_tables("Query returned 0 rows.") is None


def test_digest_comma_numbers() -> None:
    md = """
| name | amt |
| --- | --- |
| a | 1,000.5 |
| b | 2,000 |
"""
    d = digest_markdown_tables(md)
    assert d is not None
    assert d.column_sums["amt"] == 3000.5
