"""Tail-risk Evaluation boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from camovar.paths import LakePaths
from camovar.table_io import JsonRow


def _evaluation() -> Any:
    return importlib.import_module("camovar.evaluation")


def build_tail_risk_rows(
    portfolio_returns: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    evaluation_id: str,
    portfolio_id: str,
    confidence_level: float = 0.95,
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _evaluation().build_tail_risk_rows(
            portfolio_returns,
            run_id=run_id,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
            confidence_level=confidence_level,
        ),
    )


def write_tail_risk_evaluation(
    paths: LakePaths,
    *,
    evaluation_id: str,
    run_id: str,
    portfolio_id: str,
    confidence_level: float = 0.95,
) -> list[JsonRow]:
    return cast(
        list[JsonRow],
        _evaluation().write_tail_risk_evaluation(
            paths,
            evaluation_id=evaluation_id,
            run_id=run_id,
            portfolio_id=portfolio_id,
            confidence_level=confidence_level,
        ),
    )


__all__ = ["build_tail_risk_rows", "write_tail_risk_evaluation"]
