"""Tests for PR63's portfolio profile contracts and ensemble candidate construction."""

import random
from pathlib import Path
from statistics import mean

import pytest

from camovar.calculation_status import UNAVAILABLE
from camovar.paths import LakePaths
from camovar.portfolio import PortfolioConstraints
from camovar.profiles import (
    BALANCED_PROFILE,
    DEFENSIVE_PROFILE,
    GROWTH_PROFILE,
    INCOME_PROFILE,
    ProfileContract,
    balanced_profile,
    build_balanced_ensemble_weights,
    defensive_profile,
    evaluate_profile_candidate,
    growth_profile,
    income_profile,
    write_profile_candidate,
)
from camovar.table_io import write_rows

_LISTINGS = [
    {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},  # risky, fat-tailed
    {"isin": "IE2", "exchange": "AS", "code": "BBB"},  # safe
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
            {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": date, "return": risky}
        )
        rows.append({"isin": "IE2", "exchange": "AS", "code": "BBB", "date": date, "return": safe})
    return rows


def _covariance_rows(return_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_listing: dict[tuple[str, str, str], list[float]] = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, []).append(float(row["return"]))
    keys = list(by_listing)
    means = {key: mean(values) for key, values in by_listing.items()}
    n = len(by_listing[keys[0]])
    rows: list[dict[str, object]] = []
    for left in keys:
        for right in keys:
            covariance = sum(
                (by_listing[left][t] - means[left]) * (by_listing[right][t] - means[right])
                for t in range(n)
            ) / (n - 1)
            rows.append(
                {
                    "left_isin": left[0],
                    "left_exchange": left[1],
                    "left_code": left[2],
                    "right_isin": right[0],
                    "right_exchange": right[1],
                    "right_code": right[2],
                    "covariance": covariance,
                }
            )
    return rows


def test_profile_contract_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="name must be one of"):
        ProfileContract(
            name="aggressive",
            version=1,
            objective_set=("equal_risk_contribution",),
            constraints=PortfolioConstraints(max_weight=1.0),
        )


def test_profile_contract_rejects_empty_objective_set() -> None:
    with pytest.raises(ValueError, match="objective_set must be non-empty"):
        ProfileContract(
            name=BALANCED_PROFILE,
            version=1,
            objective_set=(),
            constraints=PortfolioConstraints(max_weight=1.0),
        )


def test_defensive_balanced_income_growth_profiles_have_expected_shapes() -> None:
    defensive = defensive_profile()
    balanced = balanced_profile()
    income = income_profile()
    growth = growth_profile()

    assert defensive.name == DEFENSIVE_PROFILE
    assert defensive.objective_set == ("shrinkage_minimum_variance",)
    assert balanced.name == BALANCED_PROFILE
    assert balanced.objective_set == (
        "hierarchical_risk_parity",
        "equal_risk_contribution",
        "shrinkage_minimum_variance",
    )
    assert income.name == INCOME_PROFILE
    assert income.requires_income_data is True
    assert growth.name == GROWTH_PROFILE
    assert defensive.requires_income_data is False


def test_build_balanced_ensemble_weights_favors_the_safe_asset() -> None:
    return_rows = _return_rows()
    covariance_rows = _covariance_rows(return_rows)
    constraints = PortfolioConstraints(max_weight=1.0)

    weights = build_balanced_ensemble_weights(_LISTINGS, covariance_rows, return_rows, constraints)

    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert weights["IE2"] > weights["IE1"]


def test_evaluate_profile_candidate_balanced_is_feasible_with_baselines() -> None:
    return_rows = _return_rows()
    covariance_rows = _covariance_rows(return_rows)
    profile = ProfileContract(
        name=BALANCED_PROFILE,
        version=1,
        objective_set=(
            "hierarchical_risk_parity",
            "equal_risk_contribution",
            "shrinkage_minimum_variance",
        ),
        constraints=PortfolioConstraints(max_weight=1.0),
    )

    candidate = evaluate_profile_candidate(profile, _LISTINGS, covariance_rows, return_rows)

    assert candidate["status"] == "feasible"
    assert candidate["reasons"] == []
    assert sum(candidate["weights"].values()) == pytest.approx(1.0, abs=1e-6)
    assert "equal_weight_variance" in candidate["baseline_comparison"]
    assert "inverse_volatility_variance" in candidate["baseline_comparison"]
    assert candidate["portfolio_variance"] is not None
    assert candidate["portfolio_variance"] > 0


def test_evaluate_profile_candidate_is_deterministic() -> None:
    return_rows = _return_rows()
    covariance_rows = _covariance_rows(return_rows)
    profile = balanced_profile(max_weight=1.0)

    first = evaluate_profile_candidate(profile, _LISTINGS, covariance_rows, return_rows)
    second = evaluate_profile_candidate(profile, _LISTINGS, covariance_rows, return_rows)

    assert first["profile_candidate_id"] == second["profile_candidate_id"]


def test_evaluate_profile_candidate_defensive_uses_shrinkage_minimum_variance() -> None:
    return_rows = _return_rows()
    covariance_rows = _covariance_rows(return_rows)
    profile = defensive_profile(max_weight=1.0)

    candidate = evaluate_profile_candidate(profile, _LISTINGS, covariance_rows, return_rows)

    assert candidate["status"] == "feasible"
    assert candidate["objective_set"] == ["shrinkage_minimum_variance"]


def test_evaluate_profile_candidate_growth_uses_equal_risk_contribution() -> None:
    return_rows = _return_rows()
    covariance_rows = _covariance_rows(return_rows)
    profile = growth_profile(max_weight=1.0)

    candidate = evaluate_profile_candidate(profile, _LISTINGS, covariance_rows, return_rows)

    assert candidate["status"] == "feasible"
    assert candidate["objective_set"] == ["equal_risk_contribution"]


def test_evaluate_profile_candidate_income_reports_income_limits_unavailable() -> None:
    return_rows = _return_rows()
    covariance_rows = _covariance_rows(return_rows)
    profile = income_profile(max_weight=1.0)

    candidate = evaluate_profile_candidate(profile, _LISTINGS, covariance_rows, return_rows)

    assert candidate["requires_income_data"] is True
    assert candidate["risk_limits"]["min_net_income"] == UNAVAILABLE
    assert candidate["risk_limits"]["max_nav_erosion"] == UNAVAILABLE
    # Concentration/turnover/CVaR limits that don't need the tax/cost stack
    # remain declared, not blanked out.
    assert candidate["risk_limits"]["max_cvar"] is not None


def test_evaluate_profile_candidate_reports_infeasible_for_insufficient_history() -> None:
    sparse_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2020-01-01", "return": 0.01},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2020-02-01", "return": 0.02},
    ]
    sparse_covariance_rows = _covariance_rows(
        [
            {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "d", "return": 0.01},
            {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "d", "return": 0.02},
            {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "d2", "return": 0.02},
            {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "d2", "return": 0.01},
        ]
    )
    profile = defensive_profile(max_weight=1.0)

    candidate = evaluate_profile_candidate(profile, _LISTINGS, sparse_covariance_rows, sparse_rows)

    assert candidate["status"] == "infeasible"
    assert candidate["weights"] == {}
    assert candidate["reasons"]


def test_write_profile_candidate_persists_weights_and_diagnostics(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    return_rows = _return_rows()
    covariance_rows = _covariance_rows(return_rows)
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
    grouped_covariance_rows: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in covariance_rows:
        key = (str(row["left_exchange"]), str(row["left_isin"]))
        grouped_covariance_rows.setdefault(key, []).append(row)
    for (exchange, isin), rows in grouped_covariance_rows.items():
        write_rows(paths.gold_covariance(exchange, isin), rows)
    profile = balanced_profile(max_weight=1.0)

    weight_rows = write_profile_candidate(
        paths, evaluation_id="eval-1", portfolio_id="balanced", profile=profile
    )

    assert len(weight_rows) == 2
    assert all(row["objective"] == "profile_balanced" for row in weight_rows)
    assert sum(float(row["weight"]) for row in weight_rows) == pytest.approx(1.0, abs=1e-6)
