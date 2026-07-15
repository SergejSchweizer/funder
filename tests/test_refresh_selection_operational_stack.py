from __future__ import annotations

import pytest

from founder.refresh.contracts import ListingRecord, RefreshRequest
from founder.refresh.service import RefreshService
from founder.selection.contracts import (
    BenchmarkRef,
    CandidateMembership,
    FinalMembership,
    MetricEvidence,
    Predicate,
    PredicateSet,
    SelectionDefinition,
)
from founder.selection.service import SelectionService


class ProviderFixture:
    def list_exchange(self, exchange: str) -> tuple[ListingRecord, ...]:
        return (
            ListingRecord(
                provider="eodhd",
                exchange=exchange,
                code="ETF1",
                isin="IE00A",
                historical_nav_available=True,
            ),
            ListingRecord(provider="eodhd", exchange=exchange, code="ETF2", isin="IE00B"),
        )


def test_refresh_publishes_complete_current_pointer_and_version_set() -> None:
    service = RefreshService(catalog_provider=ProviderFixture())
    request = RefreshRequest(run_id="refresh-1", exchanges=("XETRA",), publish=True)

    result = service.synchronize_catalog(request)
    assert result.snapshot is not None
    version_set = service.build_market_data_version_set(
        dataset="quotes",
        rows_by_listing={
            result.snapshot.listings[0].listing_id: (
                {"date": "2026-01-02", "adjusted_close": 100.0},
                {"date": "2026-01-03", "adjusted_close": 101.0},
            )
        },
    )
    pointer = service.publish_current_pointer(
        request=request,
        snapshot=result.snapshot,
        market_data_version_set=version_set,
    )

    assert pointer == service.current_pointer()
    assert pointer.catalog_snapshot_id == result.snapshot.catalog_snapshot_id
    assert version_set.market_data_version_set_id.startswith("market_set_")
    assert service.result_summary(result)["historical_nav_capable_count"] == 1


def test_selection_requires_benchmark_for_benchmark_relative_predicates() -> None:
    refresh = RefreshService(catalog_provider=ProviderFixture())
    result = refresh.synchronize_catalog(RefreshRequest(run_id="refresh-1", exchanges=("XETRA",)))
    assert result.snapshot is not None
    definition = SelectionDefinition(
        predicates=PredicateSet((Predicate("downside_capture_ratio", "lte", 0.75),)),
        refresh_snapshot_id=result.snapshot.catalog_snapshot_id,
        canonical_listing_policy_id="policy_1",
    )

    with pytest.raises(ValueError, match="requires an explicit benchmark"):
        SelectionService().create_candidate_membership(definition, result.snapshot)

    benchmarked = SelectionDefinition(
        predicates=definition.predicates,
        refresh_snapshot_id=definition.refresh_snapshot_id,
        canonical_listing_policy_id=definition.canonical_listing_policy_id,
        benchmark=BenchmarkRef("benchmark_listing", result.snapshot.catalog_snapshot_id),
    )
    candidate, pointer = SelectionService().create_candidate_membership(
        benchmarked, result.snapshot
    )

    assert candidate.listing_ids
    assert pointer.state.value == "pending_update"


def test_selection_names_status_and_membership_diffs_are_stable() -> None:
    service = SelectionService()
    definition = SelectionDefinition(
        predicates=PredicateSet(
            (
                Predicate("exchange", "eq", "XETRA"),
                Predicate("trading_currency", "eq", "EUR"),
            )
        ),
        refresh_snapshot_id="catalog_1",
        canonical_listing_policy_id="policy_1",
    )
    previous = CandidateMembership("selection_1", "catalog_1", ("listing_a", "listing_b"))
    current = CandidateMembership("selection_1", "catalog_1", ("listing_b", "listing_c"))
    pointer = service.use(
        service.create_candidate_membership(
            definition,
            RefreshService(catalog_provider=ProviderFixture())
            .synchronize_catalog(RefreshRequest(run_id="refresh-1", exchanges=("XETRA",)))
            .snapshot,  # type: ignore[arg-type]
        )[1]
    )

    name = service.readable_name(definition, max_length=64)
    diff = service.diff_memberships(previous, current)

    assert name.startswith("exchange_eq_xetra_trading_currency_eq_eur_")
    assert service.status()["selection_id"] == pointer.selection_id
    assert diff.added_listing_ids == ("listing_c",)
    assert diff.removed_listing_ids == ("listing_a",)


def test_selection_service_covers_catalog_operators_and_final_membership() -> None:
    result = RefreshService(catalog_provider=ProviderFixture()).synchronize_catalog(
        RefreshRequest(run_id="refresh-1", exchanges=("XETRA",))
    )
    assert result.snapshot is not None
    service = SelectionService()
    assert service.status() == {"state": "none"}
    definition = SelectionDefinition(
        predicates=PredicateSet(
            (
                Predicate("exchange", "in", ("XETRA", "AS")),
                Predicate("exchange", "not-in", ("AS",)),
                Predicate("trading_currency", "is-null"),
                Predicate("declared_payout_frequency", "not-null"),
            )
        ),
        refresh_snapshot_id=result.snapshot.catalog_snapshot_id,
        canonical_listing_policy_id="policy_1",
    )
    candidate, _ = service.create_candidate_membership(definition, result.snapshot)

    assert candidate.listing_ids == ()
    with pytest.raises(ValueError, match="requires metric evidence"):
        service.finalize_membership(candidate, ())

    final = service.finalize_membership(
        candidate,
        (MetricEvidence("annualized_volatility", "listing_a", True),),
    )
    assert final.membership_id.startswith("final_membership_")
    previous_final = FinalMembership("candidate_1", "evidence_1", ("listing_a",))
    current_final = FinalMembership("candidate_2", "evidence_2", ("listing_a", "listing_b"))
    assert service.diff_memberships(previous_final, current_final).added_listing_ids == (
        "listing_b",
    )


def test_selection_readable_name_handles_tuple_values_and_truncation() -> None:
    definition = SelectionDefinition(
        predicates=PredicateSet((Predicate("exchange", "in", ("XETRA", "AS")),)),
        refresh_snapshot_id="catalog_1",
        canonical_listing_policy_id="policy_1",
    )

    assert SelectionService().readable_name(definition, max_length=30).startswith("exchange_")
