"""Rebalance simulation Evaluation boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from camovar.paths import LakePaths
from camovar.table_io import JsonRow


def _evaluation() -> Any:
    return importlib.import_module("camovar.evaluation")


def build_rebalance_events(
    matrix_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    evaluation_id: str,
    portfolio_id: str,
    target_weights: Mapping[str, float] | None = None,
    schedule: str = "monthly",
    transaction_cost_rate: float = 0.0,
    drift_threshold: float | None = None,
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _evaluation().build_rebalance_events(
            matrix_rows,
            run_id=run_id,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            target_weights=target_weights,
            schedule=schedule,
            transaction_cost_rate=transaction_cost_rate,
            drift_threshold=drift_threshold,
        ),
    )


def write_rebalance_simulation(
    paths: LakePaths,
    *,
    evaluation_id: str,
    run_id: str,
    portfolio_id: str,
    target_weights: Mapping[str, float] | None = None,
    schedule: str = "monthly",
    transaction_cost_rate: float = 0.0,
    drift_threshold: float | None = None,
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _evaluation().write_rebalance_simulation(
            paths,
            evaluation_id=evaluation_id,
            run_id=run_id,
            portfolio_id=portfolio_id,
            target_weights=target_weights,
            schedule=schedule,
            transaction_cost_rate=transaction_cost_rate,
            drift_threshold=drift_threshold,
        ),
    )


__all__ = ["build_rebalance_events", "write_rebalance_simulation"]
