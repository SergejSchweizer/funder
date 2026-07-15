from __future__ import annotations

import pytest

from founder.refresh.contracts import (
    CatalogSnapshot,
    ListingRecord,
    RefreshRequest,
    RefreshRunStatus,
)
from founder.refresh.service import RefreshService
from founder.selection.contracts import (
    CandidateMembership,
    CurrentSelectionPointer,
    Predicate,
    PredicateSet,
    SelectionDefinition,
    SelectionState,
)
from founder.selection.service import SelectionService
from founder.update.contracts import UpdateRequest, UpdateRunManifest, UpdateRunStatus
from founder.update.service import UpdateService


class ProviderFixture:
    def __init__(self, rows: dict[str, tuple[ListingRecord, ...]]) -> None:
        self.rows = rows

    def list_exchange(self, exchange: str) -> tuple[ListingRecord, ...]:
        if exchange == "BROKEN":
            raise RuntimeError("provider unavailable")
        return self.rows.get(exchange, ())


class SelectionReadPortFixture:
    def __init__(
        self,
        *,
        pointer: CurrentSelectionPointer | None,
        candidate: CandidateMembership | None,
    ) -> None:
        self.pointer = pointer
        self.candidate = candidate

    def current_pointer(self) -> CurrentSelectionPointer | None:
        return self.pointer

    def candidate_membership(self, candidate_membership_id: str) -> CandidateMembership | None:
        if self.candidate and self.candidate.candidate_membership_id == candidate_membership_id:
            return self.candidate
        return None


def test_refresh_catalog_sync_reports_partial_failures_and_missing_isins() -> None:
    provider = ProviderFixture(
        {
            "XETRA": (
                ListingRecord(provider="eodhd", exchange="XETRA", code="ETF1", isin="IE00A"),
                ListingRecord(provider="eodhd", exchange="XETRA", code="MISS", isin=""),
            )
        }
    )
    service = RefreshService(catalog_provider=provider)

    result = service.synchronize_catalog(
        RefreshRequest(run_id="refresh-1", exchanges=("XETRA", "BROKEN"))
    )

    assert result.status is RefreshRunStatus.PARTIAL
    assert result.listing_count == 1
    assert result.unique_isin_count == 1
    assert len(result.missing_isins) == 1
    assert result.errors == ("BROKEN: provider unavailable",)
    with pytest.raises(ValueError, match="cannot publish incomplete"):
        service.synchronize_catalog(
            RefreshRequest(run_id="refresh-2", exchanges=("XETRA", "BROKEN"), publish=True)
        )


def test_refresh_market_plan_uses_one_preferred_listing_per_isin() -> None:
    provider = ProviderFixture(
        {
            "AS": (ListingRecord(provider="eodhd", exchange="AS", code="ETF", isin="IE00A"),),
            "XETRA": (ListingRecord(provider="eodhd", exchange="XETRA", code="ETF", isin="IE00A"),),
        }
    )
    result = RefreshService(catalog_provider=provider).synchronize_catalog(
        RefreshRequest(run_id="refresh-1", exchanges=("AS", "XETRA"))
    )

    assert result.status is RefreshRunStatus.SUCCEEDED
    assert len(result.plan.eligible_listing_ids) == 1
    assert len(result.plan.excluded_listings) == 1


def test_selection_service_creates_ready_catalog_only_selection() -> None:
    catalog = _catalog_snapshot(
        (ListingRecord(provider="eodhd", exchange="XETRA", code="ETF", isin="IE00A"),)
    )
    definition = SelectionDefinition(
        predicates=PredicateSet((Predicate("exchange", "eq", "XETRA"),)),
        refresh_snapshot_id=catalog.catalog_snapshot_id,
        canonical_listing_policy_id="policy_1",
    )
    service = SelectionService()

    candidate, pointer = service.create_candidate_membership(definition, catalog)

    assert candidate.listing_ids == (catalog.listings[0].listing_id,)
    assert pointer.state is SelectionState.READY
    assert service.use(pointer) == pointer
    assert service.current_pointer() == pointer


def test_selection_service_marks_metric_selection_pending_update() -> None:
    catalog = _catalog_snapshot(
        (ListingRecord(provider="eodhd", exchange="XETRA", code="ETF", isin="IE00A"),)
    )
    definition = SelectionDefinition(
        predicates=PredicateSet((Predicate("annualized_volatility", "lte", 0.2),)),
        refresh_snapshot_id=catalog.catalog_snapshot_id,
        canonical_listing_policy_id="policy_1",
    )

    _, pointer = SelectionService().create_candidate_membership(definition, catalog)

    assert pointer.state is SelectionState.PENDING_UPDATE
    assert pointer.membership_id == ""


def test_update_service_plans_only_for_current_selection() -> None:
    candidate = CandidateMembership(
        selection_id="selection_1",
        catalog_snapshot_id="catalog_1",
        listing_ids=("listing_b", "listing_a"),
    )
    pointer = CurrentSelectionPointer(
        selection_id="selection_1",
        candidate_membership_id=candidate.candidate_membership_id,
        state=SelectionState.PENDING_UPDATE,
    )
    service = UpdateService(
        selection_read_port=SelectionReadPortFixture(pointer=pointer, candidate=candidate)
    )

    plan = service.plan_current_selection(
        UpdateRequest(selection_id="selection_1", run_id="update-1")
    )

    assert [item.work_id for item in plan.work_items] == [
        "asset:listing_a",
        "asset:listing_b",
        "selection:finalize",
    ]
    assert plan.work_items[-1].depends_on == ("asset:listing_a", "asset:listing_b")
    with pytest.raises(ValueError, match="does not match"):
        service.plan_current_selection(UpdateRequest(selection_id="other", run_id="update-1"))


def test_update_service_publishes_only_published_manifests() -> None:
    service = UpdateService()
    with pytest.raises(ValueError, match="only published"):
        service.publish_manifest(
            UpdateRunManifest(
                run_id="update-1",
                plan_id="plan_1",
                status=UpdateRunStatus.SUCCEEDED,
                published=False,
            )
        )

    pointer = service.publish_manifest(
        UpdateRunManifest(
            run_id="update-1",
            plan_id="plan_1",
            status=UpdateRunStatus.SUCCEEDED,
            published=True,
        )
    )
    assert service.current_pointer() == pointer


def _catalog_snapshot(listings: tuple[ListingRecord, ...]) -> CatalogSnapshot:
    provider = ProviderFixture({"XETRA": listings})
    result = RefreshService(catalog_provider=provider).synchronize_catalog(
        RefreshRequest(run_id="refresh-1", exchanges=("XETRA",))
    )
    assert result.snapshot is not None
    return result.snapshot
