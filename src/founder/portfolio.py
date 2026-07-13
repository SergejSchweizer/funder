"""Portfolio constraint helpers and deterministic optimization objectives."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import comb, isclose
from typing import Any

from founder.paths import LakePaths
from founder.table_io import JsonRow, read_rows, write_rows

ListingKey = tuple[str, str, str]
MAX_EXACT_WEIGHT_CANDIDATES = 20_000


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

    if objective not in {"minimum_variance", "maximum_sharpe", "target_return_minimum_variance"}:
        raise ValueError(f"unknown optimization objective: {objective}")
    if objective == "target_return_minimum_variance" and target_return is None:
        raise ValueError("target_return is required")
    target_value = 0.0 if target_return is None else target_return

    covariances = _covariance_map(covariance_rows)
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
    else:
        best = min(
            feasible,
            key=lambda weights: (
                _portfolio_variance(ordered, weights, covariances),
                abs(_portfolio_return(ordered, weights, expected_returns) - target_value),
                weights,
            ),
        )
    result = {isin: weight for (isin, _, _), weight in zip(ordered, best, strict=True)}
    validate_weights(result, constraints)
    return result


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
    diagnostics = {
        "risk_free_rate": risk_free_rate,
        "target_return": target_return,
        "expected_return": _portfolio_return(ordered, ordered_weights, expected_returns),
    }
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
    return rows


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
            variance += left_weight * right_weight * covariances.get((left, right), 0.0)
    return variance


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
