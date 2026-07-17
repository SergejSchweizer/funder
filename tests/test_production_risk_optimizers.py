"""Tests for PR60's solver-backed production Minimum Variance / Equal Risk
Contribution wiring in founder.portfolio (optimize_portfolio / build_optimizer_diagnostics).
"""

from math import comb

import pytest

from founder.portfolio import (
    PRODUCTION_SOLVER_MODE,
    PortfolioConstraints,
    build_optimizer_diagnostics,
    optimize_portfolio,
)
from founder.portfolio_parts.solvers import SOLVER_NAME, SolverOutcome

# 9 listings at grid_step=0.1: comb(9+10-1, 10) = 43758 > MAX_EXACT_WEIGHT_CANDIDATES.
# Minimum Variance / Equal Risk Contribution must no longer be limited by this
# in production mode now that a real solver exists for them (PR60).
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


def test_theoretical_grid_for_over_limit_fixture_actually_exceeds_the_limit() -> None:
    assert comb(len(_OVER_LIMIT_LISTINGS) + 10 - 1, 10) == 43758


@pytest.mark.parametrize(
    "objective", ["minimum_variance", "risk_parity", "equal_risk_contribution"]
)
def test_production_mode_no_longer_limited_by_grid_size_for_solver_backed_objectives(
    objective: str,
) -> None:
    weights = optimize_portfolio(
        _OVER_LIMIT_LISTINGS,
        _dense_covariance_rows(_OVER_LIMIT_LISTINGS),
        {row["isin"]: 0.01 for row in _OVER_LIMIT_LISTINGS},
        objective=objective,
        constraints=PortfolioConstraints(max_weight=0.5),
        grid_step=_OVER_LIMIT_GRID_STEP,
        mode=PRODUCTION_SOLVER_MODE,
    )

    assert set(weights) == {row["isin"] for row in _OVER_LIMIT_LISTINGS}
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(0.0 - 1e-9 <= value <= 0.5 + 1e-9 for value in weights.values())


@pytest.mark.parametrize("objective", ["minimum_variance", "risk_parity"])
def test_production_diagnostics_report_solver_name_and_convergence(objective: str) -> None:
    listings = _OVER_LIMIT_LISTINGS
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.5)
    weights = optimize_portfolio(
        listings,
        covariance_rows,
        {row["isin"]: 0.01 for row in listings},
        objective=objective,
        constraints=constraints,
        grid_step=_OVER_LIMIT_GRID_STEP,
        mode=PRODUCTION_SOLVER_MODE,
    )

    diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {row["isin"]: 0.01 for row in listings},
        weights,
        objective=objective,
        constraints=constraints,
        mode=PRODUCTION_SOLVER_MODE,
        grid_step=_OVER_LIMIT_GRID_STEP,
    )

    assert diagnostics["solver_name"] == SOLVER_NAME
    assert diagnostics["requested_method"] == diagnostics["actual_method"] == objective
    assert diagnostics["fallback_used"] is False
    assert diagnostics["convergence_status"] == "converged"
    assert diagnostics["solver_status"] == "feasible"
    assert diagnostics["production_eligible"] is True
    assert diagnostics["iteration_count"] > 0


def test_diagnostics_never_claim_solver_provenance_for_mismatched_weights() -> None:
    # Weights that were not actually produced by the solver (e.g. a
    # hand-crafted or baseline result) must not be reported as a converged,
    # production-eligible solver result just because a solver run happens to
    # exist for this objective.
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.8)
    mismatched_weights = {"IE1": 0.9, "IE2": 0.1}  # not the true minimum-variance solution

    diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {},
        mismatched_weights,
        objective="minimum_variance",
        constraints=constraints,
        mode=PRODUCTION_SOLVER_MODE,
        grid_step=0.1,
    )

    assert diagnostics["solver_name"] != SOLVER_NAME


def test_production_diagnostics_report_solver_not_converged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.8)
    stub_weights = (0.5, 0.5)

    def _fake_solver(*_args: object, **_kwargs: object) -> SolverOutcome:
        return SolverOutcome(
            weights=stub_weights, converged=False, iteration_count=1, objective_value=1.0
        )

    monkeypatch.setattr("founder.portfolio.solve_minimum_variance", _fake_solver)

    weights = {"IE1": 0.5, "IE2": 0.5}
    diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {},
        weights,
        objective="minimum_variance",
        constraints=constraints,
        mode=PRODUCTION_SOLVER_MODE,
        grid_step=0.1,
    )

    assert diagnostics["solver_status"] == "solver_not_converged"
    assert diagnostics["convergence_status"] == "not_converged"
    assert diagnostics["production_eligible"] is False


def test_optimize_portfolio_raises_when_production_solver_does_not_converge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listings = _OVER_LIMIT_LISTINGS[:2]
    covariance_rows = _dense_covariance_rows(listings)
    constraints = PortfolioConstraints(max_weight=0.8)

    def _fake_solver(*_args: object, **_kwargs: object) -> SolverOutcome:
        return SolverOutcome(
            weights=(0.5, 0.5), converged=False, iteration_count=1, objective_value=1.0
        )

    monkeypatch.setattr("founder.portfolio.solve_minimum_variance", _fake_solver)

    with pytest.raises(ValueError, match="solver_not_converged"):
        optimize_portfolio(
            listings,
            covariance_rows,
            {},
            objective="minimum_variance",
            constraints=constraints,
            grid_step=0.1,
            mode=PRODUCTION_SOLVER_MODE,
        )
