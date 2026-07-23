"""Portfolio constraint helpers and deterministic optimization objectives."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import comb, isclose, isfinite
from typing import Any

from camovar.paths import LakePaths
from camovar.portfolio_parts.clustering import ALGORITHM_VERSION as HRP_ALGORITHM_VERSION
from camovar.portfolio_parts.clustering import LINKAGE_METHOD as HRP_LINKAGE_METHOD
from camovar.portfolio_parts.clustering import TIE_BREAKING_POLICY as HRP_TIE_BREAKING_POLICY
from camovar.portfolio_parts.clustering import (
    correlation_distance_matrix,
    quasi_diagonal_order,
    recursive_bisection,
    single_linkage,
)
from camovar.portfolio_parts.cvar import SOLVER_NAME as CVAR_SOLVER_NAME
from camovar.portfolio_parts.cvar import SOLVER_VERSION as CVAR_SOLVER_VERSION
from camovar.portfolio_parts.cvar import (
    historical_var_and_cvar,
    solve_minimum_cvar,
)
from camovar.portfolio_parts.solvers import SOLVER_NAME as PGD_SOLVER_NAME
from camovar.portfolio_parts.solvers import SOLVER_VERSION as PGD_SOLVER_VERSION
from camovar.portfolio_parts.solvers import (
    SolverOutcome,
    dense_covariance_matrix,
    project_capped_simplex,
    solve_equal_risk_contribution,
    solve_minimum_variance,
)
from camovar.risk_model import estimate_risk_model
from camovar.table_io import JsonRow, read_rows, write_rows

ListingKey = tuple[str, str, str]
MAX_EXACT_WEIGHT_CANDIDATES = 20_000
RISK_PARITY_OBJECTIVES = {"risk_parity", "equal_risk_contribution"}
MAXIMUM_DIVERSIFICATION_OBJECTIVE = "maximum_diversification"
BASELINE_OPTIMIZER_TYPE = "deterministic_baseline"
PRODUCTION_OPTIMIZER_TYPE = "production_solver"
GRID_OBJECTIVES = frozenset(
    {
        "minimum_variance",
        "maximum_sharpe",
        "target_return_minimum_variance",
        MAXIMUM_DIVERSIFICATION_OBJECTIVE,
        *RISK_PARITY_OBJECTIVES,
    }
)
# Objectives with a real solver-backed production implementation (PR60).
# maximum_sharpe, target_return_minimum_variance, and maximum_diversification
# remain grid-only comparison methods until a later PR gives them a solver.
SOLVER_BACKED_OBJECTIVES = frozenset({"minimum_variance", *RISK_PARITY_OBJECTIVES})
# PR61: historical Minimum CVaR is a scenario-based objective (needs the full
# aligned return matrix, not a covariance matrix) with its own solver, kept
# separate from optimize_portfolio's covariance-based objectives.
MINIMUM_CVAR_OBJECTIVE = "minimum_cvar"
DEFAULT_CVAR_CONFIDENCE_LEVEL = 0.95
PRODUCTION_SOLVER_MODE = "production"
BASELINE_SOLVER_MODE = "baseline"
SOLVER_MODES = (PRODUCTION_SOLVER_MODE, BASELINE_SOLVER_MODE)
OPTIMIZER_ALGORITHM_VERSION = 1
WEIGHT_SUM_TOLERANCE = 1e-9
EQUAL_WEIGHT_FALLBACK_METHOD = "equal_weight_fallback"
CANDIDATE_LIMIT_EXCEEDED_REASON = "candidate_limit_exceeded"
# PR61: the naive midpoint-recursive-variance split is a labeled baseline;
# only the real single-linkage/quasi-diagonal construction may be reported
# as `hierarchical_risk_parity` in a production-facing artifact.
HIERARCHICAL_RISK_PARITY_OBJECTIVE = "hierarchical_risk_parity"
HIERARCHICAL_RISK_PARITY_BASELINE_OBJECTIVE = "hierarchical_risk_parity_baseline"


@dataclass(frozen=True)
class PortfolioConstraints:
    """Explicit constraints for the first minimum-risk portfolio run."""

    long_only: bool = True
    min_weight: float = 0.0
    max_weight: float = 0.2
    min_quote_coverage: float = 0.95

    def __post_init__(self) -> None:
        if self.min_weight < 0:
            raise ValueError("min_weight cannot be negative")
        if self.max_weight <= 0:
            raise ValueError("max_weight must be positive")
        if self.min_weight > self.max_weight:
            raise ValueError("min_weight cannot exceed max_weight")
        if not 0 < self.min_quote_coverage <= 1:
            raise ValueError("min_quote_coverage must be in (0, 1]")

    def as_dict(self) -> JsonRow:
        return {
            "long_only": self.long_only,
            "min_weight": self.min_weight,
            "max_weight": self.max_weight,
            "min_quote_coverage": self.min_quote_coverage,
        }


@dataclass(frozen=True)
class OptimizerDiagnostics:
    optimizer_type: str
    optimizer_status: str
    requested_method: str
    actual_method: str
    solver_name: str
    solver_version: int
    solver_status: str
    convergence_status: str
    objective_value: float
    expected_return: float
    portfolio_variance: float
    constraint_violations: tuple[str, ...]
    constraint_residuals: tuple[float, ...]
    bound_activity: tuple[str, ...]
    covariance_condition: str
    missing_covariance_count: int
    non_finite_covariance_count: int
    input_listing_count: int
    iteration_count: int
    numeric_tolerances: Mapping[str, float]
    risk_model_id: str
    fallback_used: bool
    fallback_reason: str
    production_eligible: bool
    turnover_estimate: float = 0.0

    def as_dict(self) -> JsonRow:
        return {
            "optimizer_type": self.optimizer_type,
            "optimizer_status": self.optimizer_status,
            "requested_method": self.requested_method,
            "actual_method": self.actual_method,
            "solver_name": self.solver_name,
            "solver_version": self.solver_version,
            "solver_status": self.solver_status,
            "convergence_status": self.convergence_status,
            "objective_value": self.objective_value,
            "expected_return": self.expected_return,
            "portfolio_variance": self.portfolio_variance,
            "constraint_violations": list(self.constraint_violations),
            "constraint_residuals": list(self.constraint_residuals),
            "bound_activity": list(self.bound_activity),
            "covariance_condition": self.covariance_condition,
            "missing_covariance_count": self.missing_covariance_count,
            "non_finite_covariance_count": self.non_finite_covariance_count,
            "input_listing_count": self.input_listing_count,
            "iteration_count": self.iteration_count,
            "numeric_tolerances": dict(self.numeric_tolerances),
            "risk_model_id": self.risk_model_id,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "production_eligible": self.production_eligible,
            "turnover_estimate": self.turnover_estimate,
        }


def _covariance_completeness(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> tuple[int, int]:
    """Return (missing_pair_count, non_finite_pair_count) for the required set.

    The required set is every ordered pair, including self-pairs (diagonal
    variance terms), for the exact listing set a portfolio calculation needs.
    """
    missing = 0
    non_finite = 0
    for left in listings:
        for right in listings:
            key = (left, right)
            if key not in covariances:
                missing += 1
            elif not isfinite(covariances[key]):
                non_finite += 1
    return missing, non_finite


def require_complete_covariance(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> None:
    """Fail closed instead of silently treating missing/non-finite covariance as zero.

    Portfolio variance, marginal risk, diversification, and risk-parity
    calculations must never substitute a plausible-looking zero for a
    covariance element that is absent or non-finite in the exact Selection
    calendar; doing so silently understates portfolio risk.
    """
    missing, non_finite = _covariance_completeness(listings, covariances)
    if missing or non_finite:
        raise ValueError(
            "incomplete covariance matrix: "
            f"{missing} missing pair(s), {non_finite} non-finite value(s) out of "
            f"{len(listings) * len(listings)} required pairs for the exact listing set"
        )


def validate_weights(weights: dict[str, float], constraints: PortfolioConstraints) -> None:
    if not weights:
        raise ValueError("weights are required")
    total = sum(weights.values())
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("weights must sum to 1")
    for isin, weight in weights.items():
        if constraints.long_only and weight < 0:
            raise ValueError(f"negative weight for {isin}")
        if weight < constraints.min_weight:
            raise ValueError(f"weight below minimum for {isin}")
        if weight > constraints.max_weight:
            raise ValueError(f"weight above maximum for {isin}")


def equal_weight_seed(isins: list[str], constraints: PortfolioConstraints) -> dict[str, float]:
    if not isins:
        raise ValueError("at least one ISIN is required")
    weight = 1.0 / len(isins)
    weights = {isin: weight for isin in sorted(isins)}
    validate_weights(weights, constraints)
    return weights


def exact_candidate_count(listing_count: int, grid_step: float) -> int:
    """Return the exact number of grid candidates for a listing count and grid step."""
    if not 0 < grid_step <= 1:
        raise ValueError("grid_step must be in (0, 1]")
    steps = round(1.0 / grid_step)
    if not isclose(steps * grid_step, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("grid_step must divide 1")
    return comb(listing_count + steps - 1, steps)


def is_candidate_limit_exceeded(listing_count: int, grid_step: float) -> bool:
    """Return whether the exact grid enumeration exceeds MAX_EXACT_WEIGHT_CANDIDATES."""
    return exact_candidate_count(listing_count, grid_step) > MAX_EXACT_WEIGHT_CANDIDATES


def resolve_actual_optimizer_method(objective: str, listing_count: int, grid_step: float) -> str:
    """Return the method actually executed, detecting a candidate-limit fallback.

    Pure and deterministic: depends only on the objective, listing count, and
    grid step, never on the resulting weights, so a genuine optimum that
    coincidentally matches Equal Weight is never mistaken for a fallback.
    """
    if objective == "equal_weight" or objective not in GRID_OBJECTIVES:
        return objective
    if is_candidate_limit_exceeded(listing_count, grid_step):
        return EQUAL_WEIGHT_FALLBACK_METHOD
    return objective


def minimum_variance_two_asset_weight(
    *,
    left_variance: float,
    right_variance: float,
    covariance: float,
    constraints: PortfolioConstraints,
) -> dict[str, float]:
    denominator = left_variance + right_variance - (2 * covariance)
    raw_left = 0.5 if denominator == 0 else (right_variance - covariance) / denominator
    left = min(constraints.max_weight, max(constraints.min_weight, raw_left))
    right = 1.0 - left
    weights = {"left": left, "right": right}
    validate_weights(weights, constraints)
    return weights


def optimize_portfolio(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    expected_returns: Mapping[str, float],
    *,
    objective: str,
    constraints: PortfolioConstraints,
    risk_free_rate: float = 0.0,
    target_return: float | None = None,
    grid_step: float = 0.01,
    mode: str = BASELINE_SOLVER_MODE,
) -> dict[str, float]:
    if mode not in SOLVER_MODES:
        raise ValueError(f"unknown optimizer mode: {mode}")
    ordered = listing_keys(listings)
    if objective == "equal_weight":
        return equal_weight_seed([isin for isin, _, _ in ordered], constraints)

    if objective not in GRID_OBJECTIVES:
        raise ValueError(f"unknown optimization objective: {objective}")
    if objective == "target_return_minimum_variance" and target_return is None:
        raise ValueError("target_return is required")
    target_value = 0.0 if target_return is None else target_return

    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)

    if mode == PRODUCTION_SOLVER_MODE and objective in SOLVER_BACKED_OBJECTIVES:
        result = _solve_production_objective(ordered, covariances, objective, constraints)
        validate_weights(result, constraints)
        return result

    if mode == PRODUCTION_SOLVER_MODE and is_candidate_limit_exceeded(len(ordered), grid_step):
        raise ValueError(
            f"{CANDIDATE_LIMIT_EXCEEDED_REASON}: production mode requires a numerical solver "
            f"for {len(ordered)} listings at grid_step={grid_step}, which is not yet "
            "implemented; no production weights are produced for this request. Use "
            f"mode='{BASELINE_SOLVER_MODE}' for an explicitly labeled Equal Weight fallback."
        )

    candidates = _candidate_weights(ordered, constraints, grid_step=grid_step)
    if not candidates:
        raise ValueError("no feasible weights for constraints")

    feasible = [
        weights
        for weights in candidates
        if objective != "target_return_minimum_variance"
        or _portfolio_return(ordered, weights, expected_returns) >= target_value
    ]
    if not feasible:
        raise ValueError("no feasible weights satisfy target_return")

    if objective == "minimum_variance":
        best = min(
            feasible,
            key=lambda weights: (portfolio_variance(ordered, weights, covariances), weights),
        )
    elif objective == "maximum_sharpe":
        best = max(
            feasible,
            key=lambda weights: (
                _sharpe_score(ordered, weights, covariances, expected_returns, risk_free_rate),
                tuple(-weight for weight in weights),
            ),
        )
    elif objective == "target_return_minimum_variance":
        best = min(
            feasible,
            key=lambda weights: (
                portfolio_variance(ordered, weights, covariances),
                abs(_portfolio_return(ordered, weights, expected_returns) - target_value),
                weights,
            ),
        )
    elif objective == MAXIMUM_DIVERSIFICATION_OBJECTIVE:
        best = max(
            feasible,
            key=lambda weights: (
                _diversification_ratio(ordered, weights, covariances),
                tuple(-weight for weight in weights),
            ),
        )
    else:
        best = min(
            feasible,
            key=lambda weights: (
                _risk_parity_residual(ordered, weights, covariances),
                portfolio_variance(ordered, weights, covariances),
                weights,
            ),
        )
    result = {isin: weight for (isin, _, _), weight in zip(ordered, best, strict=True)}
    validate_weights(result, constraints)
    return result


def build_optimizer_diagnostics(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    expected_returns: Mapping[str, float],
    weights: Mapping[str, float],
    *,
    objective: str,
    constraints: PortfolioConstraints,
    optimizer_type: str = BASELINE_OPTIMIZER_TYPE,
    mode: str = BASELINE_SOLVER_MODE,
    grid_step: float | None = None,
    risk_model_id: str = "",
) -> JsonRow:
    if mode not in SOLVER_MODES:
        raise ValueError(f"unknown optimizer mode: {mode}")
    ordered = listing_keys(listings)
    covariances = covariance_map(covariance_rows)
    ordered_weights = tuple(float(weights[isin]) for isin, _, _ in ordered)
    expected_return = _portfolio_return(ordered, ordered_weights, expected_returns)
    violations = constraint_violations(weights, constraints)
    missing_covariances, non_finite_covariances = _covariance_completeness(ordered, covariances)
    solver_backed = mode == PRODUCTION_SOLVER_MODE and objective in SOLVER_BACKED_OBJECTIVES

    fallback_used = False
    fallback_reason = ""
    iteration_count = 1
    solver_name = optimizer_type
    solver_converged = True
    solver_backed_matches_weights = False
    if solver_backed and not (missing_covariances or non_finite_covariances):
        solver_outcome = _run_production_solver(ordered, covariances, objective, constraints)
        # Only trust the solver's own convergence/iteration stats when the
        # given weights actually match what it produced; otherwise these
        # weights came from a different computation (e.g. a baseline grid
        # result) and must not be misreported as solver-verified.
        solver_backed_matches_weights = all(
            abs(given - solved) < 1e-6
            for given, solved in zip(ordered_weights, solver_outcome.weights, strict=True)
        )
        if solver_backed_matches_weights:
            iteration_count = solver_outcome.iteration_count
            solver_name = PGD_SOLVER_NAME
            solver_converged = solver_outcome.converged
    if not solver_backed_matches_weights and objective in GRID_OBJECTIVES and grid_step is not None:
        candidate_count = exact_candidate_count(len(ordered), grid_step)
        if candidate_count > MAX_EXACT_WEIGHT_CANDIDATES:
            fallback_used = True
            fallback_reason = CANDIDATE_LIMIT_EXCEEDED_REASON
        else:
            iteration_count = candidate_count
    actual_method = EQUAL_WEIGHT_FALLBACK_METHOD if fallback_used else objective

    if missing_covariances or non_finite_covariances:
        # Fail closed: an incomplete or non-finite covariance matrix must never
        # be silently treated as zero to produce a plausible-looking variance.
        covariance_condition = (
            "missing_covariance" if missing_covariances else "non_finite_covariance"
        )
        solver_status = "blocked_missing_covariance"
        portfolio_variance_value = float("nan")
        objective_value = float("nan")
    else:
        diagonal_values = [covariances[(listing, listing)] for listing in ordered]
        covariance_condition = (
            "zero_variance" if all(value <= 0 for value in diagonal_values) else "ok"
        )
        portfolio_variance_value = portfolio_variance(ordered, ordered_weights, covariances)
        objective_value = _objective_value(objective, ordered, ordered_weights, covariances)
        if solver_backed_matches_weights and not solver_converged:
            solver_status = "solver_not_converged"
        elif fallback_used:
            solver_status = CANDIDATE_LIMIT_EXCEEDED_REASON
        elif violations:
            solver_status = "constraint_violation"
        else:
            solver_status = "feasible"
    convergence_status = (
        "converged"
        if solver_status in {"feasible", CANDIDATE_LIMIT_EXCEEDED_REASON}
        else "not_converged"
    )
    production_eligible = (
        mode == PRODUCTION_SOLVER_MODE
        and not fallback_used
        and (not solver_backed_matches_weights or solver_converged)
        and missing_covariances == 0
        and non_finite_covariances == 0
        and not violations
    )
    diagnostics = OptimizerDiagnostics(
        optimizer_type=optimizer_type,
        optimizer_status=solver_status,
        requested_method=objective,
        actual_method=actual_method,
        solver_name=solver_name,
        solver_version=PGD_SOLVER_VERSION
        if solver_backed_matches_weights
        else OPTIMIZER_ALGORITHM_VERSION,
        solver_status=solver_status,
        convergence_status=convergence_status,
        objective_value=objective_value,
        expected_return=expected_return,
        portfolio_variance=portfolio_variance_value,
        constraint_violations=tuple(violations),
        constraint_residuals=_constraint_residuals(weights, constraints),
        bound_activity=_bound_activity(weights, constraints),
        covariance_condition=covariance_condition,
        missing_covariance_count=missing_covariances,
        non_finite_covariance_count=non_finite_covariances,
        input_listing_count=len(ordered),
        iteration_count=iteration_count,
        numeric_tolerances={
            "weight_sum_tolerance": WEIGHT_SUM_TOLERANCE,
            "grid_step": grid_step if grid_step is not None else 0.0,
        },
        risk_model_id=risk_model_id,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        production_eligible=production_eligible,
    )
    return diagnostics.as_dict()


def _constraint_residuals(
    weights: Mapping[str, float], constraints: PortfolioConstraints
) -> tuple[float, ...]:
    return tuple(
        max(0.0, constraints.min_weight - float(weights[isin]))
        + max(0.0, float(weights[isin]) - constraints.max_weight)
        for isin in sorted(weights)
    )


def _bound_activity(
    weights: Mapping[str, float], constraints: PortfolioConstraints, *, tolerance: float = 1e-9
) -> tuple[str, ...]:
    activity: list[str] = []
    for isin in sorted(weights):
        value = float(weights[isin])
        if isclose(value, constraints.min_weight, rel_tol=0.0, abs_tol=tolerance):
            activity.append(f"{isin}:min_weight")
        if isclose(value, constraints.max_weight, rel_tol=0.0, abs_tol=tolerance):
            activity.append(f"{isin}:max_weight")
    return tuple(activity)


def build_target_weight_rows(
    listings: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    objective: str,
    portfolio_id: str,
    constraints: PortfolioConstraints,
    diagnostics: Mapping[str, Any] | None = None,
) -> list[JsonRow]:
    by_isin = {str(row["isin"]): row for row in listings}
    metadata = json.dumps(constraints.as_dict(), sort_keys=True)
    diagnostic_text = json.dumps(dict(diagnostics or {}), sort_keys=True)
    return [
        {
            "evaluation_id": evaluation_id,
            "objective": objective,
            "portfolio_id": portfolio_id,
            "isin": isin,
            "exchange": str(by_isin[isin]["exchange"]),
            "code": str(by_isin[isin]["code"]),
            "weight": float(weights[isin]),
            "constraints": metadata,
            "diagnostics": diagnostic_text,
        }
        for isin in sorted(weights)
    ]


def write_optimized_weights(
    paths: LakePaths,
    *,
    evaluation_id: str,
    objective: str,
    portfolio_id: str,
    constraints: PortfolioConstraints,
    risk_free_rate: float = 0.0,
    target_return: float | None = None,
    grid_step: float = 0.01,
    risk_budget_tolerance: float = 1e-6,
) -> list[JsonRow]:
    matrix_rows = read_rows(paths.gold_return_matrix(evaluation_id))
    listings = listing_rows(matrix_rows)
    covariance_rows = read_covariances(paths, listings)
    expected_returns = _expected_returns(matrix_rows)
    weights = optimize_portfolio(
        listings,
        covariance_rows,
        expected_returns,
        objective=objective,
        constraints=constraints,
        risk_free_rate=risk_free_rate,
        target_return=target_return,
        grid_step=grid_step,
    )
    ordered = listing_keys(listings)
    ordered_weights = tuple(weights[isin] for isin, _, _ in ordered)
    diagnostics: JsonRow = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        expected_returns,
        weights,
        objective=objective,
        constraints=constraints,
        grid_step=grid_step,
    )
    diagnostics.update(
        {
            "risk_free_rate": risk_free_rate,
            "target_return": target_return,
            "expected_return": _portfolio_return(ordered, ordered_weights, expected_returns),
        }
    )
    if objective in RISK_PARITY_OBJECTIVES:
        risk_rows = build_risk_contribution_rows(
            listings,
            covariance_rows,
            weights,
            evaluation_id=evaluation_id,
            objective=objective,
            portfolio_id=portfolio_id,
            tolerance=risk_budget_tolerance,
        )
        diagnostics["risk_parity_residual"] = _risk_contribution_residual(risk_rows)
        diagnostics["convergence_status"] = (
            "converged"
            if float(diagnostics["risk_parity_residual"]) <= risk_budget_tolerance
            else "not_converged"
        )
    else:
        risk_rows = []
    rows = build_target_weight_rows(
        listings,
        weights,
        evaluation_id=evaluation_id,
        objective=objective,
        portfolio_id=portfolio_id,
        constraints=constraints,
        diagnostics=diagnostics,
    )
    existing = [
        row
        for row in read_rows(paths.gold_optimized_weights(objective, evaluation_id))
        if str(row["portfolio_id"]) != portfolio_id
    ]
    write_rows(
        paths.gold_optimized_weights(objective, evaluation_id),
        sorted([*existing, *rows], key=lambda row: (str(row["portfolio_id"]), str(row["isin"]))),
    )
    if risk_rows:
        existing_risk_rows = [
            row
            for row in read_rows(paths.gold_risk_contributions(objective, evaluation_id))
            if str(row["portfolio_id"]) != portfolio_id
        ]
        write_rows(
            paths.gold_risk_contributions(objective, evaluation_id),
            sorted(
                [*existing_risk_rows, *risk_rows],
                key=lambda row: (str(row["portfolio_id"]), str(row["isin"])),
            ),
        )
    return rows


def _hrp_clustering(
    ordered: Sequence[ListingKey], covariances: Mapping[tuple[ListingKey, ListingKey], float]
) -> tuple[tuple[int, ...], list[list[float]], tuple[Any, ...]]:
    """Shared True HRP clustering step: dense matrix, linkage, quasi-diagonal order."""
    matrix = dense_covariance_matrix(ordered, covariances)
    distance_matrix = correlation_distance_matrix(matrix)
    linkage = single_linkage(distance_matrix)
    order = quasi_diagonal_order(linkage, len(ordered))
    return order, matrix, linkage


def hierarchical_risk_parity_weights(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    constraints: PortfolioConstraints,
) -> dict[str, float]:
    """True Hierarchical Risk Parity: correlation-distance clustering, quasi-diagonal
    ordering, and recursive bisection with inverse-variance intra-cluster weights.

    See `hierarchical_risk_parity_baseline_weights` for the deterministic
    midpoint-split baseline this replaces; that baseline must never be
    labeled `hierarchical_risk_parity` in a production-facing artifact.
    """
    ordered = listing_keys(listings)
    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    order, matrix, _linkage = _hrp_clustering(ordered, covariances)
    raw_index_weights, _splits = recursive_bisection(order, matrix)
    raw_weights = [raw_index_weights[index] for index in range(len(ordered))]
    projected = project_capped_simplex(
        raw_weights, min_weight=constraints.min_weight, max_weight=constraints.max_weight
    )
    weights = {ordered[index][0]: value for index, value in enumerate(projected)}
    validate_weights(weights, constraints)
    return weights


def hierarchical_risk_parity_baseline_weights(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    constraints: PortfolioConstraints,
) -> dict[str, float]:
    """Deterministic midpoint-recursive-variance baseline (pre-PR61 behavior).

    Splits listings by canonical ISIN order rather than any correlation-based
    clustering. Retained only for development and comparison; must always be
    reported under the `hierarchical_risk_parity_baseline` label, never as
    `hierarchical_risk_parity`.
    """
    ordered = listing_keys(listings)
    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    raw_weights = _recursive_hrp_baseline_weights(ordered, covariances)
    capped = {
        isin: min(constraints.max_weight, max(constraints.min_weight, raw_weights[isin]))
        for isin, _, _ in ordered
    }
    total = sum(capped.values())
    if total == 0:
        raise ValueError("no feasible HRP weights")
    weights = {isin: weight / total for isin, weight in capped.items()}
    validate_weights(weights, constraints)
    return weights


def build_hrp_cluster_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    *,
    evaluation_id: str,
    portfolio_id: str,
) -> list[JsonRow]:
    ordered = listing_keys(listings)
    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    order, matrix, _linkage = _hrp_clustering(ordered, covariances)
    _weights, splits = recursive_bisection(order, matrix)
    ordered_isins = ",".join(ordered[index][0] for index in order)
    rows: list[JsonRow] = []
    for split in splits:
        rows.append(
            {
                "evaluation_id": evaluation_id,
                "portfolio_id": portfolio_id,
                "cluster_id": split.cluster_id,
                "left_cluster": ",".join(ordered[index][0] for index in split.left_members),
                "right_cluster": ",".join(ordered[index][0] for index in split.right_members),
                "cluster_variance": split.left_variance + split.right_variance,
                "allocation": split.left_allocation,
                "ordered_isins": ordered_isins,
                "linkage_method": HRP_LINKAGE_METHOD,
                "tie_breaking_policy": HRP_TIE_BREAKING_POLICY,
                "algorithm_version": HRP_ALGORITHM_VERSION,
            }
        )
    return rows


def build_hrp_linkage_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    *,
    evaluation_id: str,
    portfolio_id: str,
) -> list[JsonRow]:
    """Persist the single-linkage dendrogram itself (the merge history)."""
    ordered = listing_keys(listings)
    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    _order, _matrix, linkage = _hrp_clustering(ordered, covariances)
    leaf_count = len(ordered)

    def label(cluster_id: int) -> str:
        return ordered[cluster_id][0] if cluster_id < leaf_count else f"cluster-{cluster_id}"

    return [
        {
            "evaluation_id": evaluation_id,
            "portfolio_id": portfolio_id,
            "step_index": step_index,
            "left_cluster_id": label(step.left),
            "right_cluster_id": label(step.right),
            "distance": step.distance,
            "size": step.size,
            "linkage_method": HRP_LINKAGE_METHOD,
            "tie_breaking_policy": HRP_TIE_BREAKING_POLICY,
            "algorithm_version": HRP_ALGORITHM_VERSION,
        }
        for step_index, step in enumerate(linkage, start=1)
    ]


def write_hierarchical_risk_parity(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    constraints: PortfolioConstraints,
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow]]:
    matrix_rows = read_rows(paths.gold_return_matrix(evaluation_id))
    listings = listing_rows(matrix_rows)
    covariance_rows = read_covariances(paths, listings)
    weights = hierarchical_risk_parity_weights(listings, covariance_rows, constraints)
    weight_rows = build_target_weight_rows(
        listings,
        weights,
        evaluation_id=evaluation_id,
        objective=HIERARCHICAL_RISK_PARITY_OBJECTIVE,
        portfolio_id=portfolio_id,
        constraints=constraints,
        diagnostics={
            **build_optimizer_diagnostics(
                listings,
                covariance_rows,
                {},
                weights,
                objective=HIERARCHICAL_RISK_PARITY_OBJECTIVE,
                constraints=constraints,
            ),
            "ordered_isins": ",".join(sorted(weights)),
            "linkage_method": HRP_LINKAGE_METHOD,
            "tie_breaking_policy": HRP_TIE_BREAKING_POLICY,
        },
    )
    cluster_rows = build_hrp_cluster_rows(
        listings,
        covariance_rows,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
    )
    linkage_rows = build_hrp_linkage_rows(
        listings,
        covariance_rows,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
    )
    _replace_portfolio_rows(
        paths.gold_optimized_weights(HIERARCHICAL_RISK_PARITY_OBJECTIVE, evaluation_id),
        portfolio_id,
        weight_rows,
    )
    _replace_portfolio_rows(paths.gold_hrp_clusters(evaluation_id), portfolio_id, cluster_rows)
    _replace_portfolio_rows(paths.gold_hrp_linkage(evaluation_id), portfolio_id, linkage_rows)
    return weight_rows, cluster_rows, linkage_rows


def write_hierarchical_risk_parity_baseline(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    constraints: PortfolioConstraints,
) -> list[JsonRow]:
    """Write the deterministic midpoint-split HRP baseline for development/comparison.

    Always labeled `hierarchical_risk_parity_baseline`; never the production
    `hierarchical_risk_parity` objective (see PR61 amendment).
    """
    matrix_rows = read_rows(paths.gold_return_matrix(evaluation_id))
    listings = listing_rows(matrix_rows)
    covariance_rows = read_covariances(paths, listings)
    weights = hierarchical_risk_parity_baseline_weights(listings, covariance_rows, constraints)
    weight_rows = build_target_weight_rows(
        listings,
        weights,
        evaluation_id=evaluation_id,
        objective=HIERARCHICAL_RISK_PARITY_BASELINE_OBJECTIVE,
        portfolio_id=portfolio_id,
        constraints=constraints,
        diagnostics={
            **build_optimizer_diagnostics(
                listings,
                covariance_rows,
                {},
                weights,
                objective=HIERARCHICAL_RISK_PARITY_BASELINE_OBJECTIVE,
                constraints=constraints,
            ),
            "ordered_isins": ",".join(sorted(weights)),
        },
    )
    _replace_portfolio_rows(
        paths.gold_optimized_weights(HIERARCHICAL_RISK_PARITY_BASELINE_OBJECTIVE, evaluation_id),
        portfolio_id,
        weight_rows,
    )
    return weight_rows


def _aligned_return_matrix(
    listings: Sequence[ListingKey], return_rows: Sequence[Mapping[str, Any]]
) -> list[list[float]]:
    """Build a dense `T x N` (dates x listings) matrix of aligned historical returns.

    Only dates common to every listing are included, matching the "exact
    Selection calendar" alignment used elsewhere (e.g. `require_complete_covariance`).
    """
    by_listing: dict[ListingKey, dict[str, float]] = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, {})[str(row["date"])] = float(row["return"])
    common_dates: set[str] | None = None
    for listing in listings:
        dates = set(by_listing.get(listing, {}))
        common_dates = dates if common_dates is None else common_dates & dates
    ordered_dates = sorted(common_dates or set())
    return [[by_listing[listing][date] for listing in listings] for date in ordered_dates]


def minimum_cvar_weights(
    listings: Sequence[Mapping[str, Any]],
    return_rows: Sequence[Mapping[str, Any]],
    constraints: PortfolioConstraints,
    *,
    confidence_level: float = DEFAULT_CVAR_CONFIDENCE_LEVEL,
) -> dict[str, float]:
    """Historical Minimum CVaR: minimize Conditional Value-at-Risk over long-only,
    bounded weights via the Rockafellar-Uryasev projected-subgradient solver.

    Unlike the covariance-based objectives, this needs the full aligned
    historical return matrix (the empirical loss distribution), not a
    covariance matrix, so it is a standalone entry point rather than an
    `optimize_portfolio` objective.
    """
    ordered = listing_keys(listings)
    returns_matrix = _aligned_return_matrix(ordered, return_rows)
    if len(returns_matrix) < 2:
        raise ValueError("at least two common historical return observations are required")
    outcome = solve_minimum_cvar(
        returns_matrix,
        confidence_level=confidence_level,
        min_weight=constraints.min_weight,
        max_weight=constraints.max_weight,
    )
    if not outcome.converged:
        raise ValueError(
            f"solver_not_converged: the {CVAR_SOLVER_NAME} solver did not converge for "
            f"minimum_cvar within {outcome.iteration_count} iterations; no production "
            "weights are produced for this request"
        )
    weights = {isin: weight for (isin, _, _), weight in zip(ordered, outcome.weights, strict=True)}
    validate_weights(weights, constraints)
    return weights


def build_minimum_cvar_diagnostics(
    listings: Sequence[Mapping[str, Any]],
    return_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    constraints: PortfolioConstraints,
    confidence_level: float = DEFAULT_CVAR_CONFIDENCE_LEVEL,
) -> JsonRow:
    """Report VaR/CVaR and solver diagnostics for an already-computed minimum-CVaR
    portfolio. Re-runs the solver and only trusts its convergence/iteration stats
    when the given weights numerically match its own output (see PR60's
    `build_optimizer_diagnostics` for the same weights-provenance safeguard).
    """
    ordered = listing_keys(listings)
    returns_matrix = _aligned_return_matrix(ordered, return_rows)
    ordered_weights = tuple(float(weights[isin]) for isin, _, _ in ordered)
    violations = constraint_violations(weights, constraints)
    outcome = (
        solve_minimum_cvar(
            returns_matrix,
            confidence_level=confidence_level,
            min_weight=constraints.min_weight,
            max_weight=constraints.max_weight,
        )
        if len(returns_matrix) >= 2
        else None
    )
    solver_matches_weights = outcome is not None and all(
        abs(given - solved) < 1e-6
        for given, solved in zip(ordered_weights, outcome.weights, strict=True)
    )
    if solver_matches_weights and outcome is not None:
        var, cvar, iteration_count, converged = (
            outcome.var,
            outcome.cvar,
            outcome.iteration_count,
            outcome.converged,
        )
    else:
        losses = [
            -sum(value * weight for value, weight in zip(scenario, ordered_weights, strict=True))
            for scenario in returns_matrix
        ]
        var, cvar, _tail_count = historical_var_and_cvar(losses, confidence_level)
        iteration_count, converged = 0, False
    if not solver_matches_weights:
        solver_status = "unverified"
    elif not converged:
        solver_status = "solver_not_converged"
    elif violations:
        solver_status = "constraint_violation"
    else:
        solver_status = "feasible"
    production_eligible = solver_matches_weights and converged and not violations
    return {
        "optimizer_type": PRODUCTION_OPTIMIZER_TYPE,
        "optimizer_status": solver_status,
        "requested_method": MINIMUM_CVAR_OBJECTIVE,
        "actual_method": MINIMUM_CVAR_OBJECTIVE,
        "solver_name": CVAR_SOLVER_NAME,
        "solver_version": CVAR_SOLVER_VERSION,
        "solver_status": solver_status,
        "convergence_status": "converged" if converged else "not_converged",
        "objective_value": cvar,
        "var": var,
        "cvar": cvar,
        "confidence_level": confidence_level,
        "constraint_violations": list(violations),
        "input_listing_count": len(ordered),
        "iteration_count": iteration_count,
        "fallback_used": False,
        "fallback_reason": "",
        "production_eligible": production_eligible,
    }


def write_minimum_cvar_portfolio(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    constraints: PortfolioConstraints,
    confidence_level: float = DEFAULT_CVAR_CONFIDENCE_LEVEL,
) -> list[JsonRow]:
    matrix_rows = read_rows(paths.gold_return_matrix(evaluation_id))
    listings = listing_rows(matrix_rows)
    weights = minimum_cvar_weights(
        listings, matrix_rows, constraints, confidence_level=confidence_level
    )
    weight_rows = build_target_weight_rows(
        listings,
        weights,
        evaluation_id=evaluation_id,
        objective=MINIMUM_CVAR_OBJECTIVE,
        portfolio_id=portfolio_id,
        constraints=constraints,
        diagnostics=build_minimum_cvar_diagnostics(
            listings,
            matrix_rows,
            weights,
            constraints=constraints,
            confidence_level=confidence_level,
        ),
    )
    _replace_portfolio_rows(
        paths.gold_optimized_weights(MINIMUM_CVAR_OBJECTIVE, evaluation_id),
        portfolio_id,
        weight_rows,
    )
    return weight_rows


def shrinkage_minimum_variance_weights(
    listings: Sequence[Mapping[str, Any]],
    return_rows: Sequence[Mapping[str, Any]],
    constraints: PortfolioConstraints,
    *,
    estimator: str = "ledoit_wolf",
    max_iterations: int = 30_000,
) -> dict[str, float]:
    """Minimum Variance using a camovar.risk_model shrinkage/EWMA covariance estimate.

    Unlike `optimize_portfolio`'s solver-backed `minimum_variance` (which uses
    the raw sample covariance from Gold pairwise covariance rows), this wires
    `camovar.risk_model`'s estimators through to the same PR60 projected-
    gradient-descent solver -- the wiring noted as a follow-up in
    docs/lake_contracts.md and used by PR63's Balanced ensemble. Shrinkage
    covariance entries are typically much smaller in magnitude than raw Gold
    covariance rows, so this uses a larger default iteration budget than the
    solver's own default to reach the same absolute convergence tolerance.
    """
    ordered = listing_keys(listings)
    risk_model = estimate_risk_model(return_rows, listings=ordered, estimator=estimator)
    if not risk_model.diagnostics.production_eligible:
        raise ValueError(
            "risk_model_not_production_eligible: "
            f"{', '.join(risk_model.diagnostics.availability_reasons)}"
        )
    covariances = {
        (risk_model.listings[i], risk_model.listings[j]): risk_model.covariance[i][j]
        for i in range(len(risk_model.listings))
        for j in range(len(risk_model.listings))
    }
    outcome = solve_minimum_variance(
        ordered,
        covariances,
        min_weight=constraints.min_weight,
        max_weight=constraints.max_weight,
        max_iterations=max_iterations,
    )
    if not outcome.converged:
        raise ValueError(
            f"solver_not_converged: the {PGD_SOLVER_NAME} solver did not converge for "
            f"shrinkage minimum_variance within {outcome.iteration_count} iterations; no "
            "production weights are produced for this request"
        )
    weights = {isin: weight for (isin, _, _), weight in zip(ordered, outcome.weights, strict=True)}
    validate_weights(weights, constraints)
    return weights


def build_diversification_metric_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    portfolio_id: str,
) -> list[JsonRow]:
    ordered = listing_keys(listings)
    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    ordered_weights = tuple(float(weights[isin]) for isin, _, _ in ordered)
    ratio = _diversification_ratio(ordered, ordered_weights, covariances)
    portfolio_variance_value = portfolio_variance(ordered, ordered_weights, covariances)
    asset_volatility = sum(
        weight * (max(0.0, covariances[(listing, listing)]) ** 0.5)
        for listing, weight in zip(ordered, ordered_weights, strict=True)
    )
    return [
        {
            "evaluation_id": evaluation_id,
            "portfolio_id": portfolio_id,
            "diversification_ratio": ratio,
            "portfolio_volatility": max(0.0, portfolio_variance_value) ** 0.5,
            "weighted_asset_volatility": asset_volatility,
            "diagnostics": json.dumps({"objective": MAXIMUM_DIVERSIFICATION_OBJECTIVE}),
        }
    ]


def write_maximum_diversification(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    constraints: PortfolioConstraints,
    grid_step: float = 0.01,
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix_rows = read_rows(paths.gold_return_matrix(evaluation_id))
    listings = listing_rows(matrix_rows)
    covariance_rows = read_covariances(paths, listings)
    weights = optimize_portfolio(
        listings,
        covariance_rows,
        {},
        objective=MAXIMUM_DIVERSIFICATION_OBJECTIVE,
        constraints=constraints,
        grid_step=grid_step,
    )
    weight_rows = build_target_weight_rows(
        listings,
        weights,
        evaluation_id=evaluation_id,
        objective=MAXIMUM_DIVERSIFICATION_OBJECTIVE,
        portfolio_id=portfolio_id,
        constraints=constraints,
        diagnostics=build_optimizer_diagnostics(
            listings,
            covariance_rows,
            {},
            weights,
            objective=MAXIMUM_DIVERSIFICATION_OBJECTIVE,
            constraints=constraints,
            grid_step=grid_step,
        ),
    )
    metric_rows = build_diversification_metric_rows(
        listings,
        covariance_rows,
        weights,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
    )
    _replace_portfolio_rows(
        paths.gold_optimized_weights(MAXIMUM_DIVERSIFICATION_OBJECTIVE, evaluation_id),
        portfolio_id,
        weight_rows,
    )
    _replace_portfolio_rows(
        paths.gold_diversification_metrics(evaluation_id), portfolio_id, metric_rows
    )
    return weight_rows, metric_rows


def build_risk_contribution_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    objective: str,
    portfolio_id: str,
    tolerance: float = 1e-6,
) -> list[JsonRow]:
    ordered = listing_keys(listings)
    covariances = covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    ordered_weights = tuple(float(weights[isin]) for isin, _, _ in ordered)
    portfolio_variance_value = portfolio_variance(ordered, ordered_weights, covariances)
    target_budget = 1.0 / len(ordered)
    contribution_rows: list[JsonRow] = []
    for listing, weight in zip(ordered, ordered_weights, strict=True):
        marginal = _marginal_risk_contribution(listing, ordered, ordered_weights, covariances)
        absolute = weight * marginal
        percent = 0.0 if portfolio_variance_value == 0 else absolute / portfolio_variance_value
        contribution_rows.append(
            {
                "evaluation_id": evaluation_id,
                "objective": objective,
                "portfolio_id": portfolio_id,
                "isin": listing[0],
                "exchange": listing[1],
                "code": listing[2],
                "weight": weight,
                "marginal_risk_contribution": marginal,
                "absolute_risk_contribution": absolute,
                "percent_risk_contribution": percent,
                "target_risk_budget": target_budget,
                "risk_budget_residual": percent - target_budget,
                "portfolio_variance": portfolio_variance_value,
            }
        )
    residual = _risk_contribution_residual(contribution_rows)
    status = "converged" if residual <= tolerance else "not_converged"
    return [
        {
            **row,
            "objective_residual": residual,
            "convergence_status": status,
        }
        for row in contribution_rows
    ]


def listing_keys(listings: Sequence[Mapping[str, Any]]) -> list[ListingKey]:
    keys = sorted({(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in listings})
    if not keys:
        raise ValueError("at least one listing is required")
    return keys


def listing_rows(matrix_rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    return [
        {"isin": isin, "exchange": exchange, "code": code}
        for isin, exchange, code in listing_keys(matrix_rows)
    ]


def _replace_portfolio_rows(
    path: Any, portfolio_id: str, rows: Sequence[Mapping[str, Any]]
) -> None:
    existing = [row for row in read_rows(path) if str(row["portfolio_id"]) != portfolio_id]
    write_rows(
        path,
        sorted(
            [*existing, *rows], key=lambda row: (str(row["portfolio_id"]), str(row.get("isin", "")))
        ),
    )


def _expected_returns(matrix_rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    returns: dict[str, list[float]] = {}
    for row in matrix_rows:
        returns.setdefault(str(row["isin"]), []).append(float(row["return"]))
    return {isin: sum(values) / len(values) for isin, values in returns.items()}


def read_covariances(paths: LakePaths, listings: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    rows: list[JsonRow] = []
    for isin, exchange, _ in listing_keys(listings):
        rows.extend(read_rows(paths.gold_covariance(exchange, isin)))
    return rows


def covariance_map(
    covariance_rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[ListingKey, ListingKey], float]:
    values: dict[tuple[ListingKey, ListingKey], float] = {}
    for row in covariance_rows:
        left = (str(row["left_isin"]), str(row["left_exchange"]), str(row["left_code"]))
        right = (str(row["right_isin"]), str(row["right_exchange"]), str(row["right_code"]))
        values[(left, right)] = float(row["covariance"])
    return values


def _run_production_solver(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
    objective: str,
    constraints: PortfolioConstraints,
) -> SolverOutcome:
    if objective == "minimum_variance":
        return solve_minimum_variance(
            listings,
            covariances,
            min_weight=constraints.min_weight,
            max_weight=constraints.max_weight,
        )
    return solve_equal_risk_contribution(
        listings,
        covariances,
        min_weight=constraints.min_weight,
        max_weight=constraints.max_weight,
    )


def _solve_production_objective(
    listings: Sequence[ListingKey],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
    objective: str,
    constraints: PortfolioConstraints,
) -> dict[str, float]:
    outcome = _run_production_solver(listings, covariances, objective, constraints)
    if not outcome.converged:
        raise ValueError(
            f"solver_not_converged: the {PGD_SOLVER_NAME} solver did not converge for "
            f"objective {objective!r} within {outcome.iteration_count} iterations; no "
            "production weights are produced for this request"
        )
    return {isin: weight for (isin, _, _), weight in zip(listings, outcome.weights, strict=True)}


def constraint_violations(
    weights: Mapping[str, float], constraints: PortfolioConstraints
) -> list[str]:
    violations: list[str] = []
    total = sum(float(weight) for weight in weights.values())
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        violations.append("weights_do_not_sum_to_one")
    for isin, weight in sorted(weights.items()):
        value = float(weight)
        if constraints.long_only and value < 0:
            violations.append(f"negative_weight:{isin}")
        if value < constraints.min_weight:
            violations.append(f"below_min_weight:{isin}")
        if value > constraints.max_weight:
            violations.append(f"above_max_weight:{isin}")
    return violations


def _objective_value(
    objective: str,
    listings: Sequence[ListingKey],
    weights: Sequence[float],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> float:
    if objective == MAXIMUM_DIVERSIFICATION_OBJECTIVE:
        return _diversification_ratio(listings, weights, covariances)
    if objective in RISK_PARITY_OBJECTIVES:
        return _risk_parity_residual(listings, weights, covariances)
    return portfolio_variance(listings, weights, covariances)


def _candidate_weights(
    listings: Sequence[ListingKey], constraints: PortfolioConstraints, *, grid_step: float
) -> list[tuple[float, ...]]:
    if exact_candidate_count(len(listings), grid_step) > MAX_EXACT_WEIGHT_CANDIDATES:
        return _fallback_candidate_weights(listings, constraints)
    steps = round(1.0 / grid_step)
    candidates: list[tuple[float, ...]] = []
    for integers in _weight_integer_partitions(len(listings), steps):
        weights = tuple(round(item * grid_step, 12) for item in integers)
        try:
            validate_weights(
                {isin: weight for (isin, _, _), weight in zip(listings, weights, strict=True)},
                constraints,
            )
        except ValueError:
            continue
        candidates.append(weights)
    return candidates


def _fallback_candidate_weights(
    listings: Sequence[ListingKey], constraints: PortfolioConstraints
) -> list[tuple[float, ...]]:
    try:
        weights = equal_weight_seed([isin for isin, _, _ in listings], constraints)
    except ValueError:
        return []
    return [tuple(weights[isin] for isin, _, _ in listings)]


def _weight_integer_partitions(count: int, total: int) -> list[tuple[int, ...]]:
    if count == 1:
        return [(total,)]
    rows: list[tuple[int, ...]] = []
    for head in range(total + 1):
        rows.extend((head, *tail) for tail in _weight_integer_partitions(count - 1, total - head))
    return rows


def _portfolio_return(
    listings: Sequence[ListingKey], weights: Sequence[float], expected_returns: Mapping[str, float]
) -> float:
    return sum(
        expected_returns.get(isin, 0.0) * weight
        for (isin, _, _), weight in zip(listings, weights, strict=True)
    )


def portfolio_variance(
    listings: Sequence[ListingKey],
    weights: Sequence[float],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> float:
    variance = 0.0
    for left, left_weight in zip(listings, weights, strict=True):
        for right, right_weight in zip(listings, weights, strict=True):
            variance += left_weight * right_weight * covariances[(left, right)]
    return variance


def _diversification_ratio(
    listings: Sequence[ListingKey],
    weights: Sequence[float],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> float:
    variance_value = portfolio_variance(listings, weights, covariances)
    if variance_value <= 0:
        return 0.0
    weighted_volatility = sum(
        weight * (max(0.0, covariances[(listing, listing)]) ** 0.5)
        for listing, weight in zip(listings, weights, strict=True)
    )
    return float(weighted_volatility / (variance_value**0.5))


def _cluster_variance(
    listings: Sequence[ListingKey], covariances: Mapping[tuple[ListingKey, ListingKey], float]
) -> float:
    """Equal-weight cluster variance used by the baseline only (see PR61)."""
    if not listings:
        return 0.0
    weight = 1.0 / len(listings)
    return portfolio_variance(listings, [weight] * len(listings), covariances)


def _recursive_hrp_baseline_weights(
    listings: Sequence[ListingKey], covariances: Mapping[tuple[ListingKey, ListingKey], float]
) -> dict[str, float]:
    if len(listings) == 1:
        return {listings[0][0]: 1.0}
    midpoint = len(listings) // 2
    left = list(listings[:midpoint])
    right = list(listings[midpoint:])
    left_variance = _cluster_variance(left, covariances)
    right_variance = _cluster_variance(right, covariances)
    total = left_variance + right_variance
    left_allocation = 0.5 if total == 0 else right_variance / total
    right_allocation = 1.0 - left_allocation
    weights: dict[str, float] = {}
    for isin, weight in _recursive_hrp_baseline_weights(left, covariances).items():
        weights[isin] = weight * left_allocation
    for isin, weight in _recursive_hrp_baseline_weights(right, covariances).items():
        weights[isin] = weight * right_allocation
    return weights


def _marginal_risk_contribution(
    listing: ListingKey,
    listings: Sequence[ListingKey],
    weights: Sequence[float],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> float:
    return sum(
        weight * covariances[(listing, right)]
        for right, weight in zip(listings, weights, strict=True)
    )


def _risk_parity_residual(
    listings: Sequence[ListingKey],
    weights: Sequence[float],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
) -> float:
    variance = portfolio_variance(listings, weights, covariances)
    target = 1.0 / len(listings)
    residual = 0.0
    for listing, weight in zip(listings, weights, strict=True):
        marginal = _marginal_risk_contribution(listing, listings, weights, covariances)
        percent = 0.0 if variance == 0 else (weight * marginal) / variance
        residual += (percent - target) ** 2
    return residual


def _risk_contribution_residual(rows: Sequence[Mapping[str, Any]]) -> float:
    return sum(float(row["risk_budget_residual"]) ** 2 for row in rows)


def _sharpe_score(
    listings: Sequence[ListingKey],
    weights: Sequence[float],
    covariances: Mapping[tuple[ListingKey, ListingKey], float],
    expected_returns: Mapping[str, float],
    risk_free_rate: float,
) -> float:
    variance = portfolio_variance(listings, weights, covariances)
    if variance <= 0:
        return 0.0
    return float(
        (_portfolio_return(listings, weights, expected_returns) - risk_free_rate) / (variance**0.5)
    )
