"""Shared calculation-confidence status vocabulary for tax and cost results.

Per docs/backlog/eu-tax-cost-architecture.md ("Calculation Status And
Confidence"): every tax or cost result must report one of these statuses.
Missing or unverified rules must resolve to `UNAVAILABLE`/`UNSUPPORTED`,
never a plausible zero tax or zero cost.
"""

from __future__ import annotations

EXACT = "exact"
VERIFIED_ESTIMATE = "verified_estimate"
USER_SUPPLIED_ESTIMATE = "user_supplied_estimate"
UNAVAILABLE = "unavailable"
UNSUPPORTED = "unsupported"

CALCULATION_STATUSES = (
    EXACT,
    VERIFIED_ESTIMATE,
    USER_SUPPLIED_ESTIMATE,
    UNAVAILABLE,
    UNSUPPORTED,
)

# Statuses that represent an actionable, usable result rather than a gap.
RESOLVED_STATUSES = (EXACT, VERIFIED_ESTIMATE, USER_SUPPLIED_ESTIMATE)


def require_known_status(status: str, field_name: str = "status") -> str:
    """Return `status` if it is a recognized calculation status, else raise."""
    if status not in CALCULATION_STATUSES:
        raise ValueError(f"{field_name} must be one of {CALCULATION_STATUSES}, got {status!r}")
    return status


def is_resolved(status: str) -> bool:
    """True when `status` represents a usable result rather than a gap."""
    return status in RESOLVED_STATUSES


__all__ = [
    "CALCULATION_STATUSES",
    "EXACT",
    "RESOLVED_STATUSES",
    "UNAVAILABLE",
    "UNSUPPORTED",
    "USER_SUPPLIED_ESTIMATE",
    "VERIFIED_ESTIMATE",
    "is_resolved",
    "require_known_status",
]
