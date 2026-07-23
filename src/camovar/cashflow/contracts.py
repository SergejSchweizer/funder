"""Neutral cash-flow result contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from camovar.calculation_status import require_known_status


@dataclass(frozen=True)
class CashFlowResult:
    """One period's gross-to-net cash-flow reconciliation for a portfolio.

    Gross, after-tax, and after-cost amounts must always remain separately
    visible (see the architecture doc's "Architectural Principles" #9).
    """

    period_start: date
    period_end: date
    gross_cash_flow: Decimal
    source_withholding_tax: Decimal
    residence_tax: Decimal
    foreign_tax_credit: Decimal
    transaction_costs: Decimal
    recurring_costs: Decimal
    net_spendable_cash_flow: Decimal
    reinvested_cash_flow: Decimal
    withdrawn_cash_flow: Decimal
    capital_after_cash_flow: Decimal
    nominal_capital_change: Decimal
    real_capital_change: Decimal
    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot precede period_start")
        reinvested_plus_withdrawn = self.reinvested_cash_flow + self.withdrawn_cash_flow
        if reinvested_plus_withdrawn != self.net_spendable_cash_flow:
            raise ValueError(
                "reinvested_cash_flow + withdrawn_cash_flow must equal net_spendable_cash_flow"
            )


__all__ = ["CashFlowResult"]
