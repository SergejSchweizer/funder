from datetime import date as _date
from datetime import timedelta
from pathlib import Path

import pytest

from camovar.paths import LakePaths
from camovar.table_io import read_rows
from camovar.univariate_statistics import (
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


def _dividend(date: str, value: float = 1.0) -> dict[str, object]:
    return {
        "run_id": "bronze-1",
        "isin": "IE1",
        "code": "AAA",
        "exchange": "XETRA",
        "date": date,
        "value": value,
        "unadjustedValue": value,
        "currency": "EUR",
        "symbol": "AAA.XETRA",
        "run_date": "2026-01-04",
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
    assert row["distribution_frequency"] == "accumulating"
    assert row["distribution_events_per_year"] == 0.0
    assert row["last_distribution_date"] == ""
    assert row["distribution_observation_count"] == 0
    assert written == statistics
    assert read_rows(paths.gold_univariate_statistics("XETRA", "IE1")) == statistics


def test_univariate_statistics_reuses_cached_listing_artifacts(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-01-02", 110.0),
        _quote("2026-01-03", 120.0),
    ]
    dividends = [_dividend("2026-02-15")]

    first = write_univariate_statistics(
        paths,
        quotes,
        dividend_rows=dividends,
        confidence_level=0.75,
    )
    path = paths.gold_univariate_statistics("XETRA", "IE1")
    first_mtime = path.stat().st_mtime_ns

    second = write_univariate_statistics(
        paths,
        quotes,
        dividend_rows=dividends,
        confidence_level=0.75,
    )

    assert second == first
    assert path.stat().st_mtime_ns == first_mtime


def test_univariate_statistics_detect_monthly_distribution_frequency() -> None:
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-02-01", 101.0),
        _quote("2026-03-01", 102.0),
    ]
    dividends = [
        _dividend("2026-01-15"),
        _dividend("2026-02-15"),
        _dividend("2026-03-15"),
        _dividend("2026-04-15"),
    ]

    row = build_univariate_statistics(quotes, dividend_rows=dividends)[0]

    assert row["distribution_frequency"] == "monthly"
    assert row["distribution_events_per_year"] == pytest.approx(12.171, rel=0.001)
    assert row["last_distribution_date"] == "2026-04-15"
    assert row["distribution_observation_count"] == 4


@pytest.mark.parametrize(
    ("dividend_dates", "expected_frequency"),
    [
        (["2026-01-15"], "unknown"),
        (["2026-01-15", "2026-04-15", "2026-07-15"], "quarterly"),
        (["2026-01-15", "2026-07-15", "2027-01-15"], "semiannual"),
        (["2026-01-15", "2027-01-15", "2028-01-15"], "annual"),
        (["2026-01-15", "2026-03-01", "2027-01-15"], "irregular"),
    ],
)
def test_univariate_statistics_classify_distribution_frequency(
    dividend_dates: list[str],
    expected_frequency: str,
) -> None:
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-02-01", 101.0),
        _quote("2026-03-01", 102.0),
    ]

    row = build_univariate_statistics(
        quotes,
        dividend_rows=[_dividend(dividend_date) for dividend_date in dividend_dates],
    )[0]

    assert row["distribution_frequency"] == expected_frequency
    assert row["last_distribution_date"] == dividend_dates[-1]
    assert row["distribution_observation_count"] == len(dividend_dates)


def test_univariate_statistics_ignore_empty_and_zero_distribution_events() -> None:
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-02-01", 101.0),
        _quote("2026-03-01", 102.0),
    ]
    dividends = [
        _dividend(""),
        _dividend("2026-01-15", value=0.0),
        _dividend("2026-02-15"),
    ]

    row = build_univariate_statistics(quotes, dividend_rows=dividends)[0]

    assert row["distribution_frequency"] == "unknown"
    assert row["last_distribution_date"] == "2026-02-15"
    assert row["distribution_observation_count"] == 1


def test_univariate_statistics_quarantines_invalid_prices_instead_of_zero_return() -> None:
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-01-02", 0.0),
        _quote("2026-01-02", -5.0),
        _quote("2026-01-03", 110.0),
    ]

    returns = build_quote_returns(quotes)
    row = build_univariate_statistics(quotes)[0]

    assert [item["date"] for item in returns] == ["2026-01-03"]
    assert returns[0]["return"] != 0.0
    assert row["quarantined_price_count"] == 2
    assert row["non_positive_price_detected"] is True
    assert row["duplicate_date_detected"] is True
    assert row["production_eligible"] is False
    assert row["data_quality_reason"] == "non_positive_price"


def test_univariate_statistics_are_production_eligible_with_enough_clean_history() -> None:
    start = _date(2020, 1, 1)
    quotes = [
        _quote((start + timedelta(days=index)).isoformat(), 100.0 + index) for index in range(253)
    ]

    row = build_univariate_statistics(quotes)[0]

    assert row["return_observation_count"] == 252
    assert row["meets_min_history_252"] is True
    assert row["meets_min_history_504"] is False
    assert row["production_eligible"] is True
    assert row["data_quality_reason"] == "ok"


def test_univariate_statistics_parallel_matches_serial() -> None:
    quotes: list[dict[str, object]] = []
    for isin, exchange, code, base in (
        ("IE1", "XETRA", "AAA", 100.0),
        ("IE2", "AS", "BBB", 200.0),
    ):
        for index, date in enumerate(("2026-01-01", "2026-01-02", "2026-01-03")):
            row = _quote(date, base + float(index))
            row["isin"] = isin
            row["exchange"] = exchange
            row["code"] = code
            quotes.append(row)

    serial = build_univariate_statistics(quotes, concurrency=1)
    parallel = build_univariate_statistics(quotes, concurrency=2)

    assert parallel == serial


def test_univariate_statistics_reject_invalid_confidence_level() -> None:
    with pytest.raises(ValueError, match="confidence_level"):
        build_univariate_statistics([_quote("2026-01-01", 100.0)], confidence_level=1.0)
