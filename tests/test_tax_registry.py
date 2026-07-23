"""Tests for PR62A's jurisdiction-neutral country tax-adapter registry."""

from datetime import date
from decimal import Decimal

import pytest

from camovar.tax.contracts import (
    CostBasisRequest,
    CostBasisResult,
    InstrumentTaxFacts,
    InvestorTaxProfile,
    LossOffsetRequest,
    LossOffsetResult,
    TaxCalculationResult,
    TaxClassification,
    TaxEventRequest,
    TaxYearCloseRequest,
    TaxYearResult,
    ValidationResult,
)
from camovar.tax.registry import (
    EU_COUNTRY_CODES,
    CountryTaxRegistry,
    UnsupportedCountryError,
)


class _StubCountryTaxAdapter:
    """A minimal CountryTaxAdapter used only to exercise the registry."""

    def validate_profile(self, profile: InvestorTaxProfile) -> ValidationResult:
        return ValidationResult(valid=True)

    def classify_instrument(self, instrument: InstrumentTaxFacts) -> TaxClassification:
        return TaxClassification(
            isin=instrument.isin, jurisdiction="AT", classification="reporting", status="exact"
        )

    def calculate_event(self, request: TaxEventRequest) -> TaxCalculationResult:
        return TaxCalculationResult(
            gross_amount_base=request.event.gross_amount,
            source_withholding_tax=Decimal("0"),
            residence_tax_before_credits=Decimal("0"),
            foreign_tax_credit=Decimal("0"),
            residence_tax_after_credits=Decimal("0"),
            allowance_used=Decimal("0"),
            realized_loss_offset=Decimal("0"),
            total_tax=Decimal("0"),
            net_amount=request.event.gross_amount,
            status="exact",
            rule_set_ref=None,
        )

    def update_cost_basis(self, request: CostBasisRequest) -> CostBasisResult:
        return CostBasisResult(
            state=request.state,
            realized_gain=Decimal("0"),
            realized_loss=Decimal("0"),
            status="exact",
        )

    def apply_loss_offset(self, request: LossOffsetRequest) -> LossOffsetResult:
        return LossOffsetResult(
            offset_gains_by_category={},
            remaining_losses_by_category={},
            carry_forward_state=request.carry_forward_state,
            status="exact",
        )

    def close_tax_year(self, request: TaxYearCloseRequest) -> TaxYearResult:
        return TaxYearResult(
            tax_year=request.tax_year,
            jurisdiction=request.jurisdiction,
            account_id=request.account_id,
            carry_forward_state={},
            status="exact",
        )


def test_eu_country_codes_has_27_member_states() -> None:
    assert len(EU_COUNTRY_CODES) == 27
    assert {"AT", "DE", "FR", "IE", "NL"}.issubset(EU_COUNTRY_CODES)
    assert "US" not in EU_COUNTRY_CODES
    assert "GB" not in EU_COUNTRY_CODES


def test_registry_has_no_supported_countries_by_default() -> None:
    registry = CountryTaxRegistry()

    for country_code in EU_COUNTRY_CODES:
        assert registry.is_known_country(country_code) is True
        assert registry.is_supported(country_code) is False


def test_registry_resolve_raises_for_known_but_unregistered_country() -> None:
    registry = CountryTaxRegistry()

    with pytest.raises(UnsupportedCountryError, match="AT"):
        registry.resolve("AT")


def test_registry_resolve_raises_for_unknown_country() -> None:
    registry = CountryTaxRegistry()

    with pytest.raises(UnsupportedCountryError, match="US"):
        registry.resolve("US")


def test_registry_register_rejects_unknown_country_code() -> None:
    registry = CountryTaxRegistry()

    with pytest.raises(ValueError, match="not a known jurisdiction"):
        registry.register("US", _StubCountryTaxAdapter())


def test_registry_register_and_resolve_round_trips() -> None:
    registry = CountryTaxRegistry()
    adapter = _StubCountryTaxAdapter()

    registry.register("AT", adapter)

    assert registry.is_supported("AT") is True
    assert registry.resolve("AT") is adapter
    assert registry.supported_country_codes() == frozenset({"AT"})
    # Other known countries remain unsupported.
    assert registry.is_supported("DE") is False


def test_stub_adapter_satisfies_the_protocol_end_to_end() -> None:
    registry = CountryTaxRegistry()
    adapter = _StubCountryTaxAdapter()
    registry.register("AT", adapter)
    resolved = registry.resolve("AT")

    profile = InvestorTaxProfile(
        residence_country="AT",
        investor_type="private",
        account_type="ordinary",
        filing_currency="EUR",
        tax_year=2026,
    )
    assert resolved.validate_profile(profile).valid is True

    from camovar.tax.contracts import TaxEvent

    event = TaxEvent(
        event_id="evt-1",
        event_date=date(2026, 3, 1),
        event_type="distribution",
        instrument_id="IE00ABC",
        gross_amount=Decimal("10.00"),
        currency="EUR",
    )
    result = resolved.calculate_event(TaxEventRequest(profile=profile, event=event))
    assert result.net_amount == Decimal("10.00")
