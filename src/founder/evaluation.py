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


def write_evaluation_outputs(
    paths: LakePaths, *, evaluation_id: str = "default"
) -> tuple[list[JsonRow], list[JsonRow]]:
    matrix = build_return_matrix(read_gold_returns(paths), evaluation_id)
    metrics = build_asset_metrics(matrix, evaluation_id)
    write_rows(paths.gold_return_matrix(evaluation_id), matrix)
    write_rows(paths.gold_asset_metrics(evaluation_id), metrics)
    return matrix, metrics
