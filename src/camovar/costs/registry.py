"""Broker/venue/execution/FX/tax/recurring cost-profile registry (PR62A).

Unlike `camovar.tax.registry.CountryTaxRegistry`, broker and venue ids are
not a fixed enumerable set, so this registry has no "known but unsupported"
placeholder concept: an unregistered profile simply has no cost estimate
and must resolve to `unavailable`/`unsupported`, never a plausible zero
cost.
"""

from __future__ import annotations

from camovar.costs.contracts import CostComponentProfile

# Cost-component kinds a profile may be registered under.
COST_COMPONENT_KINDS = (
    "broker",
    "venue",
    "execution",
    "fx",
    "jurisdiction_transaction_tax",
    "recurring_account",
)


class UnsupportedCostProfileError(LookupError):
    """Raised when no cost-component profile is registered for a request."""


class CostProfileRegistry:
    """A registry of `(kind, profile_id)` to `CostComponentProfile` implementations."""

    def __init__(self) -> None:
        self._profiles: dict[tuple[str, str], CostComponentProfile] = {}

    def register(self, kind: str, profile_id: str, profile: CostComponentProfile) -> None:
        if kind not in COST_COMPONENT_KINDS:
            raise ValueError(f"kind must be one of {COST_COMPONENT_KINDS}, got {kind!r}")
        if not profile_id.strip():
            raise ValueError("profile_id is required")
        self._profiles[(kind, profile_id)] = profile

    def is_supported(self, kind: str, profile_id: str) -> bool:
        return (kind, profile_id) in self._profiles

    def resolve(self, kind: str, profile_id: str) -> CostComponentProfile:
        profile = self._profiles.get((kind, profile_id))
        if profile is None:
            raise UnsupportedCostProfileError(
                f"no {kind!r} cost profile registered for {profile_id!r}"
            )
        return profile

    def registered_profile_ids(self, kind: str) -> frozenset[str]:
        return frozenset(key[1] for key in self._profiles if key[0] == kind)


__all__ = [
    "COST_COMPONENT_KINDS",
    "CostProfileRegistry",
    "UnsupportedCostProfileError",
]
