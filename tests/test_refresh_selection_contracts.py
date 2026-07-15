from __future__ import annotations

import pytest

from founder.refresh.contracts import (
    CatalogCompleteness,
    CatalogSnapshot,
    InstrumentRecord,
    ListingRecord,
    MarketDatasetVersion,
    MarketDataVersionSet,
    RefreshSnapshotRef,
)
from founder.selection.contracts import (
    FilterPhase,
    Predicate,
    PredicateSet,
    field_definition,
    public_field_listing,
)


def test_refresh_catalog_contracts_have_stable_normalized_identities() -> None:
    instrument = InstrumentRecord(isin=" ie00abc ", name="Fund")
    listing = ListingRecord(
        provider="eodhd",
        exchange="xetra",
        code="abc",
        isin="IE00ABC",
        trading_currency="eur",
        provider_declared_distribution_frequency="monthly",
        historical_nav_available=True,
    )
    same_listing = ListingRecord(provider="EODHD", exchange="XETRA", code="ABC", isin="IE00ABC")

    assert instrument.instrument_id == "IE00ABC"
    assert listing.instrument_id == "IE00ABC"
    assert listing.listing_id == same_listing.listing_id
    assert listing.canonical_payload()["trading_currency"] == "EUR"


def test_refresh_snapshot_ref_pins_catalog_and_market_data_versions() -> None:
    listing = ListingRecord(provider="eodhd", exchange="xetra", code="abc", isin="IE00ABC")
    catalog = CatalogSnapshot(
        instruments=(InstrumentRecord(isin="IE00ABC"),),
        listings=(listing,),
        completeness=CatalogCompleteness(expected_exchanges=1, completed_exchanges=1),
    )
    dataset = MarketDatasetVersion(
        dataset="quotes",
        listing_id=listing.listing_id,
        content_fingerprint="sha256:abc",
        first_date="2020-01-01",
        last_date="2026-07-15",
    )
    version_set = MarketDataVersionSet((dataset,))

    ref = RefreshSnapshotRef(
        catalog_snapshot_id=catalog.catalog_snapshot_id,
        market_data_version_set_id=version_set.market_data_version_set_id,
    )

    assert catalog.completeness.is_complete
    assert ref.catalog_snapshot_id.startswith("catalog_")
    assert ref.market_data_version_set_id.startswith("market_set_")
    with pytest.raises(ValueError, match="must pin"):
        RefreshSnapshotRef(catalog_snapshot_id="", market_data_version_set_id="market_set_1")


def test_selection_predicate_contracts_validate_fields_and_required_metrics() -> None:
    predicates = PredicateSet(
        (
            Predicate("exchange", "in", ("XETRA", "AS")),
            Predicate("annualized_volatility", "lte", 0.2),
            Predicate("downside_capture_ratio", "lte", 0.75),
        )
    )

    assert field_definition("exchange").phase is FilterPhase.CATALOG
    assert predicates.predicate_set_id.startswith("predicate_set_")
    assert [item.metric_name for item in predicates.metric_requirements] == [
        "annualized_volatility",
        "downside_capture_ratio",
    ]


def test_selection_predicate_contracts_reject_invalid_operator_shapes() -> None:
    with pytest.raises(ValueError, match="unknown selection field"):
        Predicate("unknown", "eq", "x")
    with pytest.raises(ValueError, match="not valid"):
        Predicate("exchange", "lte", "XETRA")
    with pytest.raises(ValueError, match="requires a tuple"):
        Predicate("exchange", "in", "XETRA")
    with pytest.raises(ValueError, match="does not accept"):
        Predicate("exchange", "is-null", "XETRA")


def test_public_field_listing_exposes_selection_metadata() -> None:
    fields = {str(item["name"]): item for item in public_field_listing()}

    assert fields["exchange"]["phase"] == "catalog"
    assert fields["downside_capture_ratio"]["benchmark_required"] is True
    assert fields["risk_type"]["metric_requirement"] == "risk_type"
