"""Efficient-frontier Evaluation boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from camovar.paths import LakePaths
from camovar.table_io import JsonRow


def _evaluation() -> Any:
    return importlib.import_module("camovar.evaluation")


def build_efficient_frontier(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    expected_returns: Mapping[str, float],
    *,
    evaluation_id: str,
    constraints: Any,
    target_returns: Sequence[float],
    grid_step: float = 0.1,
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _evaluation().build_efficient_frontier(
            listings,
            covariance_rows,
            expected_returns,
            evaluation_id=evaluation_id,
            constraints=constraints,
            target_returns=target_returns,
            grid_step=grid_step,
        ),
    )


def write_efficient_frontier(
    paths: LakePaths,
    *,
    evaluation_id: str,
    constraints: Any,
    target_returns: Sequence[float],
    grid_step: float = 0.1,
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _evaluation().write_efficient_frontier(
            paths,
            evaluation_id=evaluation_id,
            constraints=constraints,
            target_returns=target_returns,
            grid_step=grid_step,
        ),
    )


__all__ = ["build_efficient_frontier", "write_efficient_frontier"]
