"""Portfolio constraint boundary."""

from __future__ import annotations

import importlib
from typing import Any, cast


def _portfolio() -> Any:
    return importlib.import_module("camovar.portfolio")


PortfolioConstraints: Any = _portfolio().PortfolioConstraints


def validate_weights(weights: dict[str, float], constraints: Any) -> None:
    _portfolio().validate_weights(weights, constraints)


def equal_weight_seed(isins: list[str], constraints: Any) -> dict[str, float]:
    return cast(dict[str, float], _portfolio().equal_weight_seed(isins, constraints))


__all__ = ["PortfolioConstraints", "equal_weight_seed", "validate_weights"]
