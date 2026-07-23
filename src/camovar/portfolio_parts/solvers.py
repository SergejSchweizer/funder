"""Pure-Python constrained convex solvers for production portfolio construction.

This module implements the actual numerical mathematics for PR60's
solver-backed objectives (Minimum Variance and Equal Risk Contribution),
per the "Architecture Ownership" principle in
`docs/backlog/00-critical-correctness-priority-queue.md`: solver
mathematics belongs in a `portfolio_parts` implementation module, not
dynamically re-imported from the `camovar.portfolio` facade.

The repository intentionally has no numerical runtime dependency (pyarrow
only). Rather than adding scipy/numpy, this module hand-implements a
projected gradient descent solver with a backtracking (Armijo-style) line
search and a capped-simplex projection, matching the existing pure-Python
style used by `camovar.risk_model`'s Jacobi eigenvalue solver.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import sqrt

ListingKey = tuple[str, str, str]

SOLVER_NAME = "projected_gradient_descent"
SOLVER_VERSION = 1
DEFAULT_MAX_ITERATIONS = 3_000
DEFAULT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class SolverOutcome:
    """Result of a projected gradient descent solve."""

    weights: tuple[float, ...]
    converged: bool
    iteration_count: int
    objective_value: float


def dense_covariance_matrix(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> list[list[float]]:
    """Build a dense NxN covariance matrix in canonical listing order.

    Callers must validate completeness (see `camovar.portfolio.
    require_complete_covariance`) before calling this; a missing pair
    raises `KeyError` rather than silently substituting zero.
    """
    return [[covariances[(left, right)] for right in listings] for left in listings]


def project_capped_simplex(
    values: Sequence[float],
    *,
    min_weight: float,
    max_weight: float,
    tolerance: float = 1e-12,
    max_iterations: int = 100,
) -> list[float]:
    """Project `values` onto {w : sum(w) = 1, min_weight <= w_i <= max_weight}.

    Uses bisection on the Lagrange multiplier of the equality constraint
    (a standard algorithm for projection onto a capped simplex): for a
    candidate multiplier `tau`, `w_i(tau) = clip(values_i - tau, lo, hi)` is
    monotonically non-increasing in `tau`, so `sum(w(tau))` is monotonically
    non-increasing and can be bisected to hit 1.0 exactly.
    """
    count = len(values)
    if count == 0:
        raise ValueError("at least one value is required")
    if min_weight * count > 1.0 + 1e-9 or max_weight * count < 1.0 - 1e-9:
        raise ValueError("min_weight/max_weight bounds are infeasible for a simplex of this size")
    low_tau = min(values) - max_weight
    high_tau = max(values) - min_weight
    candidate = [min(max_weight, max(min_weight, value)) for value in values]
    for _ in range(max_iterations):
        mid_tau = (low_tau + high_tau) / 2.0
        candidate = [min(max_weight, max(min_weight, value - mid_tau)) for value in values]
        total = sum(candidate)
        if abs(total - 1.0) < tolerance:
            return candidate
        if total > 1.0:
            low_tau = mid_tau
        else:
            high_tau = mid_tau
    return candidate


def _matvec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [sum(row[j] * vector[j] for j in range(len(vector))) for row in matrix]


def minimum_variance_objective(weights: Sequence[float], covariance_w: Sequence[float]) -> float:
    return sum(w * cw for w, cw in zip(weights, covariance_w, strict=True))


def minimum_variance_gradient(covariance_w: Sequence[float]) -> list[float]:
    return [2.0 * value for value in covariance_w]


def equal_risk_contribution_objective(
    weights: Sequence[float], covariance_w: Sequence[float]
) -> float:
    n = len(weights)
    portfolio_variance = minimum_variance_objective(weights, covariance_w)
    target = portfolio_variance / n
    return sum(
        (weight * cw - target) ** 2 for weight, cw in zip(weights, covariance_w, strict=True)
    )


def equal_risk_contribution_gradient(
    weights: Sequence[float], covariance: Sequence[Sequence[float]], covariance_w: Sequence[float]
) -> list[float]:
    """Analytic gradient of `equal_risk_contribution_objective`.

    Let `RC_i = w_i * (Sigma w)_i` and `T = (w^T Sigma w) / n`. The gradient
    of `sum_i (RC_i - T)^2` with respect to `w_k` is:

        2 * sum_i (RC_i - T) * (d(RC_i)/dw_k - dT/dw_k)

    where `d(RC_i)/dw_k = [i == k] * (Sigma w)_i + w_i * Sigma_ik` and
    `dT/dw_k = (2/n) * (Sigma w)_k` (since `Sigma` is symmetric). This is
    verified against a central-difference numerical gradient in tests.
    """
    n = len(weights)
    portfolio_variance = minimum_variance_objective(weights, covariance_w)
    target = portfolio_variance / n
    residuals = [weight * cw - target for weight, cw in zip(weights, covariance_w, strict=True)]
    gradient = [0.0] * n
    for k in range(n):
        total = 0.0
        for i in range(n):
            d_rc_i_dw_k = (covariance_w[i] if i == k else 0.0) + weights[i] * covariance[i][k]
            d_target_dw_k = (2.0 / n) * covariance_w[k]
            total += residuals[i] * (d_rc_i_dw_k - d_target_dw_k)
        gradient[k] = 2.0 * total
    return gradient


def _projected_gradient_descent(
    *,
    initial_weights: Sequence[float],
    objective_fn: Callable[[Sequence[float]], float],
    gradient_fn: Callable[[Sequence[float]], list[float]],
    project_fn: Callable[[Sequence[float]], list[float]],
    max_iterations: int,
    tolerance: float,
) -> SolverOutcome:
    weights = list(project_fn(initial_weights))
    objective = objective_fn(weights)
    step = 1.0
    converged = False
    iteration_count = 0
    for _iteration in range(1, max_iterations + 1):
        iteration_count += 1
        gradient = gradient_fn(weights)
        step = min(step * 2.0, 1.0)
        while True:
            candidate = project_fn([w - step * g for w, g in zip(weights, gradient, strict=True)])
            candidate_objective = objective_fn(candidate)
            if candidate_objective <= objective + 1e-15 or step < 1e-15:
                break
            step *= 0.5
        movement = max(abs(a - b) for a, b in zip(candidate, weights, strict=True))
        weights = list(candidate)
        objective = candidate_objective
        if movement < tolerance:
            converged = True
            break
    return SolverOutcome(
        weights=tuple(weights),
        converged=converged,
        iteration_count=iteration_count,
        objective_value=objective,
    )


def solve_minimum_variance(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
    *,
    min_weight: float,
    max_weight: float,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> SolverOutcome:
    """Solve constrained Minimum Variance via projected gradient descent."""
    matrix = dense_covariance_matrix(listings, covariances)
    n = len(listings)
    initial = [1.0 / n] * n

    def objective_fn(weights: Sequence[float]) -> float:
        return minimum_variance_objective(weights, _matvec(matrix, weights))

    def gradient_fn(weights: Sequence[float]) -> list[float]:
        return minimum_variance_gradient(_matvec(matrix, weights))

    def project_fn(weights: Sequence[float]) -> list[float]:
        return project_capped_simplex(weights, min_weight=min_weight, max_weight=max_weight)

    return _projected_gradient_descent(
        initial_weights=initial,
        objective_fn=objective_fn,
        gradient_fn=gradient_fn,
        project_fn=project_fn,
        max_iterations=max_iterations,
        tolerance=tolerance,
    )


def solve_equal_risk_contribution(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
    *,
    min_weight: float,
    max_weight: float,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> SolverOutcome:
    """Solve constrained Equal Risk Contribution via projected gradient descent."""
    matrix = dense_covariance_matrix(listings, covariances)
    n = len(listings)
    # Inverse-volatility seed converges faster than equal weight for ERC.
    variances = [matrix[i][i] for i in range(n)]
    inverse_vol = [1.0 / sqrt(value) if value > 0 else 1.0 for value in variances]
    total_inverse_vol = sum(inverse_vol)
    initial = [value / total_inverse_vol for value in inverse_vol]

    def objective_fn(weights: Sequence[float]) -> float:
        return equal_risk_contribution_objective(weights, _matvec(matrix, weights))

    def gradient_fn(weights: Sequence[float]) -> list[float]:
        return equal_risk_contribution_gradient(weights, matrix, _matvec(matrix, weights))

    def project_fn(weights: Sequence[float]) -> list[float]:
        return project_capped_simplex(weights, min_weight=min_weight, max_weight=max_weight)

    return _projected_gradient_descent(
        initial_weights=initial,
        objective_fn=objective_fn,
        gradient_fn=gradient_fn,
        project_fn=project_fn,
        max_iterations=max_iterations,
        tolerance=tolerance,
    )


def inverse_volatility_weights(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
    *,
    min_weight: float,
    max_weight: float,
) -> tuple[float, ...]:
    """Return the Inverse Volatility baseline: weight proportional to 1/volatility.

    A simple, deterministic comparison baseline (per PR60 acceptance
    criteria), not a numerical solver: no iteration or convergence concept
    applies.
    """
    variances = [covariances[(listing, listing)] for listing in listings]
    inverse_vol = [1.0 / sqrt(value) if value > 0 else 0.0 for value in variances]
    total = sum(inverse_vol)
    if total <= 0:
        n = len(listings)
        raw = [1.0 / n] * n
    else:
        raw = [value / total for value in inverse_vol]
    return tuple(project_capped_simplex(raw, min_weight=min_weight, max_weight=max_weight))


__all__ = [
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_TOLERANCE",
    "SOLVER_NAME",
    "SOLVER_VERSION",
    "SolverOutcome",
    "dense_covariance_matrix",
    "equal_risk_contribution_gradient",
    "equal_risk_contribution_objective",
    "inverse_volatility_weights",
    "minimum_variance_gradient",
    "minimum_variance_objective",
    "project_capped_simplex",
    "solve_equal_risk_contribution",
    "solve_minimum_variance",
]
