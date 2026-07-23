"""Cost contracts shared by broker, venue, execution, FX, and tax profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from camovar.calculation_status import require_known_status


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


@dataclass(frozen=True)
class ExecutionContext:
    """The trade-level facts needed to resolve broker, venue, and tax costs."""

    investor_country: str
    broker_id: str
    broker_country: str
    venue_id: str
    instrument_id: str
    instrument_type: str
    side: str
    quantity: Decimal
    price: Decimal
    trade_currency: str
    base_currency: str
    trade_date: date

    def __post_init__(self) -> None:
        _require_text(self.investor_country, "investor_country")
        _require_text(self.broker_id, "broker_id")
        _require_text(self.venue_id, "venue_id")
        _require_text(self.instrument_id, "instrument_id")
        _require_text(self.trade_currency, "trade_currency")
        _require_text(self.base_currency, "base_currency")
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.price <= 0:
            raise ValueError("price must be positive")


@dataclass(frozen=True)
class ComponentCostEstimate:
    """One cost-component profile's contribution to a `CostBreakdown`."""

    amount_base_currency: Decimal
    status: str
    profile_ref: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")
        _require_text(self.profile_ref, "profile_ref")


@dataclass(frozen=True)
class CostBreakdown:
    """The full composed cost of one execution."""

    broker_fee: Decimal
    venue_fee: Decimal
    settlement_fee: Decimal
    estimated_spread_cost: Decimal
    estimated_slippage: Decimal
    fx_cost: Decimal
    transaction_tax: Decimal
    recurring_cost_allocation: Decimal
    total_cost: Decimal
    status: str
    profile_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")


class CostComponentProfile(Protocol):
    """A single, versioned, effective-dated cost-component profile.

    Implementations cover broker fees, venue fees, execution/slippage
    models, FX conversion costs, jurisdiction transaction taxes, and
    recurring account costs. Each is resolved and registered independently
    so that, for example, the same tax residence can be priced under
    different brokers without changing residence-tax rules.
    """

    def estimate(self, context: ExecutionContext) -> ComponentCostEstimate: ...


__all__ = [
    "ComponentCostEstimate",
    "CostBreakdown",
    "CostComponentProfile",
    "ExecutionContext",
]
