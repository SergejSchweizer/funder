"""Portfolio return-series Evaluation boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from camovar.paths import LakePaths
from camovar.table_io import JsonRow


def _evaluation() -> Any:
    return importlib.import_module("camovar.evaluation")


def build_portfolio_returns(
    matrix_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    portfolio_id: str,
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _evaluation().build_portfolio_returns(
            matrix_rows, weights, evaluation_id=evaluation_id, portfolio_id=portfolio_id
        ),
    )


def build_drawdowns(portfolio_returns: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    return cast(list[JsonRow], _evaluation().build_drawdowns(portfolio_returns))


def write_portfolio_evaluation(
    paths: LakePaths,
    *,
    evaluation_id: str = "default",
    portfolio_id: str = "equal-weight",
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow], list[JsonRow]],
        _evaluation().write_portfolio_evaluation(
            paths, evaluation_id=evaluation_id, portfolio_id=portfolio_id
        ),
    )


__all__ = ["build_drawdowns", "build_portfolio_returns", "write_portfolio_evaluation"]
