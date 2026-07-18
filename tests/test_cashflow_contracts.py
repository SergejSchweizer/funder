"""Tests for PR62A's neutral cash-flow result contract."""

from datetime import date
from decimal import Decimal

import pytest

from founder.cashflow.contracts import CashFlowResult


def _result(**overrides: object) -> CashFlowResult:
    defaults: dict[str, object] = {
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        "gross_cash_flow": Decimal("100.00"),
        "source_withholding_tax": Decimal("15.00"),
        "residence_tax": Decimal("10.00"),
        "foreign_tax_credit": Decimal("5.00"),
        "transaction_costs": Decimal("1.00"),
        "recurring_costs": Decimal("0.50"),
        "net_spendable_cash_flow": Decimal("68.50"),
        "reinvested_cash_flow": Decimal("0"),
        "withdrawn_cash_flow": Decimal("68.50"),
        "capital_after_cash_flow": Decimal("1000.00"),
        "nominal_capital_change": Decimal("0"),
        "real_capital_change": Decimal("-2.00"),
        "status": "verified_estimate",
    }
    defaults.update(overrides)
    return CashFlowResult(**defaults)  # type: ignore[arg-type]


def test_cash_flow_result_accepts_reconciled_amounts() -> None:
    result = _result()

    assert result.net_spendable_cash_flow == Decimal("68.50")


def test_cash_flow_result_rejects_period_end_before_start() -> None:
    with pytest.raises(ValueError, match="period_end cannot precede period_start"):
        _result(period_start=date(2026, 2, 1), period_end=date(2026, 1, 1))


def test_cash_flow_result_rejects_unreconciled_split() -> None:
    with pytest.raises(ValueError, match="reinvested_cash_flow \\+ withdrawn_cash_flow"):
        _result(reinvested_cash_flow=Decimal("10.00"), withdrawn_cash_flow=Decimal("10.00"))


def test_cash_flow_result_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status"):
        _result(status="probably_fine")
