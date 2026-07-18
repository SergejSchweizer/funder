"""Jurisdiction-neutral tax contracts (PR62A).

These dataclasses describe the shape of tax calculation requests and
results without encoding any country's actual tax rate, allowance, or
threshold. Concrete rates and mechanics belong in versioned per-country
rule resources consumed by a `CountryTaxAdapter` implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from founder.calculation_status import require_known_status


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def _empty_attributes() -> Mapping[str, str | int | float | bool]:
    return {}


def _empty_metadata() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class InvestorTaxProfile:
    """The investor-side facts needed to resolve a jurisdiction's tax rules."""

    residence_country: str
    investor_type: str
    account_type: str
    filing_currency: str
    tax_year: int
    attributes: Mapping[str, str | int | float | bool] = field(default_factory=_empty_attributes)

    def __post_init__(self) -> None:
        _require_text(self.residence_country, "residence_country")
        _require_text(self.investor_type, "investor_type")
        _require_text(self.account_type, "account_type")
        _require_text(self.filing_currency, "filing_currency")
        if self.tax_year < 1970:
            raise ValueError("tax_year must be a plausible calendar year")


@dataclass(frozen=True)
class TaxRuleSetRef:
    """An immutable, versioned, source-attributed reference to a rule set."""

    jurisdiction: str
    rule_set_id: str
    version: str
    valid_from: date
    valid_to: date | None
    reviewed_at: date
    verification_status: str
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.jurisdiction, "jurisdiction")
        _require_text(self.rule_set_id, "rule_set_id")
        _require_text(self.version, "version")
        require_known_status(self.verification_status, "verification_status")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot precede valid_from")

    def covers(self, event_date: date) -> bool:
        """True when `event_date` falls within this rule set's validity window."""
        if event_date < self.valid_from:
            return False
        return self.valid_to is None or event_date <= self.valid_to


TAX_EVENT_TYPES = (
    "distribution",
    "interest",
    "realized_gain",
    "realized_loss",
    "deemed_distribution",
    "accumulating_fund_income",
    "fund_tax_adjustment",
    "foreign_withholding",
    "corporate_action",
    "fee_tax_adjustment",
)


@dataclass(frozen=True)
class TaxEvent:
    """A single taxable event to be classified and calculated."""

    event_id: str
    event_date: date
    event_type: str
    instrument_id: str
    gross_amount: Decimal
    currency: str
    source_country: str | None = None
    metadata: Mapping[str, str] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.instrument_id, "instrument_id")
        _require_text(self.currency, "currency")
        if self.event_type not in TAX_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {TAX_EVENT_TYPES}, got {self.event_type!r}"
            )


@dataclass(frozen=True)
class TaxCalculationResult:
    """The full breakdown of a single tax event's calculation."""

    gross_amount_base: Decimal
    source_withholding_tax: Decimal
    residence_tax_before_credits: Decimal
    foreign_tax_credit: Decimal
    residence_tax_after_credits: Decimal
    allowance_used: Decimal
    realized_loss_offset: Decimal
    total_tax: Decimal
    net_amount: Decimal
    status: str
    rule_set_ref: TaxRuleSetRef | None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstrumentTaxFacts:
    """Instrument-level facts an adapter needs to classify tax treatment."""

    isin: str
    instrument_type: str
    instrument_domicile: str
    fund_tax_status: str

    def __post_init__(self) -> None:
        _require_text(self.isin, "isin")
        _require_text(self.instrument_type, "instrument_type")
        _require_text(self.instrument_domicile, "instrument_domicile")


@dataclass(frozen=True)
class TaxClassification:
    isin: str
    jurisdiction: str
    classification: str
    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")


@dataclass(frozen=True)
class TaxEventRequest:
    profile: InvestorTaxProfile
    event: TaxEvent


@dataclass(frozen=True)
class AcquisitionLot:
    lot_id: str
    acquired_date: date
    quantity: Decimal
    cost_basis_base_currency: Decimal


@dataclass(frozen=True)
class Disposal:
    disposal_date: date
    quantity: Decimal
    proceeds_base_currency: Decimal


@dataclass(frozen=True)
class BasisAdjustment:
    adjustment_date: date
    amount_base_currency: Decimal
    reason: str


@dataclass(frozen=True)
class PositionTaxState:
    """Persisted per-position tax state (see "Cost-Basis Methods")."""

    jurisdiction: str
    rule_set_id: str
    account_id: str
    instrument_id: str
    quantity: Decimal
    cost_basis_base_currency: Decimal
    realized_gain_ytd: Decimal = Decimal("0")
    realized_loss_ytd: Decimal = Decimal("0")
    foreign_tax_credit_ytd: Decimal = Decimal("0")
    last_event_id: str | None = None


@dataclass(frozen=True)
class CostBasisResult:
    state: PositionTaxState
    realized_gain: Decimal
    realized_loss: Decimal
    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")


@dataclass(frozen=True)
class CostBasisRequest:
    state: PositionTaxState
    disposal: Disposal


@dataclass(frozen=True)
class LossOffsetRequest:
    tax_year: int
    realized_gains_by_category: Mapping[str, Decimal]
    realized_losses_by_category: Mapping[str, Decimal]
    carry_forward_state: Mapping[str, Decimal]


@dataclass(frozen=True)
class LossOffsetResult:
    offset_gains_by_category: Mapping[str, Decimal]
    remaining_losses_by_category: Mapping[str, Decimal]
    carry_forward_state: Mapping[str, Decimal]
    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")


@dataclass(frozen=True)
class TaxYearCloseRequest:
    tax_year: int
    jurisdiction: str
    account_id: str


@dataclass(frozen=True)
class TaxYearResult:
    tax_year: int
    jurisdiction: str
    account_id: str
    carry_forward_state: Mapping[str, Decimal]
    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_known_status(self.status, "status")


@dataclass(frozen=True)
class FundTaxFactsResult:
    """A fund-tax data provider's answer for one ISIN/jurisdiction/tax year."""

    isin: str
    jurisdiction: str
    tax_year: int
    fund_tax_classification: str
    reporting_status: str
    distribution_tax_base: Decimal
    deemed_income_tax_base: Decimal
    foreign_tax_credit: Decimal
    cost_basis_adjustment: Decimal
    source_ref: str
    verification_status: str

    def __post_init__(self) -> None:
        _require_text(self.isin, "isin")
        _require_text(self.jurisdiction, "jurisdiction")
        require_known_status(self.verification_status, "verification_status")


__all__ = [
    "TAX_EVENT_TYPES",
    "AcquisitionLot",
    "BasisAdjustment",
    "CostBasisRequest",
    "CostBasisResult",
    "Disposal",
    "FundTaxFactsResult",
    "InstrumentTaxFacts",
    "InvestorTaxProfile",
    "LossOffsetRequest",
    "LossOffsetResult",
    "PositionTaxState",
    "TaxCalculationResult",
    "TaxClassification",
    "TaxEvent",
    "TaxEventRequest",
    "TaxRuleSetRef",
    "TaxYearCloseRequest",
    "TaxYearResult",
    "ValidationResult",
]
