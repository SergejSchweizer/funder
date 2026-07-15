"""Bivariate Statistics for approved ISIN listing pairs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from founder.gold_pair_stats import (
    correlation_value,
    index_returns,
    iter_pair_observations,
    sample_covariance,
    sort_pair_rows,
)
from founder.paths import LakePaths
from founder.schemas import validate_rows
from founder.table_io import JsonRow, write_rows


def build_bivariate_statistics(
    return_rows: Sequence[Mapping[str, Any]],
    *,
    skip_same_isin: bool = True,
) -> list[JsonRow]:
    """Compute pairwise statistics from aligned return rows.

    The output intentionally contains only two-listing statistics. Single-listing
    return summaries belong in the separate univariate statistics module.
    """
    returns_by_listing = index_returns(return_rows)
    rows: list[JsonRow] = []
    for pair in iter_pair_observations(
        returns_by_listing,
        include_self=False,
        skip_same_isin=skip_same_isin,
    ):
        covariance = sample_covariance(pair.left_values, pair.right_values)
        left_variance = sample_covariance(pair.left_values, pair.left_values)
        right_variance = sample_covariance(pair.right_values, pair.right_values)
        rows.append(
            {
                "pair_key": _pair_key(pair.left, pair.right),
                "left_listing_key": _listing_key(pair.left),
                "right_listing_key": _listing_key(pair.right),
                "left_id": pair.left_id,
                "right_id": pair.right_id,
                "left_isin": pair.left[0],
                "left_exchange": pair.left[1],
                "left_code": pair.left[2],
                "right_isin": pair.right[0],
                "right_exchange": pair.right[1],
                "right_code": pair.right[2],
                "date_start": pair.dates[0] if pair.dates else "",
                "date_end": pair.dates[-1] if pair.dates else "",
                "n_observations": len(pair.dates),
                "pearson_correlation": correlation_value(
                    pair.left_values,
                    pair.right_values,
                    "pearson",
                ),
                "spearman_correlation": correlation_value(
                    pair.left_values,
                    pair.right_values,
                    "spearman",
                ),
                "covariance": covariance,
                "left_variance": left_variance,
                "right_variance": right_variance,
                "left_beta_to_right": _ratio(covariance, right_variance),
                "right_beta_to_left": _ratio(covariance, left_variance),
            }
        )
    return sort_pair_rows(rows)


def write_bivariate_statistics(
    paths: LakePaths,
    return_rows: Sequence[Mapping[str, Any]],
    *,
    skip_same_isin: bool = True,
) -> list[JsonRow]:
    """Write Bivariate Statistics rows to stable Gold paths by listing pair."""
    rows = build_bivariate_statistics(return_rows, skip_same_isin=skip_same_isin)
    validate_rows("bivariate_statistics", rows)
    for row in rows:
        write_rows(
            paths.gold_bivariate_statistics_pair(
                str(row["left_exchange"]),
                str(row["left_isin"]),
                str(row["left_code"]),
                str(row["right_exchange"]),
                str(row["right_isin"]),
                str(row["right_code"]),
            ),
            [row],
        )
    return rows


def _listing_key(listing: tuple[str, str, str]) -> str:
    isin, exchange, code = listing
    return f"{exchange}__{isin}__{code}"


def _pair_key(left: tuple[str, str, str], right: tuple[str, str, str]) -> str:
    return f"{_listing_key(left)}___{_listing_key(right)}"


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


__all__ = [
    "build_bivariate_statistics",
    "write_bivariate_statistics",
]
