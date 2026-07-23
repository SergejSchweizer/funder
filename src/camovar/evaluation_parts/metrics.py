"""Asset and portfolio metric Evaluation boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from camovar.table_io import JsonRow


def _evaluation() -> Any:
    return importlib.import_module("camovar.evaluation")


def build_asset_metrics(
    matrix_rows: Sequence[Mapping[str, Any]], evaluation_id: str = "default"
) -> list[JsonRow]:
    return cast(list[JsonRow], _evaluation().build_asset_metrics(matrix_rows, evaluation_id))


def build_portfolio_metrics(
    portfolio_returns: Sequence[Mapping[str, Any]],
    drawdowns: Sequence[Mapping[str, Any]],
    *,
    evaluation_id: str,
    portfolio_id: str,
    objective: str = "equal_weight",
    turnover: float = 0.0,
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _evaluation().build_portfolio_metrics(
            portfolio_returns,
            drawdowns,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            objective=objective,
            turnover=turnover,
        ),
    )


__all__ = ["build_asset_metrics", "build_portfolio_metrics"]
