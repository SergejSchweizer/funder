"""Tests for the PR62A cost-basis strategy protocol."""

from datetime import date
from decimal import Decimal

from founder.tax.contracts import (
    AcquisitionLot,
    BasisAdjustment,
    CostBasisResult,
    Disposal,
    PositionTaxState,
)
from founder.tax.cost_basis import CostBasisStrategy


class _MovingAverageCostBasis:
    """A minimal CostBasisStrategy implementation used only for protocol tests."""

    def acquire(self, state: PositionTaxState, lot: AcquisitionLot) -> PositionTaxState:
        new_quantity = state.quantity + lot.quantity
        new_basis = state.cost_basis_base_currency + lot.cost_basis_base_currency
        return PositionTaxState(
            jurisdiction=state.jurisdiction,
            rule_set_id=state.rule_set_id,
            account_id=state.account_id,
            instrument_id=state.instrument_id,
            quantity=new_quantity,
            cost_basis_base_currency=new_basis,
        )

    def dispose(self, state: PositionTaxState, disposal: Disposal) -> CostBasisResult:
        average_cost = state.cost_basis_base_currency / state.quantity
        cost_of_disposal = average_cost * disposal.quantity
        gain = disposal.proceeds_base_currency - cost_of_disposal
        return CostBasisResult(
            state=state,
            realized_gain=max(gain, Decimal("0")),
            realized_loss=max(-gain, Decimal("0")),
            status="exact",
        )

    def adjust(self, state: PositionTaxState, adjustment: BasisAdjustment) -> PositionTaxState:
        new_basis = state.cost_basis_base_currency + adjustment.amount_base_currency
        return PositionTaxState(
            jurisdiction=state.jurisdiction,
            rule_set_id=state.rule_set_id,
            account_id=state.account_id,
            instrument_id=state.instrument_id,
            quantity=state.quantity,
            cost_basis_base_currency=new_basis,
        )


def test_moving_average_strategy_satisfies_cost_basis_strategy_protocol() -> None:
    strategy: CostBasisStrategy = _MovingAverageCostBasis()

    state = PositionTaxState(
        jurisdiction="AT",
        rule_set_id="at-2026",
        account_id="acct-1",
        instrument_id="IE00ABC",
        quantity=Decimal("0"),
        cost_basis_base_currency=Decimal("0"),
    )
    state = strategy.acquire(
        state,
        AcquisitionLot(
            lot_id="lot-1",
            acquired_date=date(2026, 1, 1),
            quantity=Decimal("10"),
            cost_basis_base_currency=Decimal("1000"),
        ),
    )

    disposal = Disposal(
        disposal_date=date(2026, 6, 1),
        quantity=Decimal("5"),
        proceeds_base_currency=Decimal("600"),
    )
    result = strategy.dispose(state, disposal)

    assert result.realized_gain == Decimal("100")
    assert result.realized_loss == Decimal("0")
    assert result.status == "exact"
