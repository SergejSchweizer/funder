"""Walk-forward Evaluation boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from founder.paths import LakePaths
from founder.table_io import JsonRow


def _evaluation() -> Any:
    return importlib.import_module("founder.evaluation")


def build_walk_forward_backtest(
    matrix_rows: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    evaluation_id: str,
    objective: str,
    constraints: Any,
    train_window: int = 2,
    test_window: int = 1,
    grid_step: float = 0.1,
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _evaluation().build_walk_forward_backtest(
            matrix_rows,
            covariance_rows,
            run_id=run_id,
            evaluation_id=evaluation_id,
            objective=objective,
            constraints=constraints,
            train_window=train_window,
            test_window=test_window,
            grid_step=grid_step,
        ),
    )


def write_walk_forward_backtest(
    paths: LakePaths,
    *,
    evaluation_id: str,
    run_id: str,
    objective: str,
    constraints: Any,
    train_window: int = 2,
    test_window: int = 1,
    grid_step: float = 0.1,
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _evaluation().write_walk_forward_backtest(
            paths,
            evaluation_id=evaluation_id,
            run_id=run_id,
            objective=objective,
            constraints=constraints,
            train_window=train_window,
            test_window=test_window,
            grid_step=grid_step,
        ),
    )


__all__ = ["build_walk_forward_backtest", "write_walk_forward_backtest"]
