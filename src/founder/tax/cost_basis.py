"""Cost-basis strategy protocol (PR62A).

Jurisdictions differ on disposal/acquisition accounting (moving average,
FIFO, LIFO, specific-lot identification). Founder must not globally assume
one method; a country rule set selects the permitted strategy.
"""

from __future__ import annotations

from typing import Protocol

from founder.tax.contracts import (
    AcquisitionLot,
    BasisAdjustment,
    CostBasisResult,
    Disposal,
    PositionTaxState,
)


class CostBasisStrategy(Protocol):
    """A single disposal/acquisition accounting method."""

    def acquire(self, state: PositionTaxState, lot: AcquisitionLot) -> PositionTaxState: ...

    def dispose(self, state: PositionTaxState, disposal: Disposal) -> CostBasisResult: ...

    def adjust(self, state: PositionTaxState, adjustment: BasisAdjustment) -> PositionTaxState: ...


__all__ = ["CostBasisStrategy"]
