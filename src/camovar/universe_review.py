"""Universe review helpers for missing ISINs, currencies, and survivorship bias."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from camovar.table_io import JsonRow


def missing_isin_rows(candidates: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    return [dict(row) for row in candidates if not str(row.get("isin", "")).strip()]


def currency_exposure(
    rows: Sequence[Mapping[str, Any]], weights: Mapping[str, float]
) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for row in rows:
        isin = str(row["isin"])
        currency = str(row.get("currency", "UNKNOWN") or "UNKNOWN")
        exposure[currency] = exposure.get(currency, 0.0) + weights.get(isin, 0.0)
    return dict(sorted(exposure.items()))


def survivorship_bias_warnings(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if candidates and all(
        str(row.get("status", "active")).casefold() == "active" for row in candidates
    ):
        warnings.append(
            "Universe contains only active instruments; document survivorship-bias limits."
        )
    if missing_isin_rows(candidates):
        warnings.append("Rows without ISIN are excluded from bronze inputs and require review.")
    return warnings


def review_universe(
    candidates: Sequence[Mapping[str, Any]], weights: Mapping[str, float]
) -> JsonRow:
    return {
        "candidate_rows": len(candidates),
        "missing_isin_rows": len(missing_isin_rows(candidates)),
        "currency_exposure": currency_exposure(candidates, weights),
        "warnings": survivorship_bias_warnings(candidates),
    }
