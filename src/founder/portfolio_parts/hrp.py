"""Hierarchical-risk-parity optimizer boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from founder.paths import LakePaths
from founder.table_io import JsonRow


def _portfolio() -> Any:
    return importlib.import_module("founder.portfolio")


def hierarchical_risk_parity_weights(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    constraints: Any,
) -> dict[str, float]:
    return cast(
        dict[str, float],
        _portfolio().hierarchical_risk_parity_weights(listings, covariance_rows, constraints),
    )


def build_hrp_cluster_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    *,
    evaluation_id: str,
    portfolio_id: str,
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _portfolio().build_hrp_cluster_rows(
            listings,
            covariance_rows,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
        ),
    )


def write_hierarchical_risk_parity(
    paths: LakePaths,
    *,
    evaluation_id: str = "default",
    portfolio_id: str = "hierarchical-risk-parity",
    constraints: Any | None = None,
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow], list[JsonRow]],
        _portfolio().write_hierarchical_risk_parity(
            paths,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            constraints=constraints,
        ),
    )


__all__ = [
    "build_hrp_cluster_rows",
    "hierarchical_risk_parity_weights",
    "write_hierarchical_risk_parity",
]
