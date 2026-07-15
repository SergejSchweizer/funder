from pathlib import Path

import pytest

from founder.paths import LakePaths
from founder.table_io import read_rows
from founder.univariate_statistics import (
    build_quote_returns,
    build_univariate_statistics,
    write_univariate_statistics,
)


def _quote(date: str, adjusted_close: float) -> dict[str, object]:
    return {
        "run_id": "bronze-1",
        "isin": "IE1",
        "code": "AAA",
        "exchange": "XETRA",
        "date": date,
        "open": adjusted_close,
        "high": adjusted_close,
        "low": adjusted_close,
        "close": adjusted_close,
        "adjusted_close": adjusted_close,
        "volume": 100,
        "currency": "EUR",
        "bronzed_at": "2026-01-04T00:00:00+00:00",
    }


def test_univariate_statistics_are_univariate_and_reference_one_listing(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-01-02", 110.0),
        _quote("2026-01-03", 99.0),
        _quote("2026-01-04", 120.0),
    ]

    returns = build_quote_returns(quotes)
    statistics = build_univariate_statistics(quotes, confidence_level=0.75)
    written = write_univariate_statistics(paths, quotes, confidence_level=0.75)

    assert [row["date"] for row in returns] == ["2026-01-02", "2026-01-03", "2026-01-04"]
    assert returns[0]["log_return"] == pytest.approx(0.0953101798)
    assert returns[0]["simple_return"] == pytest.approx(0.10)
    assert len(statistics) == 1
    row = statistics[0]
    assert row["isin"] == "IE1"
    assert row["return_observation_count"] == 3
    assert row["total_return"] == pytest.approx(0.20)
    assert row["cumulative_log_return"] == pytest.approx(0.1823215568)
    assert row["annualized_geometric_return"] > row["annualized_simple_return"]
    assert row["daily_log_return_std"] > 0.0
    assert row["daily_simple_return_std"] > 0.0
    assert row["realized_variance"] > 0.0
    assert row["realized_volatility"] > 0.0
    assert row["max_drawdown"] == pytest.approx(-0.10)
    assert row["positive_day_ratio"] == pytest.approx(2 / 3)
    assert row["var"] >= 0.0
    assert row["expected_shortfall"] >= row["var"]
    assert row["trend_r_squared"] >= 0.0
    assert row["availability_reason"] == "ok"
    assert written == statistics
    assert read_rows(paths.gold_univariate_statistics("XETRA", "IE1")) == statistics


def test_univariate_statistics_reject_invalid_confidence_level() -> None:
    with pytest.raises(ValueError, match="confidence_level"):
        build_univariate_statistics([_quote("2026-01-01", 100.0)], confidence_level=1.0)
