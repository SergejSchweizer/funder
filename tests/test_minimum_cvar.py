"""Tests for camovar.portfolio_parts.cvar: pure-Python historical Minimum CVaR
solver (Rockafellar-Uryasev projected subgradient descent) for PR61.
"""

import random

import pytest

from camovar.portfolio_parts.cvar import (
    cvar_objective,
    cvar_subgradient,
    historical_var_and_cvar,
    solve_minimum_cvar,
)


def _numerical_gradient_w(weights, zeta, returns_matrix, confidence_level, epsilon=1e-6):
    gradient = []
    for k in range(len(weights)):
        bumped_up = list(weights)
        bumped_up[k] += epsilon
        bumped_down = list(weights)
        bumped_down[k] -= epsilon
        up = cvar_objective(bumped_up, zeta, returns_matrix, confidence_level)
        down = cvar_objective(bumped_down, zeta, returns_matrix, confidence_level)
        gradient.append((up - down) / (2 * epsilon))
    return gradient


def test_historical_var_and_cvar_matches_hand_computed_quantile() -> None:
    losses = [0.01, 0.02, 0.03, 0.04, 0.10]

    var, cvar, tail_count = historical_var_and_cvar(losses, confidence_level=0.8)

    # 80th percentile of 5 sorted losses -> index int(0.8*5)=4 -> loss 0.10.
    assert var == pytest.approx(0.10)
    assert cvar == pytest.approx(0.10)
    assert tail_count == 1


def test_historical_var_and_cvar_averages_repeated_tail_losses() -> None:
    losses = [0.01, 0.02, 0.05, 0.05, 0.05]

    var, cvar, tail_count = historical_var_and_cvar(losses, confidence_level=0.6)

    assert var == pytest.approx(0.05)
    assert cvar == pytest.approx(0.05)
    assert tail_count == 3


def test_historical_var_and_cvar_rejects_invalid_confidence_level() -> None:
    with pytest.raises(ValueError, match="confidence_level"):
        historical_var_and_cvar([0.01], confidence_level=1.5)
    with pytest.raises(ValueError, match="confidence_level"):
        historical_var_and_cvar([0.01], confidence_level=0.0)


def test_historical_var_and_cvar_of_empty_series_is_zero() -> None:
    assert historical_var_and_cvar([], confidence_level=0.95) == (0.0, 0.0, 0)


def test_cvar_subgradient_matches_numerical_gradient_away_from_kinks() -> None:
    # Use a fixture where no loss lands exactly on zeta (avoiding the
    # non-differentiable kink points where subgradient != gradient).
    returns_matrix = [
        (0.01, -0.02),
        (-0.03, 0.01),
        (0.02, 0.02),
        (-0.05, -0.01),
        (0.015, 0.005),
    ]
    weights = [0.4, 0.6]
    zeta = 0.02123456  # off-grid value unlikely to coincide with any loss

    analytic, _analytic_zeta = cvar_subgradient(weights, zeta, returns_matrix, 0.8)
    numerical = _numerical_gradient_w(weights, zeta, returns_matrix, 0.8)

    assert analytic == pytest.approx(numerical, abs=1e-4)


def test_solve_minimum_cvar_favors_lower_tail_risk_asset() -> None:
    random.seed(1)
    returns_matrix = []
    for _ in range(400):
        risky = random.gauss(0.0005, 0.01)
        if random.random() < 0.03:
            risky -= 0.08  # occasional crash: fat left tail
        safe = random.gauss(0.0003, 0.004)
        returns_matrix.append((risky, safe))

    outcome = solve_minimum_cvar(
        returns_matrix, confidence_level=0.95, min_weight=0.0, max_weight=1.0
    )

    assert outcome.converged is True
    assert sum(outcome.weights) == pytest.approx(1.0, abs=1e-6)
    assert outcome.weights[1] > outcome.weights[0]


def test_solve_minimum_cvar_respects_concentration_cap() -> None:
    random.seed(2)
    returns_matrix = []
    for _ in range(300):
        a = random.gauss(0.0004, 0.012)
        if random.random() < 0.03:
            a -= 0.10
        b = random.gauss(0.0003, 0.003)
        c = random.gauss(0.0006, 0.02)
        returns_matrix.append((a, b, c))

    outcome = solve_minimum_cvar(
        returns_matrix, confidence_level=0.95, min_weight=0.0, max_weight=0.6
    )

    assert sum(outcome.weights) == pytest.approx(1.0, abs=1e-6)
    assert all(value <= 0.6 + 1e-6 for value in outcome.weights)


def test_solve_minimum_cvar_handles_repeated_tail_losses() -> None:
    # Several scenarios share the exact same large loss for one asset.
    returns_matrix = [(-0.05, 0.001)] * 5 + [(0.01, 0.0005)] * 45
    outcome = solve_minimum_cvar(
        returns_matrix, confidence_level=0.9, min_weight=0.0, max_weight=1.0
    )

    assert sum(outcome.weights) == pytest.approx(1.0, abs=1e-6)
    assert outcome.weights[1] > outcome.weights[0]


def test_solve_minimum_cvar_rejects_invalid_confidence_level() -> None:
    with pytest.raises(ValueError, match="confidence_level"):
        solve_minimum_cvar([(0.01, 0.02)], confidence_level=1.0, min_weight=0.0, max_weight=1.0)


def test_solve_minimum_cvar_rejects_empty_returns_matrix() -> None:
    with pytest.raises(ValueError, match="at least one asset"):
        solve_minimum_cvar([], confidence_level=0.95, min_weight=0.0, max_weight=1.0)


def test_solve_minimum_cvar_reports_non_convergence_within_low_iteration_budget() -> None:
    random.seed(3)
    returns_matrix = [(random.gauss(0.0, 0.02), random.gauss(0.0, 0.02)) for _ in range(200)]

    outcome = solve_minimum_cvar(
        returns_matrix,
        confidence_level=0.95,
        min_weight=0.0,
        max_weight=1.0,
        max_iterations=1,
        convergence_window=200,
    )

    assert outcome.converged is False
    assert outcome.iteration_count == 1


def test_solve_minimum_cvar_is_deterministic_across_repeated_calls() -> None:
    random.seed(4)
    returns_matrix = [(random.gauss(0.0002, 0.01), random.gauss(0.0001, 0.005)) for _ in range(200)]

    first = solve_minimum_cvar(
        returns_matrix, confidence_level=0.95, min_weight=0.0, max_weight=1.0
    )
    second = solve_minimum_cvar(
        returns_matrix, confidence_level=0.95, min_weight=0.0, max_weight=1.0
    )

    assert first == second
