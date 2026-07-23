"""Shared price-quality gate and return-type primitives for Gold and Statistics.

This module gives every return-producing builder (`camovar.gold`,
`camovar.univariate_statistics`) one shared definition of a valid price point so
that invalid prices are quarantined instead of silently becoming a fabricated
zero return. It also defines the minimum-history thresholds used to decide
whether a listing's metrics may be labeled production-eligible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from camovar.table_io import JsonRow

MIN_HISTORY_SHORT = 252
MIN_HISTORY_MEDIUM = 504
MIN_HISTORY_LONG = 756

STALE_PRICE_MIN_REPEATS = 5
UNEXPLAINED_GAP_CALENDAR_DAYS = 10

NON_POSITIVE_PRICE_REASON = "non_positive_price"
DUPLICATE_DATE_REASON = "duplicate_date"


def filter_valid_price_points(
    ordered_quotes: Sequence[Mapping[str, Any]],
) -> tuple[list[JsonRow], list[JsonRow]]:
    """Split ordered per-listing quotes into valid rows and quarantined rows.

    A row is quarantined instead of silently treated as a zero-return event when
    its adjusted close is non-positive, or when its date repeats an earlier row.
    Quarantined rows keep every original field plus a `quarantine_reason`.
    """
    valid: list[JsonRow] = []
    quarantined: list[JsonRow] = []
    seen_dates: set[str] = set()
    for row in ordered_quotes:
        row_date = str(row["date"])
        if row_date in seen_dates:
            quarantined.append({**dict(row), "quarantine_reason": DUPLICATE_DATE_REASON})
            continue
        seen_dates.add(row_date)
        adjusted_close = float(row["adjusted_close"])
        if adjusted_close <= 0:
            quarantined.append({**dict(row), "quarantine_reason": NON_POSITIVE_PRICE_REASON})
            continue
        valid.append(dict(row))
    return valid, quarantined


def detect_stale_price_run(
    valid_quotes: Sequence[Mapping[str, Any]],
    *,
    min_repeats: int = STALE_PRICE_MIN_REPEATS,
) -> bool:
    """Return True when adjusted close repeats for `min_repeats` or more sessions."""
    run_length = 1
    previous_close: float | None = None
    for row in valid_quotes:
        close = float(row["adjusted_close"])
        if previous_close is not None and close == previous_close:
            run_length += 1
            if run_length >= min_repeats:
                return True
        else:
            run_length = 1
        previous_close = close
    return False


def detect_unexplained_gap(
    valid_quotes: Sequence[Mapping[str, Any]],
    *,
    max_gap_days: int = UNEXPLAINED_GAP_CALENDAR_DAYS,
) -> bool:
    """Return True when consecutive valid quote dates skip more than `max_gap_days`."""
    for previous, current in zip(valid_quotes, valid_quotes[1:], strict=False):
        previous_date = date.fromisoformat(str(previous["date"]))
        current_date = date.fromisoformat(str(current["date"]))
        if (current_date - previous_date).days > max_gap_days:
            return True
    return False


def evaluate_quote_quality(ordered_quotes: Sequence[Mapping[str, Any]]) -> JsonRow:
    """Evaluate quote-level price-quality and minimum-history production gates.

    The returned row uses only the listing's own quote history: it cannot detect
    cross-listing issues. Callers combine `observation_count` with their own
    return-construction logic; this function is the single source of truth for
    what counts as a valid price point and what counts as production-eligible
    history depth.
    """
    ordered = sorted(ordered_quotes, key=lambda row: str(row["date"]))
    valid, quarantined = filter_valid_price_points(ordered)
    non_positive_price_detected = any(
        row["quarantine_reason"] == NON_POSITIVE_PRICE_REASON for row in quarantined
    )
    duplicate_date_detected = any(
        row["quarantine_reason"] == DUPLICATE_DATE_REASON for row in quarantined
    )
    stale_price_detected = detect_stale_price_run(valid)
    unexplained_gap_detected = detect_unexplained_gap(valid)
    observation_count = max(0, len(valid) - 1)
    meets_min_history_252 = observation_count >= MIN_HISTORY_SHORT
    meets_min_history_504 = observation_count >= MIN_HISTORY_MEDIUM
    meets_min_history_756 = observation_count >= MIN_HISTORY_LONG

    issues: list[str] = []
    if non_positive_price_detected:
        issues.append(NON_POSITIVE_PRICE_REASON)
    if duplicate_date_detected:
        issues.append(DUPLICATE_DATE_REASON)
    if stale_price_detected:
        issues.append("stale_price")
    if unexplained_gap_detected:
        issues.append("unexplained_gap")
    if not meets_min_history_252:
        issues.append("insufficient_history")

    return {
        "quote_observation_count": len(ordered),
        "valid_price_count": len(valid),
        "quarantined_price_count": len(quarantined),
        "non_positive_price_detected": non_positive_price_detected,
        "duplicate_date_detected": duplicate_date_detected,
        "stale_price_detected": stale_price_detected,
        "unexplained_gap_detected": unexplained_gap_detected,
        "meets_min_history_252": meets_min_history_252,
        "meets_min_history_504": meets_min_history_504,
        "meets_min_history_756": meets_min_history_756,
        "production_eligible": not issues,
        "data_quality_reason": issues[0] if issues else "ok",
    }


def meets_minimum_observations(observation_count: int, threshold: int = MIN_HISTORY_SHORT) -> bool:
    """Return True when `observation_count` satisfies a minimum-history threshold."""
    return observation_count >= threshold
