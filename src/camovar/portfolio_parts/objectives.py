"""Core optimizer objective boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from camovar.paths import LakePaths
from camovar.table_io import JsonRow


def _portfolio() -> Any:
    return importlib.import_module("camovar.portfolio")


def optimize_portfolio(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    expected_returns: Mapping[str, float] | None = None,
    *,
    objective: str = "minimum_variance",
    constraints: Any | None = None,
    grid_step: float = 0.1,
) -> dict[str, float]:
    return cast(
        dict[str, float],
        _portfolio().optimize_portfolio(
            listings,
            covariance_rows,
            expected_returns,
            objective=objective,
            constraints=constraints,
            grid_step=grid_step,
        ),
    )


def build_target_weight_rows(
    listings: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    objective: str,
    portfolio_id: str,
    constraints: Any,
    diagnostics: Mapping[str, Any],
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _portfolio().build_target_weight_rows(
            listings,
            weights,
            evaluation_id=evaluation_id,
            objective=objective,
            portfolio_id=portfolio_id,
            constraints=constraints,
            diagnostics=diagnostics,
        ),
    )


def write_optimized_weights(
    paths: LakePaths,
    *,
    evaluation_id: str = "default",
    objective: str = "minimum_variance",
    portfolio_id: str | None = None,
    constraints: Any | None = None,
    grid_step: float = 0.1,
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _portfolio().write_optimized_weights(
            paths,
            evaluation_id=evaluation_id,
            objective=objective,
            portfolio_id=portfolio_id,
            constraints=constraints,
            grid_step=grid_step,
        ),
    )


__all__ = ["build_target_weight_rows", "optimize_portfolio", "write_optimized_weights"]
