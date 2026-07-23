"""Pure-Python historical Minimum CVaR solver (PR61's remaining scope).

Implements the Rockafellar-Uryasev (2000) reformulation of historical
Conditional Value-at-Risk minimization: for `T` historical return scenarios
and confidence level `alpha`,

    CVaR_alpha(w) = min_zeta [ zeta + (1 / ((1-alpha)*T)) * sum_t max(0, -r_t.w - zeta) ]

is convex and piecewise-linear (non-smooth) in `(w, zeta)` jointly. The
repository has no numerical/LP dependency (pyarrow only), so this module
hand-implements a projected subgradient descent solver with a diminishing
step size and best-iterate tracking -- the standard approach for non-smooth
convex optimization when no closed-form or off-the-shelf LP solver is
available, matching the pure-Python precedent set by
`camovar.portfolio_parts.solvers` (projected gradient descent) and
`camovar.portfolio_parts.clustering` (hierarchical clustering).

Per the "Architecture Ownership" principle in
`docs/backlog/00-critical-correctness-priority-queue.md`, this real
implementation lives in a `portfolio_parts` module rather than being
dynamically re-imported from the `camovar.portfolio` facade.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

from camovar.portfolio_parts.solvers import project_capped_simplex

SOLVER_NAME = "projected_subgradient_descent"
SOLVER_VERSION = 1
DEFAULT_MAX_ITERATIONS = 5_000
DEFAULT_TOLERANCE = 1e-4
DEFAULT_CONVERGENCE_WINDOW = 200
DEFAULT_BASE_STEP = 0.5


@dataclass(frozen=True)
class CVaRSolverOutcome:
    """Result of a historical Minimum CVaR solve."""

    weights: tuple[float, ...]
    var: float
    cvar: float
    converged: bool
    iteration_count: int


def historical_var_and_cvar(
    losses: Sequence[float], confidence_level: float
) -> tuple[float, float, int]:
    """Return (VaR, CVaR, tail_observation_count) for a historical loss series.

    VaR is the empirical `confidence_level` quantile of losses; CVaR is the
    average loss at or beyond that quantile (the same convention used by
    `camovar.evaluation`'s historical tail-risk metrics).
    """
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    ordered = sorted(losses)
    if not ordered:
        return 0.0, 0.0, 0
    threshold_index = min(len(ordered) - 1, int(confidence_level * len(ordered)))
    var = ordered[threshold_index]
    tail = [loss for loss in ordered if loss >= var]
    return var, sum(tail) / len(tail), len(tail)


def cvar_objective(
    weights: Sequence[float],
    zeta: float,
    returns_matrix: Sequence[Sequence[float]],
    confidence_level: float,
) -> float:
    """Rockafellar-Uryasev CVaR objective value for given `(weights, zeta)`."""
    observation_count = len(returns_matrix)
    if observation_count == 0:
        return zeta
    denominator = (1.0 - confidence_level) * observation_count
    tail_sum = 0.0
    for scenario in returns_matrix:
        loss = -sum(value * weight for value, weight in zip(scenario, weights, strict=True))
        tail_sum += max(0.0, loss - zeta)
    return zeta + tail_sum / denominator


def cvar_subgradient(
    weights: Sequence[float],
    zeta: float,
    returns_matrix: Sequence[Sequence[float]],
    confidence_level: float,
) -> tuple[list[float], float]:
    """A subgradient of the CVaR objective at `(weights, zeta)`.

    The objective is piecewise-linear in `(w, zeta)`, so a subgradient
    (rather than a true gradient) exists almost everywhere: scenarios in the
    active tail (`loss >= zeta`) contribute `-r_t` to `d/dw` and `-1` to
    `d/dzeta`; scenarios outside the tail contribute nothing. Ties at exactly
    `zeta` are included (matching `historical_var_and_cvar`'s own `>=` tail
    definition): repeated historical losses landing exactly on the empirical
    quantile are common (e.g. limit-down days), and excluding them would
    report a zero subgradient at a point that is not actually stationary.
    """
    asset_count = len(weights)
    observation_count = len(returns_matrix)
    denominator = (1.0 - confidence_level) * observation_count
    gradient_w = [0.0] * asset_count
    gradient_zeta = 1.0
    for scenario in returns_matrix:
        loss = -sum(value * weight for value, weight in zip(scenario, weights, strict=True))
        if loss >= zeta:
            gradient_zeta -= 1.0 / denominator
            for i in range(asset_count):
                gradient_w[i] -= scenario[i] / denominator
    return gradient_w, gradient_zeta


def solve_minimum_cvar(
    returns_matrix: Sequence[Sequence[float]],
    *,
    confidence_level: float,
    min_weight: float,
    max_weight: float,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
    base_step: float = DEFAULT_BASE_STEP,
    convergence_window: int = DEFAULT_CONVERGENCE_WINDOW,
) -> CVaRSolverOutcome:
    """Minimize historical CVaR over long-only, bounded portfolio weights.

    Uses an alternating scheme: at each iteration, `zeta` (the VaR threshold)
    is reset to its exact empirical quantile for the *current* weights (a
    cheap sort, not a subgradient step -- since for fixed weights the
    Rockafellar-Uryasev objective is exactly minimized over `zeta` at the
    empirical VaR), and then a single projected subgradient step with a
    diminishing `base_step / sqrt(iteration)` size updates `w` alone. This
    converges far faster than jointly subgradient-stepping both `(w, zeta)`,
    since a stale `zeta` estimate otherwise has to slowly random-walk back to
    the correct quantile via the subgradient alone. Best-iterate tracking is
    still used (subgradient descent on `w` is not monotone). Convergence is
    declared when the best objective value has not improved by more than a
    `tolerance` relative fraction for `convergence_window` consecutive
    iterations.
    """
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be in (0, 1)")
    asset_count = len(returns_matrix[0]) if returns_matrix else 0
    if asset_count == 0:
        raise ValueError("at least one asset is required")

    weights = project_capped_simplex(
        [1.0 / asset_count] * asset_count, min_weight=min_weight, max_weight=max_weight
    )

    def _losses(current_weights: Sequence[float]) -> list[float]:
        return [
            -sum(value * weight for value, weight in zip(scenario, current_weights, strict=True))
            for scenario in returns_matrix
        ]

    zeta, _var0, _count0 = historical_var_and_cvar(_losses(weights), confidence_level)
    best_weights = tuple(weights)
    best_objective = cvar_objective(weights, zeta, returns_matrix, confidence_level)
    iteration_count = 0
    stall_count = 0
    converged = False

    for iteration in range(1, max_iterations + 1):
        iteration_count = iteration
        zeta, _var, _count = historical_var_and_cvar(_losses(weights), confidence_level)
        gradient_w, _gradient_zeta = cvar_subgradient(
            weights, zeta, returns_matrix, confidence_level
        )
        step = base_step / sqrt(iteration)
        weights = project_capped_simplex(
            [w - step * g for w, g in zip(weights, gradient_w, strict=True)],
            min_weight=min_weight,
            max_weight=max_weight,
        )
        objective = cvar_objective(weights, zeta, returns_matrix, confidence_level)
        relative_improvement = (best_objective - objective) / max(abs(best_objective), 1e-8)
        if relative_improvement > tolerance:
            best_objective = objective
            best_weights = tuple(weights)
            stall_count = 0
        else:
            stall_count += 1
        if stall_count >= convergence_window:
            converged = True
            break

    final_losses = _losses(best_weights)
    var, cvar, _count = historical_var_and_cvar(final_losses, confidence_level)
    return CVaRSolverOutcome(
        weights=best_weights,
        var=var,
        cvar=cvar,
        converged=converged,
        iteration_count=iteration_count,
    )


__all__ = [
    "DEFAULT_BASE_STEP",
    "DEFAULT_CONVERGENCE_WINDOW",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_TOLERANCE",
    "SOLVER_NAME",
    "SOLVER_VERSION",
    "CVaRSolverOutcome",
    "cvar_objective",
    "cvar_subgradient",
    "historical_var_and_cvar",
    "solve_minimum_cvar",
]
