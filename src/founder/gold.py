"""Gold-layer return, correlation, and covariance inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import sqrt
from typing import Any

from founder.paths import LakePaths
from founder.table_io import JsonRow, write_rows


def build_returns(quote_rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    by_listing: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, []).append(row)

    returns: list[JsonRow] = []
    for (isin, exchange, code), rows in sorted(by_listing.items()):
        ordered = sorted(rows, key=lambda row: str(row["date"]))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            previous_close = float(previous["adjusted_close"])
            current_close = float(current["adjusted_close"])
            returns.append(
                {
                    "isin": isin,
                    "exchange": exchange,
                    "code": code,
                    "date": str(current["date"]),
                    "return": 0.0
                    if previous_close == 0
                    else (current_close / previous_close) - 1.0,
                }
            )
    return returns


def _paired_values(
    rows: Sequence[Mapping[str, Any]], left: tuple[str, str, str], right: tuple[str, str, str]
) -> tuple[list[float], list[float]]:
    by_key = {
        (str(row["isin"]), str(row["exchange"]), str(row["code"]), str(row["date"])): float(
            row["return"]
        )
        for row in rows
    }
    dates = sorted(
        {date for isin, exchange, code, date in by_key if (isin, exchange, code) == left}
        & {date for isin, exchange, code, date in by_key if (isin, exchange, code) == right}
    )
    return [by_key[(*left, item)] for item in dates], [by_key[(*right, item)] for item in dates]


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
    listings = sorted(
        {(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in return_rows}
    )
    correlations: list[JsonRow] = []
    covariances: list[JsonRow] = []
    for left in listings:
        for right in listings:
            left_values, right_values = _paired_values(return_rows, left, right)
            cov = covariance(left_values, right_values)
            left_var = covariance(left_values, left_values)
            right_var = covariance(right_values, right_values)
            corr = 0.0 if left_var == 0 or right_var == 0 else cov / sqrt(left_var * right_var)
            correlations.append(
                {
                    "left_isin": left[0],
                    "left_exchange": left[1],
                    "left_code": left[2],
                    "right_isin": right[0],
                    "right_exchange": right[1],
                    "right_code": right[2],
                    "correlation": corr,
                }
            )
            covariances.append(
                {
                    "left_isin": left[0],
                    "left_exchange": left[1],
                    "left_code": left[2],
                    "right_isin": right[0],
                    "right_exchange": right[1],
                    "right_code": right[2],
                    "covariance": cov,
                }
            )
    return correlations, covariances


def write_gold_inputs(
    paths: LakePaths, quote_rows: Sequence[Mapping[str, Any]]
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow]]:
    returns = build_returns(quote_rows)
    correlations, covariances = build_correlation_and_covariance(returns)

    returns_by_listing: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in returns:
        returns_by_listing.setdefault((str(row["exchange"]), str(row["isin"])), []).append(row)
    for (exchange, isin), rows in sorted(returns_by_listing.items()):
        write_rows(paths.gold_returns(exchange, isin), rows)

    left_keys = sorted({(str(row["left_exchange"]), str(row["left_isin"])) for row in correlations})
    for exchange, isin in left_keys:
        write_rows(
            paths.gold_correlation(exchange, isin),
            [
                item
                for item in correlations
                if str(item["left_exchange"]) == exchange and str(item["left_isin"]) == isin
            ],
        )
        write_rows(
            paths.gold_covariance(exchange, isin),
            [
                item
                for item in covariances
                if str(item["left_exchange"]) == exchange and str(item["left_isin"]) == isin
            ],
        )
    return returns, correlations, covariances
