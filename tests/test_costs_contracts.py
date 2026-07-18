"""Tests for PR62A's jurisdiction-neutral cost contracts."""

from datetime import date
from decimal import Decimal

import pytest

from founder.costs.contracts import ComponentCostEstimate, CostBreakdown, ExecutionContext


def _context(**overrides: object) -> ExecutionContext:
    defaults: dict[str, object] = {
        "investor_country": "AT",
        "broker_id": "flatex_at",
        "broker_country": "AT",
        "venue_id": "xetra",
        "instrument_id": "IE00ABC",
        "instrument_type": "etf",
        "side": "buy",
        "quantity": Decimal("10"),
        "price": Decimal("100.00"),
        "trade_currency": "EUR",
        "base_currency": "EUR",
        "trade_date": date(2026, 3, 1),
    }
    defaults.update(overrides)
    return ExecutionContext(**defaults)  # type: ignore[arg-type]


def test_execution_context_rejects_invalid_side() -> None:
    with pytest.raises(ValueError, match="side"):
        _context(side="short")


def test_execution_context_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity"):
        _context(quantity=Decimal("0"))


def test_execution_context_rejects_non_positive_price() -> None:
    with pytest.raises(ValueError, match="price"):
        _context(price=Decimal("-1"))


def test_component_cost_estimate_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status"):
        ComponentCostEstimate(
            amount_base_currency=Decimal("1.00"), status="maybe", profile_ref="flatex_at-2026"
        )


def test_cost_breakdown_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status"):
        CostBreakdown(
            broker_fee=Decimal("0"),
            venue_fee=Decimal("0"),
            settlement_fee=Decimal("0"),
            estimated_spread_cost=Decimal("0"),
            estimated_slippage=Decimal("0"),
            fx_cost=Decimal("0"),
            transaction_tax=Decimal("0"),
            recurring_cost_allocation=Decimal("0"),
            total_cost=Decimal("0"),
            status="maybe",
        )
