"""Gold evaluation datasets built from Gold return inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import sqrt
from typing import Any

from founder.gold import covariance
from founder.paths import LakePaths
from founder.table_io import JsonRow, read_rows, write_rows

ANNUAL_TRADING_DAYS = 252


def read_gold_returns(paths: LakePaths) -> list[JsonRow]:
    rows: list[JsonRow] = []
    for path in sorted((paths.gold / "returns").glob("*/*.parquet")):
        rows.extend(read_rows(path))
    return rows


def build_return_matrix(
    return_rows: Sequence[Mapping[str, Any]], evaluation_id: str
) -> list[JsonRow]:
    by_listing: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, {})[str(row["date"])] = float(row["return"])
    if not by_listing:
        return []

    common_dates = set.intersection(*(set(rows) for rows in by_listing.values()))
    matrix: list[JsonRow] = []
    for date in sorted(common_dates):
        for isin, exchange, code in sorted(by_listing):
            matrix.append(
                {
                    "evaluation_id": evaluation_id,
                    "date": date,
                    "isin": isin,
                    "exchange": exchange,
                    "code": code,
                    "return": by_listing[(isin, exchange, code)][date],
                }
            )
    return matrix


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def equal_weight_portfolio(matrix_rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    isins = sorted({str(row["isin"]) for row in matrix_rows})
    if not isins:
        raise ValueError("at least one return row is required")
    weight = 1.0 / len(isins)
    return {isin: weight for isin in isins}


def validate_portfolio_weights(
    matrix_rows: Sequence[Mapping[str, Any]], weights: Mapping[str, float]
) -> dict[str, float]:
    expected = {str(row["isin"]) for row in matrix_rows}
    cleaned = {str(isin): float(weight) for isin, weight in weights.items()}
    if not cleaned:
        raise ValueError("portfolio weights are required")
    missing = sorted(expected - set(cleaned))
    extra = sorted(set(cleaned) - expected)
    if missing:
        raise ValueError(f"portfolio weights missing ISINs: {', '.join(missing)}")
    if extra:
        raise ValueError(f"portfolio weights include unknown ISINs: {', '.join(extra)}")
    if any(weight < 0 for weight in cleaned.values()):
        raise ValueError("portfolio weights must be long-only")
    if abs(sum(cleaned.values()) - 1.0) > 1e-9:
        raise ValueError("portfolio weights must sum to 1")
    return {isin: cleaned[isin] for isin in sorted(cleaned)}


def build_asset_metrics(
    matrix_rows: Sequence[Mapping[str, Any]], evaluation_id: str
) -> list[JsonRow]:
    by_listing: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in matrix_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, []).append(row)

    metrics: list[JsonRow] = []
    for isin, exchange, code in sorted(by_listing):
        ordered = sorted(by_listing[(isin, exchange, code)], key=lambda row: str(row["date"]))
        returns = [float(row["return"]) for row in ordered]
        mean_return = sum(returns) / len(returns) if returns else 0.0
        volatility = sqrt(covariance(returns, returns)) if len(returns) >= 2 else 0.0
        downside_returns = [min(0.0, item) for item in returns]
        downside_deviation = (
            sqrt(sum(item * item for item in downside_returns) / len(downside_returns))
            * sqrt(ANNUAL_TRADING_DAYS)
            if downside_returns
            else 0.0
        )
        annualized_return = mean_return * ANNUAL_TRADING_DAYS
        annualized_volatility = volatility * sqrt(ANNUAL_TRADING_DAYS)
        metrics.append(
            {
                "evaluation_id": evaluation_id,
                "isin": isin,
                "exchange": exchange,
                "code": code,
                "observation_count": len(returns),
                "first_return_date": str(ordered[0]["date"]) if ordered else "",
                "last_return_date": str(ordered[-1]["date"]) if ordered else "",
                "mean_return": mean_return,
                "annualized_return": annualized_return,
                "annualized_volatility": annualized_volatility,
                "downside_deviation": downside_deviation,
                "sharpe_ratio": _ratio(annualized_return, annualized_volatility),
                "sortino_ratio": _ratio(annualized_return, downside_deviation),
            }
        )
    return metrics


def build_portfolio_returns(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    evaluation_id: str,
    portfolio_id: str,
    weights: Mapping[str, float],
) -> list[JsonRow]:
    validated_weights = validate_portfolio_weights(matrix_rows, weights)
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for row in matrix_rows:
        by_date.setdefault(str(row["date"]), []).append(row)

    cumulative_wealth = 1.0
    rows: list[JsonRow] = []
    for item_date in sorted(by_date):
        daily_return = sum(
            float(row["return"]) * validated_weights[str(row["isin"])] for row in by_date[item_date]
        )
        cumulative_wealth *= 1.0 + daily_return
        rows.append(
            {
                "evaluation_id": evaluation_id,
                "portfolio_id": portfolio_id,
                "date": item_date,
                "return": daily_return,
                "cumulative_wealth": cumulative_wealth,
            }
        )
    return rows


def build_drawdowns(portfolio_returns: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    running_peak = 1.0
    drawdown_duration = 0
    rows: list[JsonRow] = []
    for row in sorted(portfolio_returns, key=lambda item: str(item["date"])):
        cumulative_wealth = float(row["cumulative_wealth"])
        recovered_duration = 0
        if cumulative_wealth >= running_peak:
            recovered_duration = drawdown_duration if drawdown_duration else 0
            running_peak = cumulative_wealth
            drawdown_duration = 0
        else:
            drawdown_duration += 1
        drawdown = 0.0 if running_peak == 0 else (cumulative_wealth / running_peak) - 1.0
        rows.append(
            {
                "evaluation_id": str(row["evaluation_id"]),
                "portfolio_id": str(row["portfolio_id"]),
                "date": str(row["date"]),
                "cumulative_wealth": cumulative_wealth,
                "running_peak": running_peak,
                "drawdown": drawdown,
                "drawdown_duration": drawdown_duration,
                "recovery_duration": recovered_duration,
                "is_recovered": recovered_duration > 0,
            }
        )
    return rows


def build_portfolio_metrics(
    portfolio_returns: Sequence[Mapping[str, Any]],
    drawdown_rows: Sequence[Mapping[str, Any]],
    *,
    objective: str = "explicit_weights",
) -> list[JsonRow]:
    if not portfolio_returns:
        return []
    ordered_returns = sorted(portfolio_returns, key=lambda row: str(row["date"]))
    returns = [float(row["return"]) for row in ordered_returns]
    mean_return = sum(returns) / len(returns)
    volatility = sqrt(covariance(returns, returns)) if len(returns) >= 2 else 0.0
    downside_returns = [min(0.0, item) for item in returns]
    downside_deviation = sqrt(sum(item * item for item in downside_returns) / len(returns)) * sqrt(
        ANNUAL_TRADING_DAYS
    )
    annualized_return = mean_return * ANNUAL_TRADING_DAYS
    annualized_volatility = volatility * sqrt(ANNUAL_TRADING_DAYS)
    max_drawdown = min((float(row["drawdown"]) for row in drawdown_rows), default=0.0)
    ulcer_index = sqrt(
        sum(float(row["drawdown"]) * float(row["drawdown"]) for row in drawdown_rows)
        / len(drawdown_rows)
    )
    first = ordered_returns[0]
    return [
        {
            "evaluation_id": str(first["evaluation_id"]),
            "portfolio_id": str(first["portfolio_id"]),
            "objective": objective,
            "annualized_return": annualized_return,
            "annualized_volatility": annualized_volatility,
            "sharpe_ratio": _ratio(annualized_return, annualized_volatility),
            "sortino_ratio": _ratio(annualized_return, downside_deviation),
            "max_drawdown": max_drawdown,
            "calmar_ratio": _ratio(annualized_return, abs(max_drawdown)),
            "ulcer_index": ulcer_index,
            "turnover": 0.0,
        }
    ]


def write_evaluation_outputs(
    paths: LakePaths, *, evaluation_id: str = "default"
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix = build_return_matrix(read_gold_returns(paths), evaluation_id)
    metrics = build_asset_metrics(matrix, evaluation_id)
    write_rows(paths.gold_return_matrix(evaluation_id), matrix)
    write_rows(paths.gold_asset_metrics(evaluation_id), metrics)
    return matrix, metrics


def write_portfolio_evaluation(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    weights: Mapping[str, float] | None = None,
    objective: str = "explicit_weights",
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow]]:
    matrix = read_rows(paths.gold_return_matrix(evaluation_id))
    if not matrix:
        matrix, _ = write_evaluation_outputs(paths, evaluation_id=evaluation_id)
    portfolio_weights = equal_weight_portfolio(matrix) if weights is None else dict(weights)
    portfolio_returns = build_portfolio_returns(
        matrix,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
        weights=portfolio_weights,
    )
    drawdowns = build_drawdowns(portfolio_returns)
    metrics = build_portfolio_metrics(
        portfolio_returns,
        drawdowns,
        objective="equal_weight" if weights is None else objective,
    )
    existing_returns = [
        row
        for row in read_rows(paths.gold_portfolio_returns(evaluation_id))
        if str(row["portfolio_id"]) != portfolio_id
    ]
    existing_metrics = [
        row
        for row in read_rows(paths.gold_portfolio_metrics(evaluation_id))
        if str(row["portfolio_id"]) != portfolio_id
    ]
    write_rows(
        paths.gold_portfolio_returns(evaluation_id),
        sorted(
            [*existing_returns, *portfolio_returns],
            key=lambda row: (str(row["portfolio_id"]), str(row["date"])),
        ),
    )
    write_rows(paths.gold_drawdowns(evaluation_id, portfolio_id), drawdowns)
    write_rows(
        paths.gold_portfolio_metrics(evaluation_id),
        sorted([*existing_metrics, *metrics], key=lambda row: str(row["portfolio_id"])),
    )
    return portfolio_returns, drawdowns, metrics
