"""Tests for the shared return-type and price-quality gate."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from camovar.return_quality import (
    MIN_HISTORY_LONG,
    MIN_HISTORY_MEDIUM,
    MIN_HISTORY_SHORT,
    detect_stale_price_run,
    detect_unexplained_gap,
    evaluate_quote_quality,
    filter_valid_price_points,
    meets_minimum_observations,
)


def _quote(quote_date: str, adjusted_close: float) -> dict[str, object]:
    return {"date": quote_date, "adjusted_close": adjusted_close}


def _daily_series(count: int, *, start: str = "2020-01-01") -> list[dict[str, object]]:
    start_date = date.fromisoformat(start)
    rows: list[dict[str, object]] = []
    for index in range(count):
        current_date = start_date + timedelta(days=index)
        price = 100.0 + (index % 3) - 1.0
        rows.append(_quote(current_date.isoformat(), price))
    return rows


def test_filter_valid_price_points_quarantines_non_positive_prices() -> None:
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-01-02", 0.0),
        _quote("2026-01-03", -5.0),
        _quote("2026-01-04", 101.0),
    ]

    valid, quarantined = filter_valid_price_points(quotes)

    assert [row["date"] for row in valid] == ["2026-01-01", "2026-01-04"]
    assert [row["quarantine_reason"] for row in quarantined] == [
        "non_positive_price",
        "non_positive_price",
    ]


def test_filter_valid_price_points_quarantines_duplicate_and_corrected_dates() -> None:
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-01-02", 101.0),
        _quote("2026-01-02", 999.0),  # a later correction for the same date
        _quote("2026-01-03", 102.0),
    ]

    valid, quarantined = filter_valid_price_points(quotes)

    assert [row["date"] for row in valid] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert [row["adjusted_close"] for row in valid] == [100.0, 101.0, 102.0]
    assert quarantined == [
        {
            "date": "2026-01-02",
            "adjusted_close": 999.0,
            "quarantine_reason": "duplicate_date",
        }
    ]


def test_detect_stale_price_run_flags_repeated_prices() -> None:
    stale = [_quote(f"2026-01-{day:02d}", 100.0) for day in range(1, 6)]
    fresh = [_quote(f"2026-01-{day:02d}", 100.0 + day) for day in range(1, 6)]

    assert detect_stale_price_run(stale) is True
    assert detect_stale_price_run(fresh) is False
    assert detect_stale_price_run(stale[:4]) is False


def test_detect_unexplained_gap_flags_long_calendar_gaps() -> None:
    weekend_gap = [_quote("2026-01-02", 100.0), _quote("2026-01-05", 101.0)]
    long_gap = [_quote("2026-01-02", 100.0), _quote("2026-01-20", 101.0)]

    assert detect_unexplained_gap(weekend_gap) is False
    assert detect_unexplained_gap(long_gap) is True


def test_evaluate_quote_quality_reports_ok_when_history_and_prices_are_clean() -> None:
    quotes = _daily_series(MIN_HISTORY_SHORT + 1)

    quality = evaluate_quote_quality(quotes)

    assert quality["meets_min_history_252"] is True
    assert quality["meets_min_history_504"] is False
    assert quality["meets_min_history_756"] is False
    assert quality["production_eligible"] is True
    assert quality["data_quality_reason"] == "ok"
    assert quality["quarantined_price_count"] == 0


def test_evaluate_quote_quality_reports_insufficient_history() -> None:
    quotes = _daily_series(10)

    quality = evaluate_quote_quality(quotes)

    assert quality["meets_min_history_252"] is False
    assert quality["production_eligible"] is False
    assert quality["data_quality_reason"] == "insufficient_history"


def test_evaluate_quote_quality_meets_medium_and_long_thresholds() -> None:
    medium = evaluate_quote_quality(_daily_series(MIN_HISTORY_MEDIUM + 1))
    long_history = evaluate_quote_quality(_daily_series(MIN_HISTORY_LONG + 1))

    assert medium["meets_min_history_504"] is True
    assert medium["meets_min_history_756"] is False
    assert long_history["meets_min_history_756"] is True


def test_evaluate_quote_quality_detects_every_issue_and_prioritizes_reason() -> None:
    quotes = [
        _quote("2026-01-01", 100.0),
        _quote("2026-01-02", -1.0),  # non-positive, quarantined
        _quote("2026-01-02", 105.0),  # duplicate date, quarantined
        _quote("2026-01-03", 100.0),
        _quote("2026-01-04", 100.0),
        _quote("2026-01-05", 100.0),
        _quote("2026-01-06", 100.0),
        _quote("2026-01-07", 100.0),  # 5+ repeats: stale price
        _quote("2026-02-01", 110.0),  # unexplained gap
    ]

    quality = evaluate_quote_quality(quotes)

    assert quality["non_positive_price_detected"] is True
    assert quality["duplicate_date_detected"] is True
    assert quality["stale_price_detected"] is True
    assert quality["unexplained_gap_detected"] is True
    assert quality["production_eligible"] is False
    assert quality["data_quality_reason"] == "non_positive_price"


def test_meets_minimum_observations_uses_explicit_threshold() -> None:
    assert meets_minimum_observations(504, threshold=MIN_HISTORY_MEDIUM) is True
    assert meets_minimum_observations(503, threshold=MIN_HISTORY_MEDIUM) is False
    assert meets_minimum_observations(MIN_HISTORY_SHORT) is True


@pytest.mark.parametrize("count", [0, 1])
def test_filter_valid_price_points_handles_empty_and_single_row(count: int) -> None:
    quotes = _daily_series(count)

    valid, quarantined = filter_valid_price_points(quotes)

    assert len(valid) == count
    assert quarantined == []
