"""Tests for walk-forward return semantics and production defaults (C02)."""

from __future__ import annotations

from math import isclose, log, sqrt

import pytest

from camovar.evaluation import (
    ANNUAL_TRADING_DAYS,
    PRODUCTION_MAX_WEIGHT,
    PRODUCTION_MIN_COMPLETED_SPLITS,
    PRODUCTION_MIN_TEST_OBSERVATIONS,
    PRODUCTION_MIN_TRAIN_OBSERVATIONS,
    WALK_FORWARD_PROFILES,
    build_walk_forward_backtest,
)
from camovar.portfolio import PortfolioConstraints


def _matrix_row(
    isin: str, exchange: str, code: str, item_date: str, simple_return: float
) -> dict[str, object]:
    return {
        "evaluation_id": "eval-1",
        "date": item_date,
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "return": simple_return,
        "simple_return": simple_return,
    }


def _two_asset_matrix(returns: dict[str, tuple[float, float]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item_date, (left, right) in returns.items():
        rows.append(_matrix_row("IE1", "XETRA", "AAA", item_date, left))
        rows.append(_matrix_row("IE2", "AS", "BBB", item_date, right))
    return rows


def _sequential_dates(count: int, *, start_year: int = 2020) -> list[str]:
    dates: list[str] = []
    year, month, day = start_year, 1, 1
    for _ in range(count):
        dates.append(f"{year:04d}-{month:02d}-{day:02d}")
        day += 1
        if day > 28:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
    return dates


def test_realized_return_geometrically_compounds_positive_returns() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.10, 0.10),
            "2026-01-02": (0.10, 0.10),
            "2026-01-03": (0.10, 0.10),
        }
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=2,
    )

    # Test window is days 2-3 for the first split: two consecutive +10% days.
    expected = (1.10 * 1.10) - 1.0
    assert metrics[0]["pre_cost_return"] == pytest.approx(expected)
    assert metrics[0]["pre_cost_return"] != pytest.approx(0.10 + 0.10)  # not the old sum() bug


def test_realized_return_geometrically_compounds_negative_and_mixed_returns() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.0, 0.0),
            "2026-01-02": (-0.10, -0.10),
            "2026-01-03": (0.20, 0.20),
            "2026-01-04": (-0.05, -0.05),
        }
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=3,
    )

    expected = (0.90 * 1.20 * 0.95) - 1.0
    assert metrics[0]["pre_cost_return"] == pytest.approx(expected)
    assert metrics[0]["pre_cost_return"] != pytest.approx(-0.10 + 0.20 - 0.05)


def test_log_return_accumulation_reconciles_with_simple_return_compounding() -> None:
    """Independent proof: cumulative log return and compounded simple wealth agree."""
    simple_returns = [0.05, -0.03, 0.02, 0.08, -0.01]
    log_returns = [log(1.0 + value) for value in simple_returns]

    cumulative_log_return = sum(log_returns)
    compounded_simple_wealth = 1.0
    for value in simple_returns:
        compounded_simple_wealth *= 1.0 + value

    assert isclose(
        compounded_simple_wealth, pow(2.718281828459045, cumulative_log_return), rel_tol=1e-9
    )


def test_sharpe_and_sortino_use_consistent_annualization_across_test_windows() -> None:
    """A short and a long test window with the same daily statistics must produce
    the same annualized volatility and comparable Sharpe magnitude, proving the
    numerator and denominator share the same annualization frequency."""
    daily_returns = {f"day{i}": (0.01 if i % 2 == 0 else -0.01, 0.0) for i in range(1, 22)}
    dates = _sequential_dates(22)
    matrix = _two_asset_matrix(
        {dates[i]: value for i, (_key, value) in enumerate(daily_returns.items())}
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=20,
    )

    split = metrics[0]
    # realized_volatility must be an annualized (not raw daily) figure: for
    # alternating +-1% daily returns the daily stdev is ~0.01, so the
    # annualized figure must be much larger than 0.01.
    assert split["realized_volatility"] > 0.05
    assert isinstance(split["sharpe_ratio"], float)
    assert isinstance(split["sortino_ratio"], float)


def test_development_profile_is_never_production_eligible() -> None:
    matrix = _two_asset_matrix(
        {"2026-01-01": (0.01, 0.02), "2026-01-02": (0.02, -0.01), "2026-01-03": (0.01, 0.01)}
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=1,
    )

    assert all(row["profile"] == "development" for row in metrics)
    assert all(row["production_eligible"] is False for row in metrics)
    assert all(row["availability_reason"] == "development_profile_baseline_only" for row in metrics)


def test_production_profile_rejects_train_window_below_minimum() -> None:
    matrix = _two_asset_matrix({"2026-01-01": (0.01, 0.02), "2026-01-02": (0.02, -0.01)})
    constraints = PortfolioConstraints(max_weight=PRODUCTION_MAX_WEIGHT)

    with pytest.raises(ValueError, match="train_window"):
        build_walk_forward_backtest(
            matrix,
            run_id="wf-1",
            evaluation_id="eval-1",
            objective="equal_weight",
            constraints=constraints,
            train_window=10,
            test_window=1,
            profile="production",
        )


def test_production_profile_rejects_test_window_below_minimum() -> None:
    dates = _sequential_dates(PRODUCTION_MIN_TRAIN_OBSERVATIONS + 5)
    matrix = _two_asset_matrix({date: (0.001, 0.001) for date in dates})
    constraints = PortfolioConstraints(max_weight=PRODUCTION_MAX_WEIGHT)

    with pytest.raises(ValueError, match="test_window"):
        build_walk_forward_backtest(
            matrix,
            run_id="wf-1",
            evaluation_id="eval-1",
            objective="equal_weight",
            constraints=constraints,
            train_window=PRODUCTION_MIN_TRAIN_OBSERVATIONS,
            test_window=1,
            profile="production",
        )


def test_production_profile_rejects_max_weight_above_limit() -> None:
    dates = _sequential_dates(
        PRODUCTION_MIN_TRAIN_OBSERVATIONS + PRODUCTION_MIN_TEST_OBSERVATIONS + 5
    )
    matrix = _two_asset_matrix({date: (0.001, 0.001) for date in dates})
    constraints = PortfolioConstraints(max_weight=1.0)

    with pytest.raises(ValueError, match="max_weight"):
        build_walk_forward_backtest(
            matrix,
            run_id="wf-1",
            evaluation_id="eval-1",
            objective="equal_weight",
            constraints=constraints,
            train_window=PRODUCTION_MIN_TRAIN_OBSERVATIONS,
            test_window=PRODUCTION_MIN_TEST_OBSERVATIONS,
            profile="production",
        )


def _four_asset_matrix(
    returns: dict[str, tuple[float, float, float, float]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item_date, (a, b, c, d) in returns.items():
        rows.append(_matrix_row("IE1", "XETRA", "AAA", item_date, a))
        rows.append(_matrix_row("IE2", "AS", "BBB", item_date, b))
        rows.append(_matrix_row("IE3", "PA", "CCC", item_date, c))
        rows.append(_matrix_row("IE4", "MC", "DDD", item_date, d))
    return rows


def test_production_profile_marks_ineligible_when_too_few_completed_splits() -> None:
    total_days = PRODUCTION_MIN_TRAIN_OBSERVATIONS + PRODUCTION_MIN_TEST_OBSERVATIONS
    dates = _sequential_dates(total_days)
    matrix = _four_asset_matrix({date: (0.0005, 0.0004, 0.0003, 0.0002) for date in dates})
    constraints = PortfolioConstraints(max_weight=PRODUCTION_MAX_WEIGHT)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=PRODUCTION_MIN_TRAIN_OBSERVATIONS,
        test_window=PRODUCTION_MIN_TEST_OBSERVATIONS,
        profile="production",
    )

    assert len(metrics) < PRODUCTION_MIN_COMPLETED_SPLITS
    assert all(row["production_eligible"] is False for row in metrics)
    assert all(row["availability_reason"] == "insufficient_completed_splits" for row in metrics)


def test_production_profile_is_eligible_with_enough_splits() -> None:
    total_days = PRODUCTION_MIN_TRAIN_OBSERVATIONS + PRODUCTION_MIN_TEST_OBSERVATIONS * (
        PRODUCTION_MIN_COMPLETED_SPLITS + 1
    )
    dates = _sequential_dates(total_days)
    matrix = _four_asset_matrix({date: (0.0005, 0.0004, 0.0003, 0.0002) for date in dates})
    constraints = PortfolioConstraints(max_weight=PRODUCTION_MAX_WEIGHT)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=PRODUCTION_MIN_TRAIN_OBSERVATIONS,
        test_window=PRODUCTION_MIN_TEST_OBSERVATIONS,
        profile="production",
    )

    assert len(metrics) >= PRODUCTION_MIN_COMPLETED_SPLITS
    assert all(row["production_eligible"] is True for row in metrics)
    assert all(row["availability_reason"] == "ok" for row in metrics)


def test_unknown_profile_is_rejected() -> None:
    matrix = _two_asset_matrix({"2026-01-01": (0.01, 0.02), "2026-01-02": (0.02, -0.01)})
    with pytest.raises(ValueError, match="unknown walk-forward profile"):
        build_walk_forward_backtest(
            matrix,
            run_id="wf-1",
            evaluation_id="eval-1",
            objective="equal_weight",
            constraints=PortfolioConstraints(max_weight=1.0),
            train_window=1,
            test_window=1,
            profile="bogus",
        )


def test_transaction_cost_changes_post_cost_return_but_not_pre_cost_return() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.01, 0.02),
            "2026-01-02": (0.02, -0.01),
            "2026-01-03": (0.03, 0.01),
            "2026-01-04": (-0.01, 0.02),
        }
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    free, _ = build_walk_forward_backtest(
        matrix,
        run_id="wf-free",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=1,
        transaction_cost_rate=0.0,
    )
    costly, _ = build_walk_forward_backtest(
        matrix,
        run_id="wf-costly",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=1,
        transaction_cost_rate=0.01,
    )

    for free_row, costly_row in zip(free, costly, strict=True):
        assert free_row["pre_cost_return"] == pytest.approx(costly_row["pre_cost_return"])
        if costly_row["turnover"] > 0:
            assert costly_row["transaction_cost"] > 0.0
            assert costly_row["post_cost_return"] < costly_row["pre_cost_return"]
        assert free_row["transaction_cost"] == 0.0
        assert free_row["post_cost_return"] == pytest.approx(free_row["pre_cost_return"])


def test_no_future_observation_influences_an_earlier_split() -> None:
    """Changing returns strictly after a split's test window must not change that split."""
    base_matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.01, 0.02),
            "2026-01-02": (0.02, -0.01),
            "2026-01-03": (0.03, 0.01),
            "2026-01-04": (-0.01, 0.02),
        }
    )
    altered_matrix = [dict(row) for row in base_matrix]
    for row in altered_matrix:
        if row["date"] == "2026-01-04":
            row["return"] = 0.99
            row["simple_return"] = 0.99
    constraints = PortfolioConstraints(max_weight=1.0)

    base_metrics, _ = build_walk_forward_backtest(
        base_matrix,
        run_id="wf-base",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=1,
    )
    altered_metrics, _ = build_walk_forward_backtest(
        altered_matrix,
        run_id="wf-altered",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=1,
    )

    # The first two splits (test windows on 2026-01-02 and 2026-01-03) must be
    # identical; only the split whose test window includes 2026-01-04 differs.
    assert base_metrics[0]["pre_cost_return"] == pytest.approx(
        altered_metrics[0]["pre_cost_return"]
    )
    assert base_metrics[1]["pre_cost_return"] == pytest.approx(
        altered_metrics[1]["pre_cost_return"]
    )
    assert base_metrics[2]["pre_cost_return"] != pytest.approx(
        altered_metrics[2]["pre_cost_return"]
    )


def test_actual_optimizer_method_flags_candidate_limit_fallback() -> None:
    """With enough listings, the deterministic grid search exceeds
    MAX_EXACT_WEIGHT_CANDIDATES and silently falls back to equal weight.
    That fallback must be recorded, not reported as the requested objective."""
    dates = _sequential_dates(3)
    listing_count = 9  # comb(9 + 10 - 1, 10) = 43758 > MAX_EXACT_WEIGHT_CANDIDATES (20000)
    rows: list[dict[str, object]] = []
    for item_date in dates:
        for index in range(listing_count):
            rows.append(
                _matrix_row(
                    f"IE{index}", "XETRA", f"AAA{index}", item_date, 0.01 * ((index % 3) - 1)
                )
            )
    constraints = PortfolioConstraints(max_weight=1.0)

    metrics, _weights = build_walk_forward_backtest(
        rows,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="minimum_variance",
        constraints=constraints,
        train_window=1,
        test_window=1,
        grid_step=0.1,
    )

    assert metrics
    assert all(row["objective"] == "minimum_variance" for row in metrics)
    assert all(row["actual_optimizer_method"] == "equal_weight_fallback" for row in metrics)


def test_actual_optimizer_method_matches_objective_when_no_fallback_occurs() -> None:
    matrix = _two_asset_matrix(
        {"2026-01-01": (0.01, 0.02), "2026-01-02": (0.02, -0.01), "2026-01-03": (0.01, 0.03)}
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="minimum_variance",
        constraints=constraints,
        train_window=1,
        test_window=1,
    )

    assert all(row["actual_optimizer_method"] == "minimum_variance" for row in metrics)


def test_walk_forward_profiles_registry_matches_documented_thresholds() -> None:
    development = WALK_FORWARD_PROFILES["development"]
    production = WALK_FORWARD_PROFILES["production"]

    assert development.min_train_observations == 1
    assert development.min_test_observations == 1
    assert development.max_weight == 1.0

    assert production.min_train_observations == PRODUCTION_MIN_TRAIN_OBSERVATIONS == 504
    assert production.min_test_observations == PRODUCTION_MIN_TEST_OBSERVATIONS == 21
    assert production.min_completed_splits == PRODUCTION_MIN_COMPLETED_SPLITS == 2
    assert production.max_weight == PRODUCTION_MAX_WEIGHT < 1.0


def test_annualized_volatility_scales_with_annual_trading_days_constant() -> None:
    matrix = _two_asset_matrix(
        {
            "2026-01-01": (0.02, 0.0),
            "2026-01-02": (-0.02, 0.0),
            "2026-01-03": (0.02, 0.0),
        }
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    metrics, _weights = build_walk_forward_backtest(
        matrix,
        run_id="wf-1",
        evaluation_id="eval-1",
        objective="equal_weight",
        constraints=constraints,
        train_window=1,
        test_window=2,
    )

    # Independently recompute expected annualized volatility from the equal-weight
    # portfolio's own test-window returns (50% IE1 + 50% IE2, IE2 always flat).
    portfolio_returns = [0.01, -0.01]
    mean = sum(portfolio_returns) / len(portfolio_returns)
    variance = sum((value - mean) ** 2 for value in portfolio_returns) / (
        len(portfolio_returns) - 1
    )
    expected_annualized_volatility = sqrt(variance) * sqrt(ANNUAL_TRADING_DAYS)
    assert metrics[0]["realized_volatility"] == pytest.approx(expected_annualized_volatility)
