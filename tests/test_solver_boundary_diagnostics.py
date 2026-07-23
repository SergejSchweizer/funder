"""Tests for the PR59 "No Silent Equal-Weight Fallback" and solver diagnostics amendment."""

from math import comb

import pytest

from camovar.portfolio import (
    BASELINE_SOLVER_MODE,
    CANDIDATE_LIMIT_EXCEEDED_REASON,
    EQUAL_WEIGHT_FALLBACK_METHOD,
    MAX_EXACT_WEIGHT_CANDIDATES,
    PRODUCTION_SOLVER_MODE,
    PortfolioConstraints,
    build_optimizer_diagnostics,
    exact_candidate_count,
    is_candidate_limit_exceeded,
    optimize_portfolio,
    resolve_actual_optimizer_method,
)

# 9 listings at grid_step=0.1 (steps=10): comb(9+10-1, 10) = 43758 > 20000.
_OVER_LIMIT_LISTINGS = [
    {"isin": f"IE{i}", "exchange": "XETRA", "code": f"ETF{i}"} for i in range(1, 10)
]
_OVER_LIMIT_GRID_STEP = 0.1


def _dense_covariance_rows(
    listings: list[dict[str, str]], *, diagonal: float = 0.01, off_diagonal: float = 0.0
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for left in listings:
        for right in listings:
            rows.append(
                {
                    "left_isin": left["isin"],
                    "left_exchange": left["exchange"],
                    "left_code": left["code"],
                    "right_isin": right["isin"],
                    "right_exchange": right["exchange"],
                    "right_code": right["code"],
                    "covariance": diagonal if left["isin"] == right["isin"] else off_diagonal,
                }
            )
    return rows


def test_exact_candidate_count_matches_stars_and_bars_formula() -> None:
    assert exact_candidate_count(2, 0.5) == comb(2 + 2 - 1, 2)
    assert exact_candidate_count(9, 0.1) == 43758


def test_exact_candidate_count_rejects_invalid_grid_step() -> None:
    with pytest.raises(ValueError, match="grid_step must be in"):
        exact_candidate_count(3, 0.0)
    with pytest.raises(ValueError, match="grid_step must divide 1"):
        exact_candidate_count(3, 0.3)


def test_is_candidate_limit_exceeded_matches_configured_threshold() -> None:
    assert is_candidate_limit_exceeded(len(_OVER_LIMIT_LISTINGS), _OVER_LIMIT_GRID_STEP) is True
    assert is_candidate_limit_exceeded(2, 0.5) is False
    assert exact_candidate_count(9, 0.1) > MAX_EXACT_WEIGHT_CANDIDATES


def test_resolve_actual_optimizer_method_is_pure_and_deterministic() -> None:
    # Equal Weight is always itself: an explicit baseline, never a hidden fallback.
    assert resolve_actual_optimizer_method("equal_weight", 9, 0.1) == "equal_weight"
    # A non-grid objective (e.g. hierarchical_risk_parity) has no candidate-limit concept.
    assert resolve_actual_optimizer_method("hierarchical_risk_parity", 9, 0.1) == (
        "hierarchical_risk_parity"
    )
    # Within the limit: requested method is genuinely executed.
    assert resolve_actual_optimizer_method("minimum_variance", 2, 0.5) == "minimum_variance"
    # Over the limit: the grid objective silently becomes an equal-weight fallback.
    assert (
        resolve_actual_optimizer_method("minimum_variance", 9, 0.1) == EQUAL_WEIGHT_FALLBACK_METHOD
    )


def test_resolve_actual_optimizer_method_is_not_fooled_by_a_genuine_equal_weight_optimum() -> None:
    # Unlike a weight-comparison heuristic, this pure function cannot mistake a
    # genuine minimum-variance optimum that happens to equal Equal Weight for a
    # candidate-limit fallback: it never inspects the resulting weights at all.
    assert resolve_actual_optimizer_method("minimum_variance", 2, 0.5) == "minimum_variance"


def test_optimize_portfolio_production_mode_rejects_candidate_limit_exceeded() -> None:
    # maximum_sharpe has no solver-backed production path yet (PR60 only wired
    # Minimum Variance and Equal Risk Contribution), so it still hits the
    # grid candidate-limit guard added in the PR59 amendment.
    with pytest.raises(ValueError, match=CANDIDATE_LIMIT_EXCEEDED_REASON):
        optimize_portfolio(
            _OVER_LIMIT_LISTINGS,
            _dense_covariance_rows(_OVER_LIMIT_LISTINGS),
            {row["isin"]: 0.01 for row in _OVER_LIMIT_LISTINGS},
            objective="maximum_sharpe",
            constraints=PortfolioConstraints(max_weight=0.5),
            grid_step=_OVER_LIMIT_GRID_STEP,
            mode=PRODUCTION_SOLVER_MODE,
        )


def test_optimize_portfolio_baseline_mode_still_returns_labeled_fallback_weights() -> None:
    weights = optimize_portfolio(
        _OVER_LIMIT_LISTINGS,
        _dense_covariance_rows(_OVER_LIMIT_LISTINGS),
        {row["isin"]: 0.01 for row in _OVER_LIMIT_LISTINGS},
        objective="minimum_variance",
        constraints=PortfolioConstraints(max_weight=0.5),
        grid_step=_OVER_LIMIT_GRID_STEP,
        mode=BASELINE_SOLVER_MODE,
    )

    assert set(weights) == {row["isin"] for row in _OVER_LIMIT_LISTINGS}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_optimize_portfolio_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown optimizer mode"):
        optimize_portfolio(
            _OVER_LIMIT_LISTINGS[:2],
            _dense_covariance_rows(_OVER_LIMIT_LISTINGS[:2]),
            {},
            objective="minimum_variance",
            constraints=PortfolioConstraints(max_weight=0.8),
            grid_step=0.1,
            mode="not_a_real_mode",
        )


def test_diagnostics_report_candidate_limit_fallback_and_block_production_eligibility() -> None:
    weights = optimize_portfolio(
        _OVER_LIMIT_LISTINGS,
        _dense_covariance_rows(_OVER_LIMIT_LISTINGS),
        {row["isin"]: 0.01 for row in _OVER_LIMIT_LISTINGS},
        objective="maximum_sharpe",
        constraints=PortfolioConstraints(max_weight=0.5),
        grid_step=_OVER_LIMIT_GRID_STEP,
        mode=BASELINE_SOLVER_MODE,
    )

    diagnostics = build_optimizer_diagnostics(
        _OVER_LIMIT_LISTINGS,
        _dense_covariance_rows(_OVER_LIMIT_LISTINGS),
        {row["isin"]: 0.01 for row in _OVER_LIMIT_LISTINGS},
        weights,
        objective="maximum_sharpe",
        constraints=PortfolioConstraints(max_weight=0.5),
        mode=PRODUCTION_SOLVER_MODE,
        grid_step=_OVER_LIMIT_GRID_STEP,
    )

    assert diagnostics["requested_method"] == "maximum_sharpe"
    assert diagnostics["actual_method"] == EQUAL_WEIGHT_FALLBACK_METHOD
    assert diagnostics["fallback_used"] is True
    assert diagnostics["fallback_reason"] == CANDIDATE_LIMIT_EXCEEDED_REASON
    assert diagnostics["solver_status"] == CANDIDATE_LIMIT_EXCEEDED_REASON
    assert diagnostics["optimizer_status"] == CANDIDATE_LIMIT_EXCEEDED_REASON
    assert diagnostics["production_eligible"] is False


def test_diagnostics_distinguish_explicit_equal_weight_from_a_hidden_fallback() -> None:
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.8)
    explicit_weights = optimize_portfolio(
        listings, covariance_rows, {}, objective="equal_weight", constraints=constraints
    )

    explicit_diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {},
        explicit_weights,
        objective="equal_weight",
        constraints=constraints,
        mode=PRODUCTION_SOLVER_MODE,
        grid_step=0.5,
    )
    fallback_diagnostics = build_optimizer_diagnostics(
        _OVER_LIMIT_LISTINGS,
        _dense_covariance_rows(_OVER_LIMIT_LISTINGS),
        {row["isin"]: 0.01 for row in _OVER_LIMIT_LISTINGS},
        optimize_portfolio(
            _OVER_LIMIT_LISTINGS,
            _dense_covariance_rows(_OVER_LIMIT_LISTINGS),
            {row["isin"]: 0.01 for row in _OVER_LIMIT_LISTINGS},
            objective="maximum_sharpe",
            constraints=PortfolioConstraints(max_weight=0.5),
            grid_step=_OVER_LIMIT_GRID_STEP,
        ),
        objective="maximum_sharpe",
        constraints=PortfolioConstraints(max_weight=0.5),
        mode=PRODUCTION_SOLVER_MODE,
        grid_step=_OVER_LIMIT_GRID_STEP,
    )

    assert (
        explicit_diagnostics["requested_method"]
        == explicit_diagnostics["actual_method"]
        == ("equal_weight")
    )
    assert explicit_diagnostics["fallback_used"] is False
    assert explicit_diagnostics["production_eligible"] is True

    assert fallback_diagnostics["requested_method"] != fallback_diagnostics["actual_method"]
    assert fallback_diagnostics["fallback_used"] is True
    assert fallback_diagnostics["production_eligible"] is False


def test_diagnostics_report_production_eligible_only_in_production_mode() -> None:
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.8)
    weights = optimize_portfolio(
        listings,
        covariance_rows,
        {"IE1": 0.01, "IE2": 0.02},
        objective="minimum_variance",
        constraints=constraints,
        grid_step=0.5,
    )

    baseline_diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {"IE1": 0.01, "IE2": 0.02},
        weights,
        objective="minimum_variance",
        constraints=constraints,
        mode=BASELINE_SOLVER_MODE,
        grid_step=0.5,
    )
    production_diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {"IE1": 0.01, "IE2": 0.02},
        weights,
        objective="minimum_variance",
        constraints=constraints,
        mode=PRODUCTION_SOLVER_MODE,
        grid_step=0.5,
    )

    assert baseline_diagnostics["fallback_used"] is False
    assert baseline_diagnostics["production_eligible"] is False
    assert production_diagnostics["production_eligible"] is True


def test_diagnostics_report_bound_activity_and_constraint_residuals() -> None:
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.6, min_weight=0.1)
    weights = {"IE1": 0.6, "IE2": 0.4}

    diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {},
        weights,
        objective="equal_weight",
        constraints=constraints,
        grid_step=0.5,
    )

    assert diagnostics["bound_activity"] == ["IE1:max_weight"]
    assert diagnostics["constraint_residuals"] == [0.0, 0.0]
    assert diagnostics["numeric_tolerances"]["grid_step"] == 0.5


def test_diagnostics_default_iteration_count_reflects_grid_size_when_not_fallen_back() -> None:
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.8)
    weights = {"IE1": 0.5, "IE2": 0.5}

    diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {},
        weights,
        objective="minimum_variance",
        constraints=constraints,
        grid_step=0.5,
    )

    assert diagnostics["iteration_count"] == exact_candidate_count(2, 0.5)


def test_diagnostics_solver_status_and_risk_model_id_default() -> None:
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.8)
    weights = {"IE1": 0.5, "IE2": 0.5}

    diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {},
        weights,
        objective="minimum_variance",
        constraints=constraints,
    )

    assert diagnostics["risk_model_id"] == ""
    assert diagnostics["solver_status"] == "feasible"
    assert diagnostics["convergence_status"] == "converged"
