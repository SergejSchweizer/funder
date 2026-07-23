"""Tests for PR62A's jurisdiction-neutral tax contracts."""

from datetime import date
from decimal import Decimal

import pytest

from camovar.tax.contracts import (
    FundTaxFactsResult,
    InvestorTaxProfile,
    TaxCalculationResult,
    TaxEvent,
    TaxRuleSetRef,
)


def test_investor_tax_profile_requires_non_empty_fields() -> None:
    with pytest.raises(ValueError, match="residence_country"):
        InvestorTaxProfile(
            residence_country="",
            investor_type="private",
            account_type="ordinary",
            filing_currency="EUR",
            tax_year=2026,
        )


def test_investor_tax_profile_rejects_implausible_tax_year() -> None:
    with pytest.raises(ValueError, match="tax_year"):
        InvestorTaxProfile(
            residence_country="AT",
            investor_type="private",
            account_type="ordinary",
            filing_currency="EUR",
            tax_year=1900,
        )


def test_tax_rule_set_ref_covers_validity_window() -> None:
    rule_set = TaxRuleSetRef(
        jurisdiction="AT",
        rule_set_id="at-private-capital-income",
        version="2026.1",
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        reviewed_at=date(2026, 1, 1),
        verification_status="verified_estimate",
        source_refs=("https://example.invalid/at-tax-law",),
    )

    assert rule_set.covers(date(2026, 6, 15)) is True
    assert rule_set.covers(date(2025, 12, 31)) is False
    assert rule_set.covers(date(2027, 1, 1)) is False


def test_tax_rule_set_ref_open_ended_valid_to_covers_future_dates() -> None:
    rule_set = TaxRuleSetRef(
        jurisdiction="AT",
        rule_set_id="at-private-capital-income",
        version="2026.1",
        valid_from=date(2026, 1, 1),
        valid_to=None,
        reviewed_at=date(2026, 1, 1),
        verification_status="verified_estimate",
    )

    assert rule_set.covers(date(2099, 1, 1)) is True


def test_tax_rule_set_ref_rejects_valid_to_before_valid_from() -> None:
    with pytest.raises(ValueError, match="valid_to cannot precede valid_from"):
        TaxRuleSetRef(
            jurisdiction="AT",
            rule_set_id="at-private-capital-income",
            version="2026.1",
            valid_from=date(2026, 6, 1),
            valid_to=date(2026, 1, 1),
            reviewed_at=date(2026, 1, 1),
            verification_status="verified_estimate",
        )


def test_tax_rule_set_ref_rejects_unknown_verification_status() -> None:
    with pytest.raises(ValueError, match="verification_status"):
        TaxRuleSetRef(
            jurisdiction="AT",
            rule_set_id="at-private-capital-income",
            version="2026.1",
            valid_from=date(2026, 1, 1),
            valid_to=None,
            reviewed_at=date(2026, 1, 1),
            verification_status="definitely_true",
        )


def test_tax_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValueError, match="event_type"):
        TaxEvent(
            event_id="evt-1",
            event_date=date(2026, 3, 1),
            event_type="lottery_winnings",
            instrument_id="IE00ABC",
            gross_amount=Decimal("10.00"),
            currency="EUR",
        )


def test_tax_event_accepts_known_event_type() -> None:
    event = TaxEvent(
        event_id="evt-1",
        event_date=date(2026, 3, 1),
        event_type="distribution",
        instrument_id="IE00ABC",
        gross_amount=Decimal("10.00"),
        currency="EUR",
    )

    assert event.event_type == "distribution"


def test_tax_calculation_result_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status"):
        TaxCalculationResult(
            gross_amount_base=Decimal("10.00"),
            source_withholding_tax=Decimal("0"),
            residence_tax_before_credits=Decimal("0"),
            foreign_tax_credit=Decimal("0"),
            residence_tax_after_credits=Decimal("0"),
            allowance_used=Decimal("0"),
            realized_loss_offset=Decimal("0"),
            total_tax=Decimal("0"),
            net_amount=Decimal("10.00"),
            status="probably_fine",
            rule_set_ref=None,
        )


def test_fund_tax_facts_result_requires_non_empty_isin_and_jurisdiction() -> None:
    with pytest.raises(ValueError, match="isin"):
        FundTaxFactsResult(
            isin="",
            jurisdiction="AT",
            tax_year=2026,
            fund_tax_classification="reporting",
            reporting_status="reported",
            distribution_tax_base=Decimal("0"),
            deemed_income_tax_base=Decimal("0"),
            foreign_tax_credit=Decimal("0"),
            cost_basis_adjustment=Decimal("0"),
            source_ref="oekb-2026",
            verification_status="unavailable",
        )
