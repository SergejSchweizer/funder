"""Tests for the PR58 "Missing Covariance Is Not Zero" amendment.

Portfolio variance, marginal risk, diversification, and risk-parity math must
never silently substitute zero for an absent or non-finite covariance
element. These tests prove the production entry points fail closed instead.
"""

from math import isnan, nan

import pytest

from founder.portfolio import (
    PortfolioConstraints,
    build_diversification_metric_rows,
    build_optimizer_diagnostics,
    build_risk_contribution_rows,
    hierarchical_risk_parity_weights,
    optimize_portfolio,
    require_complete_covariance,
)

_LISTINGS = [
    {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
    {"isin": "IE2", "exchange": "AS", "code": "BBB"},
]


def _covariance_row(left: str, right: str, value: float) -> dict[str, object]:
    left_row = next(row for row in _LISTINGS if row["isin"] == left)
    right_row = next(row for row in _LISTINGS if row["isin"] == right)
    return {
        "left_isin": left_row["isin"],
        "left_exchange": left_row["exchange"],
        "left_code": left_row["code"],
        "right_isin": right_row["isin"],
        "right_exchange": right_row["exchange"],
        "right_code": right_row["code"],
        "covariance": value,
    }


def _complete_rows(off_diagonal: float = 0.02) -> list[dict[str, object]]:
    return [
        _covariance_row("IE1", "IE1", 0.01),
        _covariance_row("IE1", "IE2", off_diagonal),
        _covariance_row("IE2", "IE1", off_diagonal),
        _covariance_row("IE2", "IE2", 0.04),
    ]


def _missing_right_variance_rows() -> list[dict[str, object]]:
    # IE2's own variance ((IE2, IE2)) is absent -- a realistic gap where a
    # pairwise builder skipped a listing rather than reporting one value.
    return [
        _covariance_row("IE1", "IE1", 0.01),
        _covariance_row("IE1", "IE2", 0.02),
        _covariance_row("IE2", "IE1", 0.02),
    ]


def _non_finite_rows() -> list[dict[str, object]]:
    rows = _complete_rows()
    rows[1]["covariance"] = nan
    rows[2]["covariance"] = nan
    return rows


@pytest.mark.parametrize(
    "objective",
    ["minimum_variance", "maximum_sharpe", "risk_parity", "maximum_diversification"],
)
def test_optimize_portfolio_fails_closed_on_missing_covariance(objective: str) -> None:
    with pytest.raises(ValueError, match="incomplete covariance matrix"):
        optimize_portfolio(
            _LISTINGS,
            _missing_right_variance_rows(),
            {"IE1": 0.01, "IE2": 0.02},
            objective=objective,
            constraints=PortfolioConstraints(max_weight=0.8),
            grid_step=0.1,
        )


def test_optimize_portfolio_fails_closed_on_non_finite_covariance() -> None:
    with pytest.raises(ValueError, match="non-finite value"):
        optimize_portfolio(
            _LISTINGS,
            _non_finite_rows(),
            {"IE1": 0.01, "IE2": 0.02},
            objective="minimum_variance",
            constraints=PortfolioConstraints(max_weight=0.8),
            grid_step=0.1,
        )


def test_optimize_portfolio_succeeds_with_complete_covariance() -> None:
    weights = optimize_portfolio(
        _LISTINGS,
        _complete_rows(),
        {"IE1": 0.01, "IE2": 0.02},
        objective="minimum_variance",
        constraints=PortfolioConstraints(max_weight=0.8),
        grid_step=0.1,
    )

    assert set(weights) == {"IE1", "IE2"}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_hierarchical_risk_parity_fails_closed_on_missing_covariance() -> None:
    with pytest.raises(ValueError, match="incomplete covariance matrix"):
        hierarchical_risk_parity_weights(
            _LISTINGS,
            _missing_right_variance_rows(),
            PortfolioConstraints(max_weight=0.8),
        )


def test_diversification_metrics_fail_closed_on_missing_covariance() -> None:
    with pytest.raises(ValueError, match="incomplete covariance matrix"):
        build_diversification_metric_rows(
            _LISTINGS,
            _missing_right_variance_rows(),
            {"IE1": 0.5, "IE2": 0.5},
            evaluation_id="eval-1",
            portfolio_id="max-div",
        )


def test_risk_contribution_rows_fail_closed_on_missing_covariance() -> None:
    with pytest.raises(ValueError, match="incomplete covariance matrix"):
        build_risk_contribution_rows(
            _LISTINGS,
            _missing_right_variance_rows(),
            {"IE1": 0.5, "IE2": 0.5},
            evaluation_id="eval-1",
            objective="risk_parity",
            portfolio_id="rp-1",
        )


def test_optimizer_diagnostics_reports_blocked_status_without_raising() -> None:
    diagnostics = build_optimizer_diagnostics(
        _LISTINGS,
        _missing_right_variance_rows(),
        {"IE1": 0.01, "IE2": 0.02},
        {"IE1": 0.5, "IE2": 0.5},
        objective="minimum_variance",
        constraints=PortfolioConstraints(max_weight=0.8),
    )

    assert diagnostics["optimizer_status"] == "blocked_missing_covariance"
    assert diagnostics["covariance_condition"] == "missing_covariance"
    assert diagnostics["missing_covariance_count"] == 1
    assert isnan(diagnostics["portfolio_variance"])
    assert isnan(diagnostics["objective_value"])


def test_optimizer_diagnostics_reports_non_finite_covariance_condition() -> None:
    diagnostics = build_optimizer_diagnostics(
        _LISTINGS,
        _non_finite_rows(),
        {"IE1": 0.01, "IE2": 0.02},
        {"IE1": 0.5, "IE2": 0.5},
        objective="minimum_variance",
        constraints=PortfolioConstraints(max_weight=0.8),
    )

    assert diagnostics["optimizer_status"] == "blocked_missing_covariance"
    assert diagnostics["covariance_condition"] == "non_finite_covariance"


def test_optimizer_diagnostics_reports_ok_for_complete_covariance() -> None:
    diagnostics = build_optimizer_diagnostics(
        _LISTINGS,
        _complete_rows(),
        {"IE1": 0.01, "IE2": 0.02},
        {"IE1": 0.5, "IE2": 0.5},
        objective="minimum_variance",
        constraints=PortfolioConstraints(max_weight=0.8),
    )

    assert diagnostics["optimizer_status"] == "feasible"
    assert diagnostics["covariance_condition"] == "ok"
    assert diagnostics["missing_covariance_count"] == 0
    assert diagnostics["portfolio_variance"] == pytest.approx(0.5 * 0.5 * (0.01 + 0.04 + 2 * 0.02))


def test_missing_covariance_never_silently_understates_variance() -> None:
    # With the pre-amendment `.get(key, 0.0)` fallback, the missing (IE2, IE2)
    # variance term would default to 0.0, understating true portfolio
    # variance instead of failing. Prove the fixture is rejected outright.
    complete_variance = 0.5 * 0.5 * (0.01 + 0.04 + 2 * 0.02)
    assert complete_variance > 0.0

    with pytest.raises(ValueError, match="incomplete covariance matrix"):
        require_complete_covariance(
            [("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")],
            {
                (("IE1", "XETRA", "AAA"), ("IE1", "XETRA", "AAA")): 0.01,
                (("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")): 0.02,
                (("IE2", "AS", "BBB"), ("IE1", "XETRA", "AAA")): 0.02,
                # (IE2, IE2) intentionally absent.
            },
        )
