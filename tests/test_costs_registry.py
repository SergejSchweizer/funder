"""Tests for the PR62A cost-profile registry."""

from decimal import Decimal

import pytest

from camovar.costs.contracts import ComponentCostEstimate, ExecutionContext
from camovar.costs.registry import CostProfileRegistry, UnsupportedCostProfileError


class _FlatFeeBrokerProfile:
    def estimate(self, context: ExecutionContext) -> ComponentCostEstimate:
        return ComponentCostEstimate(
            amount_base_currency=Decimal("1.50"), status="exact", profile_ref="flatex_at-2026"
        )


def test_registry_has_no_profiles_by_default() -> None:
    registry = CostProfileRegistry()

    assert registry.is_supported("broker", "flatex_at") is False
    assert registry.registered_profile_ids("broker") == frozenset()


def test_registry_resolve_raises_for_unregistered_profile() -> None:
    registry = CostProfileRegistry()

    with pytest.raises(UnsupportedCostProfileError, match="flatex_at"):
        registry.resolve("broker", "flatex_at")


def test_registry_rejects_unknown_kind() -> None:
    registry = CostProfileRegistry()

    with pytest.raises(ValueError, match="kind"):
        registry.register("crypto_bridge", "flatex_at", _FlatFeeBrokerProfile())


def test_registry_register_and_resolve_round_trips() -> None:
    registry = CostProfileRegistry()
    profile = _FlatFeeBrokerProfile()

    registry.register("broker", "flatex_at", profile)

    assert registry.is_supported("broker", "flatex_at") is True
    assert registry.resolve("broker", "flatex_at") is profile
    assert registry.registered_profile_ids("broker") == frozenset({"flatex_at"})
    # A different kind with the same id remains unregistered.
    assert registry.is_supported("venue", "flatex_at") is False
