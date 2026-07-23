"""Risk-parity optimizer boundary."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any, cast


def _portfolio() -> Any:
    return importlib.import_module("camovar.portfolio")


def build_risk_contribution_rows(
    listings: Sequence[Mapping[str, Any]],
    covariance_rows: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    evaluation_id: str,
    portfolio_id: str,
) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        _portfolio().build_risk_contribution_rows(
            listings,
            covariance_rows,
            weights,
            evaluation_id=evaluation_id,
            portfolio_id=portfolio_id,
        ),
    )


__all__ = ["build_risk_contribution_rows"]
