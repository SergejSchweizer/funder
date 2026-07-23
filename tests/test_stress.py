"""Tests for PR65's stress, bootstrap, and sensitivity analysis module."""

import pytest

from camovar.stress import (
    BLOCK_BOOTSTRAP_SCENARIO,
    CORRELATION_CONVERGENCE_SCENARIO,
    COVARIANCE_PERTURBATION_SCENARIO,
    DISTRIBUTION_CUT_SCENARIO,
    HISTORICAL_STRESS_SCENARIO,
    block_bootstrap_scenarios,
    build_sensitivity_summary,
    correlation_convergence_scenario,
    covariance_perturbation_scenario,
    detect_worst_drawdown_window,
    distribution_cut_scenario,
    historical_stress_scenario,
    parametric_var_cvar,
)


def _row(isin: str, exchange: str, code: str, date: str, value: float) -> dict[str, object]:
    return {
        "evaluation_id": "eval-1",
        "date": date,
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "return": value,
        "simple_return": value,
    }


def _matrix_rows() -> list[dict[str, object]]:
    # Two assets over 10 days; days 4-6 (index 3-5, 0-based) form a clear
    # crash window for both (a deep, deterministic drawdown), surrounded by
    # steady positive days.
    a_returns = [0.01, 0.01, 0.01, -0.20, -0.15, -0.10, 0.01, 0.01, 0.01, 0.01]
    b_returns = [0.005, 0.005, 0.005, -0.10, -0.08, -0.05, 0.005, 0.005, 0.005, 0.005]
    rows: list[dict[str, object]] = []
    for day in range(10):
        date = f"2020-01-{day + 1:02d}"
        rows.append(_row("IE1", "XETRA", "AAA", date, a_returns[day]))
        rows.append(_row("IE2", "AS", "BBB", date, b_returns[day]))
    return rows


_WEIGHTS = {"IE1": 0.5, "IE2": 0.5}


def test_parametric_var_cvar_matches_known_z_scores() -> None:
    var, cvar = parametric_var_cvar(0.02, 0.95)

    assert var == pytest.approx(1.644854 * 0.02, rel=1e-5)
    assert cvar > var


def test_parametric_var_cvar_zero_volatility_is_zero() -> None:
    assert parametric_var_cvar(0.0, 0.95) == (0.0, 0.0)


def test_parametric_var_cvar_rejects_negative_volatility() -> None:
    with pytest.raises(ValueError, match="volatility"):
        parametric_var_cvar(-0.01, 0.95)


def test_detect_worst_drawdown_window_finds_the_crash_days() -> None:
    start, end = detect_worst_drawdown_window(_matrix_rows(), _WEIGHTS, window_length=3)

    assert start == "2020-01-04"
    assert end == "2020-01-06"


def test_detect_worst_drawdown_window_rejects_insufficient_history() -> None:
    with pytest.raises(ValueError, match="observations are required"):
        detect_worst_drawdown_window(_matrix_rows(), _WEIGHTS, window_length=100)


def test_historical_stress_scenario_replays_the_worst_window() -> None:
    result = historical_stress_scenario(
        _matrix_rows(), _WEIGHTS, candidate_id="balanced", window_length=3
    )

    assert result.scenario_type == HISTORICAL_STRESS_SCENARIO
    assert result.compounded_return < 0
    assert result.max_drawdown < 0
    assert result.cvar >= result.var
    assert result.parameters["start_date"] == "2020-01-04"


def test_historical_stress_scenario_is_deterministic() -> None:
    first = historical_stress_scenario(
        _matrix_rows(), _WEIGHTS, candidate_id="balanced", window_length=3
    )
    second = historical_stress_scenario(
        _matrix_rows(), _WEIGHTS, candidate_id="balanced", window_length=3
    )

    assert first.scenario_id == second.scenario_id
    assert first == second


def test_distribution_cut_scenario_applies_shock_to_selected_isin() -> None:
    # Use an all-positive return series so a cut can only make the outcome
    # worse -- a crash-window fixture would let a cut soften pre-existing
    # losses too, which is a real (if confusing) property of a uniform
    # percentage shock, not the intent of this test.
    steady_rows = [
        _row("IE1", "XETRA", "AAA", f"2020-01-{day + 1:02d}", 0.01) for day in range(10)
    ] + [_row("IE2", "AS", "BBB", f"2020-01-{day + 1:02d}", 0.005) for day in range(10)]
    cut = distribution_cut_scenario(
        steady_rows,
        _WEIGHTS,
        candidate_id="balanced",
        cut_isins=["IE1"],
        cut_factor=-0.5,
    )
    no_cut = distribution_cut_scenario(
        steady_rows,
        _WEIGHTS,
        candidate_id="balanced",
        cut_isins=["IE1"],
        cut_factor=0.0,
    )

    assert cut.scenario_type == DISTRIBUTION_CUT_SCENARIO
    assert cut.compounded_return < no_cut.compounded_return


def test_distribution_cut_scenario_rejects_boosting_factor() -> None:
    with pytest.raises(ValueError, match="cut_factor"):
        distribution_cut_scenario(
            _matrix_rows(), _WEIGHTS, candidate_id="balanced", cut_isins=["IE1"], cut_factor=0.5
        )


def test_block_bootstrap_scenarios_are_seeded_and_deterministic() -> None:
    first = block_bootstrap_scenarios(
        _matrix_rows(),
        _WEIGHTS,
        candidate_id="balanced",
        block_length=2,
        scenario_count=5,
        seed=42,
    )
    second = block_bootstrap_scenarios(
        _matrix_rows(),
        _WEIGHTS,
        candidate_id="balanced",
        block_length=2,
        scenario_count=5,
        seed=42,
    )

    assert len(first) == 5
    assert all(result.scenario_type == BLOCK_BOOTSTRAP_SCENARIO for result in first)
    assert [result.scenario_id for result in first] == [result.scenario_id for result in second]
    assert [result.compounded_return for result in first] == [
        result.compounded_return for result in second
    ]
    # Distinct scenario indices should not all be identical scenario ids.
    assert len({result.scenario_id for result in first}) > 1


def test_block_bootstrap_scenarios_different_seed_differs() -> None:
    seed_a = block_bootstrap_scenarios(
        _matrix_rows(), _WEIGHTS, candidate_id="balanced", block_length=2, scenario_count=3, seed=1
    )
    seed_b = block_bootstrap_scenarios(
        _matrix_rows(), _WEIGHTS, candidate_id="balanced", block_length=2, scenario_count=3, seed=2
    )

    assert [r.scenario_id for r in seed_a] != [r.scenario_id for r in seed_b]


def test_block_bootstrap_scenarios_rejects_insufficient_history() -> None:
    with pytest.raises(ValueError, match="observations are required"):
        block_bootstrap_scenarios(
            _matrix_rows(),
            _WEIGHTS,
            candidate_id="balanced",
            block_length=100,
            scenario_count=1,
            seed=1,
        )


_COVARIANCE = [[0.0004, 0.0001], [0.0001, 0.0001]]
_ORDERED_WEIGHTS = (0.5, 0.5)


def test_correlation_convergence_scenario_increases_risk_as_factor_rises() -> None:
    low = correlation_convergence_scenario(
        _COVARIANCE, _ORDERED_WEIGHTS, candidate_id="balanced", convergence_factor=0.0
    )
    high = correlation_convergence_scenario(
        _COVARIANCE, _ORDERED_WEIGHTS, candidate_id="balanced", convergence_factor=1.0
    )

    assert low.scenario_type == CORRELATION_CONVERGENCE_SCENARIO
    assert high.var > low.var
    assert high.cvar > low.cvar
    assert low.compounded_return == 0.0


def test_correlation_convergence_scenario_rejects_out_of_range_factor() -> None:
    with pytest.raises(ValueError, match="convergence_factor"):
        correlation_convergence_scenario(
            _COVARIANCE, _ORDERED_WEIGHTS, candidate_id="balanced", convergence_factor=1.5
        )


def test_covariance_perturbation_scenario_scales_risk() -> None:
    baseline = covariance_perturbation_scenario(
        _COVARIANCE, _ORDERED_WEIGHTS, candidate_id="balanced", perturbation_factor=0.0
    )
    bumped = covariance_perturbation_scenario(
        _COVARIANCE, _ORDERED_WEIGHTS, candidate_id="balanced", perturbation_factor=1.0
    )

    assert bumped.scenario_type == COVARIANCE_PERTURBATION_SCENARIO
    assert bumped.var == pytest.approx(baseline.var * (2**0.5), rel=1e-6)


def test_covariance_perturbation_scenario_rejects_full_wipeout_or_below() -> None:
    with pytest.raises(ValueError, match="perturbation_factor"):
        covariance_perturbation_scenario(
            _COVARIANCE, _ORDERED_WEIGHTS, candidate_id="balanced", perturbation_factor=-1.0
        )


def test_build_sensitivity_summary_aggregates_median_and_worst_case() -> None:
    rows = _matrix_rows()
    scenarios = [
        historical_stress_scenario(rows, _WEIGHTS, candidate_id="balanced", window_length=3),
        distribution_cut_scenario(
            rows, _WEIGHTS, candidate_id="balanced", cut_isins=["IE1"], cut_factor=-0.5
        ),
        *block_bootstrap_scenarios(
            rows, _WEIGHTS, candidate_id="balanced", block_length=2, scenario_count=3, seed=7
        ),
    ]

    summary = build_sensitivity_summary(scenarios)

    assert summary["candidate_id"] == "balanced"
    assert summary["scenario_count"] == 5
    assert summary["worst_compounded_return"] <= summary["median_compounded_return"]
    assert summary["worst_max_drawdown"] <= summary["median_max_drawdown"]
    assert summary["worst_cvar"] >= summary["median_cvar"]


def test_build_sensitivity_summary_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one scenario result"):
        build_sensitivity_summary([])


def test_build_sensitivity_summary_rejects_mixed_candidates() -> None:
    rows = _matrix_rows()
    scenario_a = historical_stress_scenario(rows, _WEIGHTS, candidate_id="a", window_length=3)
    scenario_b = historical_stress_scenario(rows, _WEIGHTS, candidate_id="b", window_length=3)

    with pytest.raises(ValueError, match="same candidate"):
        build_sensitivity_summary([scenario_a, scenario_b])
