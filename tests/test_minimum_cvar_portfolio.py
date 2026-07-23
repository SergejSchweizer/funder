"""Tests for the PR61 Minimum CVaR wiring in camovar.portfolio."""

import random
from pathlib import Path

import pytest

from camovar.paths import LakePaths
from camovar.portfolio import (
    MINIMUM_CVAR_OBJECTIVE,
    PortfolioConstraints,
    build_minimum_cvar_diagnostics,
    minimum_cvar_weights,
    write_minimum_cvar_portfolio,
)
from camovar.table_io import read_rows, write_rows

_LISTINGS = [
    {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},  # fat-tailed
    {"isin": "IE2", "exchange": "AS", "code": "BBB"},  # steady
]


def _return_rows(seed: int = 1, count: int = 300) -> list[dict[str, object]]:
    random.seed(seed)
    rows: list[dict[str, object]] = []
    for day in range(count):
        date = f"2020-{1 + day // 28:02d}-{1 + day % 28:02d}"
        risky = random.gauss(0.0005, 0.01)
        if random.random() < 0.03:
            risky -= 0.08
        safe = random.gauss(0.0003, 0.004)
        rows.append(
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "date": date,
                "return": risky,
            }
        )
        rows.append(
            {
                "isin": "IE2",
                "exchange": "AS",
                "code": "BBB",
                "date": date,
                "return": safe,
            }
        )
    return rows


def test_minimum_cvar_weights_favor_lower_tail_risk_asset() -> None:
    constraints = PortfolioConstraints(max_weight=1.0)

    weights = minimum_cvar_weights(_LISTINGS, _return_rows(), constraints, confidence_level=0.95)

    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert weights["IE2"] > weights["IE1"]


def test_minimum_cvar_weights_respect_concentration_cap() -> None:
    constraints = PortfolioConstraints(max_weight=0.6)

    weights = minimum_cvar_weights(_LISTINGS, _return_rows(), constraints, confidence_level=0.95)

    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert all(value <= 0.6 + 1e-6 for value in weights.values())


def test_minimum_cvar_weights_rejects_invalid_confidence_level() -> None:
    constraints = PortfolioConstraints(max_weight=1.0)

    with pytest.raises(ValueError, match="confidence_level"):
        minimum_cvar_weights(_LISTINGS, _return_rows(), constraints, confidence_level=1.5)


def test_minimum_cvar_weights_rejects_insufficient_common_history() -> None:
    constraints = PortfolioConstraints(max_weight=1.0)
    sparse_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2020-01-01", "return": 0.01},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2020-02-01", "return": 0.02},
    ]

    with pytest.raises(ValueError, match="at least two common historical return observations"):
        minimum_cvar_weights(_LISTINGS, sparse_rows, constraints)


def test_build_minimum_cvar_diagnostics_reports_production_eligible_when_matched() -> None:
    constraints = PortfolioConstraints(max_weight=1.0)
    return_rows = _return_rows()
    weights = minimum_cvar_weights(_LISTINGS, return_rows, constraints, confidence_level=0.95)

    diagnostics = build_minimum_cvar_diagnostics(
        _LISTINGS, return_rows, weights, constraints=constraints, confidence_level=0.95
    )

    assert diagnostics["requested_method"] == MINIMUM_CVAR_OBJECTIVE
    assert diagnostics["actual_method"] == MINIMUM_CVAR_OBJECTIVE
    assert diagnostics["solver_status"] == "feasible"
    assert diagnostics["convergence_status"] == "converged"
    assert diagnostics["production_eligible"] is True
    assert diagnostics["confidence_level"] == 0.95
    assert diagnostics["cvar"] >= diagnostics["var"]


def test_build_minimum_cvar_diagnostics_never_claims_solver_provenance_for_mismatched_weights() -> (
    None
):
    constraints = PortfolioConstraints(max_weight=1.0)
    return_rows = _return_rows()
    mismatched_weights = {"IE1": 0.5, "IE2": 0.5}

    diagnostics = build_minimum_cvar_diagnostics(
        _LISTINGS, return_rows, mismatched_weights, constraints=constraints, confidence_level=0.95
    )

    assert diagnostics["solver_status"] == "unverified"
    assert diagnostics["production_eligible"] is False


def test_write_minimum_cvar_portfolio_persists_weights_and_diagnostics(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    return_rows = _return_rows()
    write_rows(
        paths.gold_return_matrix("eval-1"),
        [
            {
                "evaluation_id": "eval-1",
                "date": row["date"],
                "isin": row["isin"],
                "exchange": row["exchange"],
                "code": row["code"],
                "return": row["return"],
            }
            for row in return_rows
        ],
    )
    constraints = PortfolioConstraints(max_weight=1.0)

    weight_rows = write_minimum_cvar_portfolio(
        paths,
        evaluation_id="eval-1",
        portfolio_id="cvar",
        constraints=constraints,
        confidence_level=0.95,
    )

    assert len(weight_rows) == 2
    assert all(row["objective"] == MINIMUM_CVAR_OBJECTIVE for row in weight_rows)
    assert sum(float(row["weight"]) for row in weight_rows) == pytest.approx(1.0, abs=1e-6)
    assert read_rows(paths.gold_optimized_weights(MINIMUM_CVAR_OBJECTIVE, "eval-1")) == weight_rows
