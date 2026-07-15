"""Return-matrix Evaluation boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from founder.paths import LakePaths
from founder.table_io import JsonRow


def _evaluation() -> Any:
    return importlib.import_module("founder.evaluation")


def read_gold_returns(paths: LakePaths) -> list[JsonRow]:
    return cast(list[JsonRow], _evaluation().read_gold_returns(paths))


def build_return_matrix(
    return_rows: Sequence[Mapping[str, Any]], evaluation_id: str = "default"
) -> list[JsonRow]:
    return cast(list[JsonRow], _evaluation().build_return_matrix(return_rows, evaluation_id))


def write_evaluation_outputs(
    paths: LakePaths, *, evaluation_id: str = "default"
) -> tuple[list[JsonRow], list[JsonRow]]:
    return cast(
        tuple[list[JsonRow], list[JsonRow]],
        _evaluation().write_evaluation_outputs(paths, evaluation_id=evaluation_id),
    )


__all__ = ["build_return_matrix", "read_gold_returns", "write_evaluation_outputs"]
