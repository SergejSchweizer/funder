from __future__ import annotations

import pytest

from founder.selection.contracts import (
    CandidateMembership,
    CurrentSelectionPointer,
    FinalMembership,
    Predicate,
    PredicateSet,
    SelectionDefinition,
    SelectionState,
)
from founder.update.contracts import (
    MetricCacheKey,
    MetricSpec,
    PinnedUpdateInput,
    UpdatePlan,
    UpdateWorkItem,
    UpdateWorkKind,
)


def test_selection_definition_and_membership_ids_ignore_input_order() -> None:
    predicates = PredicateSet((Predicate("exchange", "in", ("XETRA", "AS")),))
    definition = SelectionDefinition(
        predicates=predicates,
        refresh_snapshot_id="catalog_1",
        canonical_listing_policy_id="policy_1",
    )
    candidate_a = CandidateMembership(
        selection_id=definition.selection_id,
        catalog_snapshot_id="catalog_1",
        listing_ids=("listing_b", "listing_a"),
    )
    candidate_b = CandidateMembership(
        selection_id=definition.selection_id,
        catalog_snapshot_id="catalog_1",
        listing_ids=("listing_a", "listing_b"),
    )
    final = FinalMembership(
        candidate_membership_id=candidate_a.candidate_membership_id,
        evidence_manifest_id="evidence_1",
        listing_ids=("listing_b", "listing_a"),
    )

    assert definition.selection_id.startswith("selection_")
    assert candidate_a.candidate_membership_id == candidate_b.candidate_membership_id
    assert final.membership_id.startswith("final_membership_")


def test_ready_selection_pointer_requires_final_membership() -> None:
    with pytest.raises(ValueError, match="requires a final membership"):
        CurrentSelectionPointer(
            selection_id="selection_1",
            candidate_membership_id="candidate_1",
            state=SelectionState.READY,
        )

    pointer = CurrentSelectionPointer(
        selection_id="selection_1",
        candidate_membership_id="candidate_1",
        membership_id="membership_1",
        state=SelectionState.READY,
    )
    assert pointer.state is SelectionState.READY


def test_update_metric_keys_and_plan_ids_are_deterministic() -> None:
    spec = MetricSpec("annualized_volatility", version=1)
    cache_key = MetricCacheKey(
        kind="asset",
        subject_id="listing_1",
        metric_spec_id=spec.metric_spec_id,
        input_version_id="market_1",
    )
    pinned = PinnedUpdateInput(
        selection_id="selection_1",
        candidate_membership_id="candidate_1",
        refresh_snapshot_id="refresh_1",
    )
    plan_a = UpdatePlan(
        pinned_input=pinned,
        work_items=(
            UpdateWorkItem(
                "finalize", UpdateWorkKind.SELECTION_FINALIZATION, (cache_key.cache_key_id,)
            ),
            UpdateWorkItem(cache_key.cache_key_id, UpdateWorkKind.ASSET_METRIC),
        ),
    )
    plan_b = UpdatePlan(
        pinned_input=pinned,
        work_items=tuple(reversed(plan_a.work_items)),
    )

    assert spec.metric_spec_id.startswith("metric_spec_")
    assert cache_key.cache_key_id.startswith("metric_cache_")
    assert plan_a.plan_id == plan_b.plan_id
