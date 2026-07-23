"""Maximum-diversification optimizer boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from camovar.paths import LakePaths
from camovar.table_io import JsonRow


def _portfolio() -> Any:
    return importlib.import_module("camovar.portfolio")


def build_diversification_metric_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    portfolio_id: str,
    diagnostics: Mapping[str, Any],
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _portfolio().build_diversification_metric_rows(
            listings,
            covariance_rows,
            weights,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            diagnostics=diagnostics,
        ),
    )


def write_maximum_diversification(
    paths: LakePaths,
    *,
    evaluation_id: str = "default",
    portfolio_id: str = "maximum-diversification",
    constraints: Any | None = None,
    grid_step: float = 0.1,
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _portfolio().write_maximum_diversification(
            paths,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            constraints=constraints,
            grid_step=grid_step,
        ),
    )


__all__ = ["build_diversification_metric_rows", "write_maximum_diversification"]
