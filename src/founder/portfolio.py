"""Portfolio constraint helpers and deterministic optimization objectives."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import comb, isclose, isfinite
from typing import Any

from founder.paths import LakePaths
from founder.table_io import JsonRow, read_rows, write_rows

ListingKey = tuple[str, str, str]
MAX_EXACT_WEIGHT_CANDIDATES = 20_000
RISK_PARITY_OBJECTIVES = {"risk_parity", "equal_risk_contribution"}
MAXIMUM_DIVERSIFICATION_OBJECTIVE = "maximum_diversification"
BASELINE_OPTIMIZER_TYPE = "deterministic_baseline"
PRODUCTION_OPTIMIZER_TYPE = "production_solver"


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
    objective_value: float
    expected_return: float
    portfolio_variance: float
    constraint_violations: tuple[str, ...]
    covariance_condition: str
    missing_covariance_count: int
    input_listing_count: int
    turnover_estimate: float = 0.0

    def as_dict(self) -> JsonRow:
        return {
            "optimizer_type": self.optimizer_type,
            "optimizer_status": self.optimizer_status,
            "objective_value": self.objective_value,
            "expected_return": self.expected_return,
            "portfolio_variance": self.portfolio_variance,
            "constraint_violations": list(self.constraint_violations),
            "covariance_condition": self.covariance_condition,
            "missing_covariance_count": self.missing_covariance_count,
            "input_listing_count": self.input_listing_count,
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
) -> dict[str, float]:
    ordered = _listing_keys(listings)
    if objective == "equal_weight":
        return equal_weight_seed([isin for isin, _, _ in ordered], constraints)

    if objective not in {
        "minimum_variance",
        "maximum_sharpe",
        "target_return_minimum_variance",
        MAXIMUM_DIVERSIFICATION_OBJECTIVE,
        *RISK_PARITY_OBJECTIVES,
    }:
        raise ValueError(f"unknown optimization objective: {objective}")
    if objective == "target_return_minimum_variance" and target_return is None:
        raise ValueError("target_return is required")
    target_value = 0.0 if target_return is None else target_return

    covariances = _covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
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
            key=lambda weights: (_portfolio_variance(ordered, weights, covariances), weights),
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
                _portfolio_variance(ordered, weights, covariances),
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
                _portfolio_variance(ordered, weights, covariances),
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
) -> JsonRow:
    ordered = _listing_keys(listings)
    covariances = _covariance_map(covariance_rows)
    ordered_weights = tuple(float(weights[isin]) for isin, _, _ in ordered)
    expected_return = _portfolio_return(ordered, ordered_weights, expected_returns)
    violations = _constraint_violations(weights, constraints)
    missing_covariances, non_finite_covariances = _covariance_completeness(ordered, covariances)
    if missing_covariances or non_finite_covariances:
        # Fail closed: an incomplete or non-finite covariance matrix must never
        # be silently treated as zero to produce a plausible-looking variance.
        covariance_condition = (
            "missing_covariance" if missing_covariances else "non_finite_covariance"
        )
        optimizer_status = "blocked_missing_covariance"
        portfolio_variance = float("nan")
        objective_value = float("nan")
    else:
        diagonal_values = [covariances[(listing, listing)] for listing in ordered]
        covariance_condition = (
            "zero_variance" if all(value <= 0 for value in diagonal_values) else "ok"
        )
        optimizer_status = "feasible" if not violations else "constraint_violation"
        portfolio_variance = _portfolio_variance(ordered, ordered_weights, covariances)
        objective_value = _objective_value(objective, ordered, ordered_weights, covariances)
    diagnostics = OptimizerDiagnostics(
        optimizer_type=optimizer_type,
        optimizer_status=optimizer_status,
        objective_value=objective_value,
        expected_return=expected_return,
        portfolio_variance=portfolio_variance,
        constraint_violations=tuple(violations),
        covariance_condition=covariance_condition,
        missing_covariance_count=missing_covariances,
        input_listing_count=len(ordered),
    )
    return diagnostics.as_dict()


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
    listings = _listing_rows(matrix_rows)
    covariance_rows = _read_covariances(paths, listings)
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
    ordered = _listing_keys(listings)
    ordered_weights = tuple(weights[isin] for isin, _, _ in ordered)
    diagnostics: JsonRow = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        expected_returns,
        weights,
        objective=objective,
        constraints=constraints,
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


def hierarchical_risk_parity_weights(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    constraints: PortfolioConstraints,
) -> dict[str, float]:
    ordered = _listing_keys(listings)
    covariances = _covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    raw_weights = _recursive_hrp_weights(ordered, covariances)
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
    ordered = _listing_keys(listings)
    covariances = _covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    rows: list[JsonRow] = []
    for index, cluster in enumerate(_cluster_splits(ordered), start=1):
        left, right = cluster
        left_variance = _cluster_variance(left, covariances)
        right_variance = _cluster_variance(right, covariances)
        total = left_variance + right_variance
        allocation = 0.5 if total == 0 else right_variance / total
        rows.append(
            {
                "evaluation_id": evaluation_id,
                "portfolio_id": portfolio_id,
                "cluster_id": f"cluster-{index:03d}",
                "left_cluster": ",".join(item[0] for item in left),
                "right_cluster": ",".join(item[0] for item in right),
                "cluster_variance": left_variance + right_variance,
                "allocation": allocation,
                "ordered_isins": ",".join(item[0] for item in ordered),
            }
        )
    return rows


def write_hierarchical_risk_parity(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    constraints: PortfolioConstraints,
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix_rows = read_rows(paths.gold_return_matrix(evaluation_id))
    listings = _listing_rows(matrix_rows)
    covariance_rows = _read_covariances(paths, listings)
    weights = hierarchical_risk_parity_weights(listings, covariance_rows, constraints)
    weight_rows = build_target_weight_rows(
        listings,
        weights,
        evaluation_id=evaluation_id,
        objective="hierarchical_risk_parity",
        portfolio_id=portfolio_id,
        constraints=constraints,
        diagnostics={
            **build_optimizer_diagnostics(
                listings,
                covariance_rows,
                {},
                weights,
                objective="hierarchical_risk_parity",
                constraints=constraints,
            ),
            "ordered_isins": ",".join(sorted(weights)),
        },
    )
    cluster_rows = build_hrp_cluster_rows(
        listings,
        covariance_rows,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
    )
    _replace_portfolio_rows(
        paths.gold_optimized_weights("hierarchical_risk_parity", evaluation_id),
        portfolio_id,
        weight_rows,
    )
    _replace_portfolio_rows(paths.gold_hrp_clusters(evaluation_id), portfolio_id, cluster_rows)
    return weight_rows, cluster_rows


def build_diversification_metric_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    portfolio_id: str,
) -> list[JsonRow]:
    ordered = _listing_keys(listings)
    covariances = _covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    ordered_weights = tuple(float(weights[isin]) for isin, _, _ in ordered)
    ratio = _diversification_ratio(ordered, ordered_weights, covariances)
    portfolio_variance = _portfolio_variance(ordered, ordered_weights, covariances)
    asset_volatility = sum(
        weight * (max(0.0, covariances[(listing, listing)]) ** 0.5)
        for listing, weight in zip(ordered, ordered_weights, strict=True)
    )
    return [
        {
            "evaluation_id": evaluation_id,
            "portfolio_id": portfolio_id,
            "diversification_ratio": ratio,
            "portfolio_volatility": max(0.0, portfolio_variance) ** 0.5,
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
    listings = _listing_rows(matrix_rows)
    covariance_rows = _read_covariances(paths, listings)
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
    ordered = _listing_keys(listings)
    covariances = _covariance_map(covariance_rows)
    require_complete_covariance(ordered, covariances)
    ordered_weights = tuple(float(weights[isin]) for isin, _, _ in ordered)
    portfolio_variance = _portfolio_variance(ordered, ordered_weights, covariances)
    target_budget = 1.0 / len(ordered)
    contribution_rows: list[JsonRow] = []
    for listing, weight in zip(ordered, ordered_weights, strict=True):
        marginal = _marginal_risk_contribution(listing, ordered, ordered_weights, covariances)
        absolute = weight * marginal
        percent = 0.0 if portfolio_variance == 0 else absolute / portfolio_variance
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
                "portfolio_variance": portfolio_variance,
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


def _listing_keys(listings: Sequence[Mapping[str, Any]]) -> list[ListingKey]:
    keys = sorted({(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in listings})
    if not keys:
        raise ValueError("at least one listing is required")
    return keys


def _listing_rows(matrix_rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    return [
        {"isin": isin, "exchange": exchange, "code": code}
        for isin, exchange, code in _listing_keys(matrix_rows)
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


def _read_covariances(paths: LakePaths, listings: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    rows: list[JsonRow] = []
    for isin, exchange, _ in _listing_keys(listings):
        rows.extend(read_rows(paths.gold_covariance(exchange, isin)))
    return rows


def _covariance_map(
    covariance_rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[ListingKey, ListingKey], float]:
    values: dict[tuple[ListingKey, ListingKey], float] = {}
    for row in covariance_rows:
        left = (str(row["left_isin"]), str(row["left_exchange"]), str(row["left_code"]))
        right = (str(row["right_isin"]), str(row["right_exchange"]), str(row["right_code"]))
        values[(left, right)] = float(row["covariance"])
    return values


def _constraint_violations(
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
    return _portfolio_variance(listings, weights, covariances)


def _candidate_weights(
    listings: Sequence[ListingKey], constraints: PortfolioConstraints, *, grid_step: float
) -> list[tuple[float, ...]]:
    if not 0 < grid_step <= 1:
        raise ValueError("grid_step must be in (0, 1]")
    steps = round(1.0 / grid_step)
    if not isclose(steps * grid_step, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("grid_step must divide 1")
    exact_candidate_count = comb(len(listings) + steps - 1, steps)
    if exact_candidate_count > MAX_EXACT_WEIGHT_CANDIDATES:
        return _fallback_candidate_weights(listings, constraints)
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


def _portfolio_variance(
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
    portfolio_variance = _portfolio_variance(listings, weights, covariances)
    if portfolio_variance <= 0:
        return 0.0
    weighted_volatility = sum(
        weight * (max(0.0, covariances[(listing, listing)]) ** 0.5)
        for listing, weight in zip(listings, weights, strict=True)
    )
    return float(weighted_volatility / (portfolio_variance**0.5))


def _cluster_splits(
    listings: Sequence[ListingKey],
) -> list[tuple[list[ListingKey], list[ListingKey]]]:
    if len(listings) <= 1:
        return []
    midpoint = len(listings) // 2
    left = list(listings[:midpoint])
    right = list(listings[midpoint:])
    return [(left, right), *_cluster_splits(left), *_cluster_splits(right)]


def _cluster_variance(
    listings: Sequence[ListingKey], covariances: Mapping[tuple[ListingKey, ListingKey], float]
) -> float:
    if not listings:
        return 0.0
    weight = 1.0 / len(listings)
    return _portfolio_variance(listings, [weight] * len(listings), covariances)


def _recursive_hrp_weights(
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
    for isin, weight in _recursive_hrp_weights(left, covariances).items():
        weights[isin] = weight * left_allocation
    for isin, weight in _recursive_hrp_weights(right, covariances).items():
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
    variance = _portfolio_variance(listings, weights, covariances)
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
    variance = _portfolio_variance(listings, weights, covariances)
    if variance <= 0:
        return 0.0
    return float(
        (_portfolio_return(listings, weights, expected_returns) - risk_free_rate) / (variance**0.5)
    )
