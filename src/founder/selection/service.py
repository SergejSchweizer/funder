"""Selection application service."""

from __future__ import annotations

from founder.refresh.contracts import CatalogSnapshot, ListingRecord
from founder.selection.contracts import (
    SELECTION_CONTRACT_VERSION,
    CandidateMembership,
    CurrentSelectionPointer,
    FilterPhase,
    FinalMembership,
    MetricEvidence,
    Predicate,
    PredicateValue,
    SelectionDefinition,
    SelectionState,
    field_definition,
)


class SelectionService:
    """Pure Selection operations over pinned Refresh contracts."""

    def __init__(self) -> None:
        self._current_pointer: CurrentSelectionPointer | None = None

    @staticmethod
    def contract_version() -> str:
        return SELECTION_CONTRACT_VERSION.qualified_name

    def create_candidate_membership(
        self,
        definition: SelectionDefinition,
        catalog_snapshot: CatalogSnapshot,
    ) -> tuple[CandidateMembership, CurrentSelectionPointer]:
        listing_ids = tuple(
            listing.listing_id
            for listing in catalog_snapshot.listings
            if listing.active and _matches_catalog_predicates(listing, definition)
        )
        candidate = CandidateMembership(
            selection_id=definition.selection_id,
            catalog_snapshot_id=catalog_snapshot.catalog_snapshot_id,
            listing_ids=listing_ids,
        )
        state = (
            SelectionState.EMPTY
            if not listing_ids
            else SelectionState.PENDING_UPDATE
            if definition.predicates.metric_requirements
            else SelectionState.READY
        )
        pointer = CurrentSelectionPointer(
            selection_id=definition.selection_id,
            candidate_membership_id=candidate.candidate_membership_id,
            membership_id=candidate.candidate_membership_id
            if state is SelectionState.READY
            else "",
            state=state,
        )
        return candidate, pointer

    def use(self, pointer: CurrentSelectionPointer) -> CurrentSelectionPointer:
        self._current_pointer = pointer
        return pointer

    def current_pointer(self) -> CurrentSelectionPointer | None:
        return self._current_pointer

    def finalize_membership(
        self,
        candidate: CandidateMembership,
        evidence: tuple[MetricEvidence, ...],
    ) -> FinalMembership:
        if not evidence:
            raise ValueError("selection finalization requires metric evidence")
        return FinalMembership(
            candidate_membership_id=candidate.candidate_membership_id,
            evidence_manifest_id=evidence[0].metric_name,
            listing_ids=candidate.listing_ids,
        )


def _matches_catalog_predicates(listing: ListingRecord, definition: SelectionDefinition) -> bool:
    for predicate in definition.predicates.predicates:
        if field_definition(predicate.field).phase is not FilterPhase.CATALOG:
            continue
        if not _matches_predicate(_catalog_value(listing, predicate.field), predicate):
            return False
    return True


def _catalog_value(listing: ListingRecord, field: str) -> object:
    if field == "exchange":
        return listing.exchange.strip().upper()
    if field == "trading_currency":
        return listing.trading_currency.strip().upper()
    if field == "declared_payout_frequency":
        return listing.provider_declared_distribution_frequency.strip().upper()
    raise ValueError(f"unsupported catalog field: {field}")


def _matches_predicate(actual: object, predicate: Predicate) -> bool:
    expected = predicate.value
    operator = predicate.operator
    if operator == "eq":
        return actual == _normalize_expected(expected)
    if operator == "ne":
        return actual != _normalize_expected(expected)
    if operator == "in":
        return actual in {_normalize_expected(item) for item in _as_tuple(expected)}
    if operator == "not-in":
        return actual not in {_normalize_expected(item) for item in _as_tuple(expected)}
    if operator == "is-null":
        return actual in (None, "")
    if operator == "not-null":
        return actual not in (None, "")
    if operator == "contains" and isinstance(actual, str) and isinstance(expected, str):
        return expected.upper() in actual
    if operator == "starts-with" and isinstance(actual, str) and isinstance(expected, str):
        return actual.startswith(expected.upper())
    raise ValueError(f"unsupported catalog operator: {operator}")


def _as_tuple(value: PredicateValue) -> tuple[PredicateValue, ...]:
    return value if isinstance(value, tuple) else (value,)


def _normalize_expected(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


__all__ = ["SelectionService"]
