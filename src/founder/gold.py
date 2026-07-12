"""Gold-layer return, correlation, and covariance inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import sqrt
from typing import Any

from founder.paths import LakePaths
from founder.table_io import JsonRow, write_rows


def build_returns(quote_rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    by_isin: dict[str, list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        by_isin.setdefault(str(row["isin"]), []).append(row)

    returns: list[JsonRow] = []
    for isin, rows in sorted(by_isin.items()):
        ordered = sorted(rows, key=lambda row: str(row["date"]))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            previous_close = float(previous["adjusted_close"])
            current_close = float(current["adjusted_close"])
            returns.append(
                {
                    "isin": isin,
                    "date": str(current["date"]),
                    "return": 0.0
                    if previous_close == 0
                    else (current_close / previous_close) - 1.0,
                }
            )
    return returns


def _paired_values(
    rows: Sequence[Mapping[str, Any]], left: str, right: str
) -> tuple[list[float], list[float]]:
    by_key = {(str(row["isin"]), str(row["date"])): float(row["return"]) for row in rows}
    dates = sorted(
        {date for isin, date in by_key if isin == left}
        & {date for isin, date in by_key if isin == right}
    )
    return [by_key[(left, item)] for item in dates], [by_key[(right, item)] for item in dates]


def covariance(left_values: Sequence[float], right_values: Sequence[float]) -> float:
    if len(left_values) < 2 or len(left_values) != len(right_values):
        return 0.0
    left_mean = sum(left_values) / len(left_values)
    right_mean = sum(right_values) / len(right_values)
    return sum(
        (left - left_mean) * (right - right_mean)
        for left, right in zip(left_values, right_values, strict=True)
    ) / (len(left_values) - 1)


def build_correlation_and_covariance(
    return_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[JsonRow], list[JsonRow]]:
    isins = sorted({str(row["isin"]) for row in return_rows})
    correlations: list[JsonRow] = []
    covariances: list[JsonRow] = []
    for left in isins:
        for right in isins:
            left_values, right_values = _paired_values(return_rows, left, right)
            cov = covariance(left_values, right_values)
            left_var = covariance(left_values, left_values)
            right_var = covariance(right_values, right_values)
            corr = 0.0 if left_var == 0 or right_var == 0 else cov / sqrt(left_var * right_var)
            correlations.append({"left_isin": left, "right_isin": right, "correlation": corr})
            covariances.append({"left_isin": left, "right_isin": right, "covariance": cov})
    return correlations, covariances


def write_gold_inputs(
    paths: LakePaths, quote_rows: Sequence[Mapping[str, Any]], *, as_of: str
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow]]:
    returns = build_returns(quote_rows)
    correlations, covariances = build_correlation_and_covariance(returns)
    write_rows(paths.gold_returns(as_of), returns)
    write_rows(paths.gold_correlation(as_of), correlations)
    write_rows(paths.gold_covariance(as_of), covariances)
    return returns, correlations, covariances
