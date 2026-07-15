from __future__ import annotations

import pytest

from founder.selection.contracts import CandidateMembership, CurrentSelectionPointer, SelectionState
from founder.update.contracts import (
    ClassificationProfile,
    EvaluationProfile,
    MetricSpec,
    PriceObservation,
    UpdateRequest,
)
from founder.update.service import UpdateService, compute_comparable_asset_metric


class SelectionReadPortFixture:
    def __init__(self, pointer, candidate) -> None:  # type: ignore[no-untyped-def]
        self.pointer = pointer
        self.candidate = candidate

    def current_pointer(self):  # type: ignore[no-untyped-def]
        return self.pointer

    def candidate_membership(self, candidate_membership_id: str):  # type: ignore[no-untyped-def]
        if self.candidate and self.candidate.candidate_membership_id == candidate_membership_id:
            return self.candidate
        return None


def test_asset_metric_cache_uses_log_returns_and_stable_artifact_ids() -> None:
    service = UpdateService()
    observations = (
        PriceObservation("listing_a", "2026-01-01", 100.0),
        PriceObservation("listing_a", "2026-01-02", 110.0),
        PriceObservation("listing_a", "2026-01-03", 99.0),
        PriceObservation("listing_a", "2026-01-04", 121.0),
    )

    artifact = service.compute_asset_metrics(
        "listing_a", observations, MetricSpec("asset", version=2)
    )
    repeated = service.compute_asset_metrics(
        "listing_a", tuple(reversed(observations)), MetricSpec("asset", version=2)
    )

    assert artifact.observation_count == 3
    assert artifact.first_return_date == "2026-01-02"
    assert artifact.max_drawdown < 0.0
    assert artifact.expected_shortfall >= 0.0
    assert artifact.artifact_id == repeated.artifact_id


def test_asset_metric_cache_reports_invalid_prices_without_fake_values() -> None:
    artifact = UpdateService().compute_asset_metrics(
        "listing_a",
        (
            PriceObservation("listing_a", "2026-01-01", 100.0),
            PriceObservation("listing_a", "2026-01-02", 0.0),
        ),
    )

    assert artifact.availability_reason == "invalid_adjusted_close"
    assert artifact.observation_count == 0


def test_screening_classification_boundaries_are_deterministic() -> None:
    service = UpdateService()
    artifact = service.compute_asset_metrics(
        "listing_a",
        (
            PriceObservation("listing_a", "2026-01-01", 100.0),
            PriceObservation("listing_a", "2026-01-02", 101.0),
            PriceObservation("listing_a", "2026-01-03", 102.0),
            PriceObservation("listing_a", "2026-01-04", 103.0),
        ),
    )

    classification = service.classify_asset(artifact, ClassificationProfile(minimum_observations=2))

    assert classification.close_price_path_type == "growing"
    assert classification.total_return_type in {"steadily_growing", "volatile_growing"}
    assert classification.risk_type == "low"
    assert classification.classification_id.startswith("classification_")


def test_selection_calendar_comparable_metrics_and_pair_metrics_are_order_stable() -> None:
    service = UpdateService()
    returns_a = {"2026-01-02": 0.01, "2026-01-03": -0.02, "2026-01-04": 0.03}
    returns_b = {"2026-01-01": 0.50, "2026-01-02": 0.02, "2026-01-03": -0.01, "2026-01-04": 0.04}
    calendar = service.build_calendar(
        final_membership_id="membership_1",
        returns_by_listing={"listing_b": returns_b, "listing_a": returns_a},
    )

    comparable = compute_comparable_asset_metric("listing_a", calendar, returns_a)
    pair_a = service.compute_pair_metrics("listing_a", "listing_b", returns_a, returns_b)
    pair_b = service.compute_pair_metrics("listing_b", "listing_a", returns_b, returns_a)

    assert calendar.dates == ("2026-01-02", "2026-01-03", "2026-01-04")
    assert comparable.calendar_id == calendar.calendar_id
    assert pair_a.pair_id == pair_b.pair_id
    assert pair_a.artifact_id == pair_b.artifact_id
    assert pair_a.observation_count == 3


def test_analysis_manifest_enforces_profile_scale_limit() -> None:
    service = UpdateService()
    calendar = service.build_calendar(
        final_membership_id="membership_1",
        returns_by_listing={"listing_a": {"2026-01-02": 0.01}},
    )

    manifest = service.build_analysis_manifest(
        selection_id="selection_1",
        final_membership_id="membership_1",
        calendar=calendar,
        artifact_ids=("artifact_b", "artifact_a"),
    )
    assert manifest.analysis_id.startswith("selection_analysis_")

    with pytest.raises(ValueError, match="scale limit"):
        service.build_analysis_manifest(
            selection_id="selection_1",
            final_membership_id="membership_1",
            calendar=calendar,
            artifact_ids=("artifact_a", "artifact_b"),
            profile=EvaluationProfile(max_members=1),
        )


def test_update_service_reports_planning_blockers() -> None:
    with pytest.raises(ValueError, match="requires a Selection read port"):
        UpdateService().plan_current_selection(UpdateRequest("selection_1", "run_1"))

    with pytest.raises(ValueError, match="without a current Selection"):
        UpdateService(
            selection_read_port=SelectionReadPortFixture(None, None)
        ).plan_current_selection(UpdateRequest("selection_1", "run_1"))

    paused_pointer = CurrentSelectionPointer("selection_1", "candidate_1", SelectionState.PAUSED)
    with pytest.raises(ValueError, match="paused Selection"):
        UpdateService(
            selection_read_port=SelectionReadPortFixture(paused_pointer, None)
        ).plan_current_selection(UpdateRequest("selection_1", "run_1"))

    empty_candidate = CandidateMembership("selection_1", "catalog_1", ())
    ready_pointer = CurrentSelectionPointer(
        "selection_1", empty_candidate.candidate_membership_id, SelectionState.READY, "membership_1"
    )
    with pytest.raises(ValueError, match="empty Selection"):
        UpdateService(
            selection_read_port=SelectionReadPortFixture(ready_pointer, empty_candidate)
        ).plan_current_selection(UpdateRequest("selection_1", "run_1"))


def test_update_service_ready_selection_plan_skips_finalization() -> None:
    candidate = CandidateMembership("selection_1", "catalog_1", ("listing_a",))
    pointer = CurrentSelectionPointer(
        "selection_1", candidate.candidate_membership_id, SelectionState.READY, "membership_1"
    )
    plan = UpdateService(
        selection_read_port=SelectionReadPortFixture(pointer, candidate)
    ).plan_current_selection(UpdateRequest("selection_1", "run_1"))

    assert [item.work_id for item in plan.work_items] == ["asset:listing_a"]


def test_update_metric_error_paths_are_explicit() -> None:
    service = UpdateService()
    unavailable = service.classify_asset(
        service.compute_asset_metrics(
            "listing_a", (PriceObservation("listing_a", "2026-01-01", 100.0),)
        )
    )
    assert unavailable.risk_type == "unavailable"

    with pytest.raises(ValueError, match="at least one member"):
        service.build_calendar(final_membership_id="membership_1", returns_by_listing={})
    with pytest.raises(ValueError, match="no common dates"):
        service.build_calendar(
            final_membership_id="membership_1",
            returns_by_listing={"a": {"2026-01-01": 0.1}, "b": {"2026-01-02": 0.2}},
        )
    with pytest.raises(ValueError, match="distinct listing ids"):
        service.compute_pair_metrics(
            "listing_a", "listing_a", {"2026-01-01": 0.1}, {"2026-01-01": 0.1}
        )
    with pytest.raises(ValueError, match="at least two common dates"):
        service.compute_pair_metrics(
            "listing_a", "listing_b", {"2026-01-01": 0.1}, {"2026-01-01": 0.1}
        )
