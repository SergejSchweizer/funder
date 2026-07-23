"""Tests for camovar.portfolio_parts.solvers: pure-Python PGD solvers for PR60."""

import pytest

from camovar.portfolio_parts.solvers import (
    dense_covariance_matrix,
    equal_risk_contribution_gradient,
    equal_risk_contribution_objective,
    inverse_volatility_weights,
    minimum_variance_gradient,
    minimum_variance_objective,
    project_capped_simplex,
    solve_equal_risk_contribution,
    solve_minimum_variance,
)

_LISTINGS = [("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB"), ("IE3", "PA", "CCC")]


def _matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[j] * vector[j] for j in range(len(vector))) for row in matrix]


def _covariance_dict(matrix: list[list[float]]) -> dict[tuple[tuple, tuple], float]:
    return {
        (_LISTINGS[i], _LISTINGS[j]): matrix[i][j]
        for i in range(len(_LISTINGS))
        for j in range(len(_LISTINGS))
    }


def _numerical_gradient(fn, weights: list[float], *, epsilon: float = 1e-6) -> list[float]:
    gradient = []
    for k in range(len(weights)):
        bumped_up = list(weights)
        bumped_up[k] += epsilon
        bumped_down = list(weights)
        bumped_down[k] -= epsilon
        gradient.append((fn(bumped_up) - fn(bumped_down)) / (2 * epsilon))
    return gradient


def test_project_capped_simplex_sums_to_one_and_respects_bounds() -> None:
    projected = project_capped_simplex([0.5, 0.2, -0.1], min_weight=0.0, max_weight=0.6)

    assert sum(projected) == pytest.approx(1.0)
    assert all(0.0 - 1e-9 <= value <= 0.6 + 1e-9 for value in projected)


def test_project_capped_simplex_is_idempotent_for_a_feasible_point() -> None:
    feasible = [0.3, 0.3, 0.4]
    projected = project_capped_simplex(feasible, min_weight=0.0, max_weight=0.6)

    assert projected == pytest.approx(feasible)


def test_project_capped_simplex_rejects_infeasible_bounds() -> None:
    with pytest.raises(ValueError, match="infeasible"):
        project_capped_simplex([0.1, 0.2, 0.3], min_weight=0.5, max_weight=0.6)


def test_project_capped_simplex_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one value is required"):
        project_capped_simplex([], min_weight=0.0, max_weight=1.0)


def test_project_capped_simplex_returns_best_effort_after_iteration_budget() -> None:
    projected = project_capped_simplex(
        [0.5, 0.2, -0.1], min_weight=0.0, max_weight=0.6, max_iterations=0
    )

    assert projected == [0.5, 0.2, 0.0]


def test_dense_covariance_matrix_is_symmetric_and_ordered() -> None:
    matrix = [[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.16]]
    covariances = _covariance_dict(matrix)

    dense = dense_covariance_matrix(_LISTINGS, covariances)

    assert dense == matrix


def test_dense_covariance_matrix_raises_key_error_for_incomplete_input() -> None:
    with pytest.raises(KeyError):
        dense_covariance_matrix(_LISTINGS, {})


def test_equal_risk_contribution_gradient_matches_numerical_gradient() -> None:
    matrix = [[0.04, 0.015, 0.005], [0.015, 0.09, 0.02], [0.005, 0.02, 0.16]]
    weights = [0.5, 0.3, 0.2]

    def objective(w: list[float]) -> float:
        return equal_risk_contribution_objective(w, _matvec(matrix, w))

    analytic = equal_risk_contribution_gradient(weights, matrix, _matvec(matrix, weights))
    numerical = _numerical_gradient(objective, weights)

    assert analytic == pytest.approx(numerical, abs=1e-4)


def test_minimum_variance_gradient_matches_numerical_gradient() -> None:
    matrix = [[0.04, 0.015, 0.005], [0.015, 0.09, 0.02], [0.005, 0.02, 0.16]]
    weights = [0.5, 0.3, 0.2]

    def objective(w: list[float]) -> float:
        return minimum_variance_objective(w, _matvec(matrix, w))

    analytic = minimum_variance_gradient(_matvec(matrix, weights))
    numerical = _numerical_gradient(objective, weights)

    assert analytic == pytest.approx(numerical, abs=1e-4)


def test_solve_minimum_variance_converges_on_diagonal_covariance() -> None:
    # Diagonal covariance: the closed-form minimum-variance solution is
    # inverse-variance weighting, w_i proportional to 1 / variance_i.
    matrix = [[0.01, 0.0, 0.0], [0.0, 0.04, 0.0], [0.0, 0.0, 0.09]]
    covariances = _covariance_dict(matrix)

    outcome = solve_minimum_variance(_LISTINGS, covariances, min_weight=0.0, max_weight=1.0)

    inverse_variance = [1 / 0.01, 1 / 0.04, 1 / 0.09]
    expected = [value / sum(inverse_variance) for value in inverse_variance]
    assert outcome.converged is True
    assert list(outcome.weights) == pytest.approx(expected, abs=1e-4)
    assert sum(outcome.weights) == pytest.approx(1.0)


def test_solve_minimum_variance_respects_allocation_caps() -> None:
    matrix = [[0.01, 0.0, 0.0], [0.0, 0.04, 0.0], [0.0, 0.0, 0.09]]
    covariances = _covariance_dict(matrix)

    outcome = solve_minimum_variance(_LISTINGS, covariances, min_weight=0.1, max_weight=0.5)

    assert outcome.converged is True
    assert sum(outcome.weights) == pytest.approx(1.0)
    assert all(0.1 - 1e-6 <= value <= 0.5 + 1e-6 for value in outcome.weights)


def test_solve_minimum_variance_handles_correlated_cluster() -> None:
    # IE1/IE2 are highly correlated (near-duplicate ETFs); IE3 is independent.
    matrix = [[0.04, 0.038, 0.0], [0.038, 0.04, 0.0], [0.0, 0.0, 0.01]]
    covariances = _covariance_dict(matrix)

    outcome = solve_minimum_variance(_LISTINGS, covariances, min_weight=0.0, max_weight=1.0)

    assert outcome.converged is True
    # The solver should still find a valid, feasible, low-variance portfolio.
    assert sum(outcome.weights) == pytest.approx(1.0)
    assert outcome.objective_value >= 0.0


def test_solve_minimum_variance_handles_near_singular_covariance() -> None:
    # IE1 and IE2 are (numerically) identical instruments.
    matrix = [[0.04, 0.0399999, 0.0], [0.0399999, 0.04, 0.0], [0.0, 0.0, 0.01]]
    covariances = _covariance_dict(matrix)

    outcome = solve_minimum_variance(
        _LISTINGS, covariances, min_weight=0.0, max_weight=1.0, max_iterations=1000
    )

    assert sum(outcome.weights) == pytest.approx(1.0, abs=1e-6)
    assert all(value >= -1e-6 for value in outcome.weights)


def test_solve_minimum_variance_handles_zero_variance_asset() -> None:
    # IE3 has zero variance and zero covariance with everything else.
    matrix = [[0.04, 0.01, 0.0], [0.01, 0.09, 0.0], [0.0, 0.0, 0.0]]
    covariances = _covariance_dict(matrix)

    outcome = solve_minimum_variance(_LISTINGS, covariances, min_weight=0.0, max_weight=1.0)

    assert outcome.converged is True
    assert sum(outcome.weights) == pytest.approx(1.0)
    # Zero-variance, zero-covariance asset absorbs all remaining allocation
    # at the true minimum (portfolio variance floor is zero).
    assert outcome.objective_value == pytest.approx(0.0, abs=1e-6)


def test_solve_equal_risk_contribution_reports_converged_and_feasible_weights() -> None:
    matrix = [[0.04, 0.01, 0.005], [0.01, 0.09, 0.02], [0.005, 0.02, 0.16]]
    covariances = _covariance_dict(matrix)

    outcome = solve_equal_risk_contribution(_LISTINGS, covariances, min_weight=0.0, max_weight=1.0)

    assert outcome.converged is True
    assert sum(outcome.weights) == pytest.approx(1.0)
    assert all(value >= -1e-9 for value in outcome.weights)


def test_solve_equal_risk_contribution_produces_near_equal_risk_budgets() -> None:
    matrix = [[0.04, 0.0, 0.0], [0.0, 0.09, 0.0], [0.0, 0.0, 0.16]]
    covariances = _covariance_dict(matrix)

    outcome = solve_equal_risk_contribution(_LISTINGS, covariances, min_weight=0.0, max_weight=1.0)

    weights = list(outcome.weights)
    contributions = [
        weights[i] * sum(matrix[i][j] * weights[j] for j in range(3)) for i in range(3)
    ]
    target = sum(contributions) / 3
    for contribution in contributions:
        assert contribution == pytest.approx(target, abs=1e-4)


def test_solve_equal_risk_contribution_reports_non_convergence_within_low_iteration_budget() -> (
    None
):
    matrix = [[0.04, 0.01, 0.005], [0.01, 0.09, 0.02], [0.005, 0.02, 0.16]]
    covariances = _covariance_dict(matrix)

    outcome = solve_equal_risk_contribution(
        _LISTINGS, covariances, min_weight=0.0, max_weight=1.0, max_iterations=1
    )

    assert outcome.converged is False
    assert outcome.iteration_count == 1


def test_inverse_volatility_weights_are_proportional_to_inverse_standard_deviation() -> None:
    matrix = [[0.01, 0.0, 0.0], [0.0, 0.04, 0.0], [0.0, 0.0, 0.09]]
    covariances = _covariance_dict(matrix)

    weights = inverse_volatility_weights(_LISTINGS, covariances, min_weight=0.0, max_weight=1.0)

    inverse_vol = [1 / 0.1, 1 / 0.2, 1 / 0.3]
    expected = [value / sum(inverse_vol) for value in inverse_vol]
    assert list(weights) == pytest.approx(expected)
    assert sum(weights) == pytest.approx(1.0)


def test_inverse_volatility_weights_fall_back_to_equal_weight_when_all_variances_are_zero() -> None:
    matrix = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    covariances = _covariance_dict(matrix)

    weights = inverse_volatility_weights(_LISTINGS, covariances, min_weight=0.0, max_weight=1.0)

    assert list(weights) == pytest.approx([1 / 3, 1 / 3, 1 / 3])
