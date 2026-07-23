from __future__ import annotations

import pytest

from camovar.artifact_cache import (
    ArtifactCacheError,
    InMemoryAnalysisRunStore,
    InMemoryArtifactCache,
    PortfolioArtifactKey,
    ReturnArtifactKey,
    create_portfolio_artifact,
    create_return_artifact,
)
from camovar.scoped_inputs import ScopedMarketInputs, SelectionInputRef, UserDataSnapshotRef


def _inputs(user_id: str = "user-a", snapshot_hash: str = "quote-hash") -> ScopedMarketInputs:
    snapshot = UserDataSnapshotRef(
        user_id=user_id,
        snapshot_id=f"snapshot-{user_id}",
        snapshot_hash=snapshot_hash,
    )
    selection = SelectionInputRef("selection-1", "selection-hash", ("obs-1", "obs-2"))
    return ScopedMarketInputs(
        snapshot=snapshot,
        selection=selection,
        quote_rows=(
            {"market_object_id": "obs-1", "close": 100},
            {"market_object_id": "obs-2", "close": 200},
        ),
        input_hash=snapshot_hash,
    )


def _return_key(
    inputs: ScopedMarketInputs, listing_id: str, *, end: str = "2026-01-01"
) -> ReturnArtifactKey:
    return ReturnArtifactKey(
        listing_id=listing_id,
        quote_snapshot_hash=inputs.input_hash,
        dividend_snapshot_hash="dividend-hash",
        date_window=("2025-01-01", end),
        return_parameters={"return_type": "log"},
        quality_policy_version="quality-v1",
        algorithm_version="returns-v1",
    )


def _return_artifact_ids(
    cache: InMemoryArtifactCache, inputs: ScopedMarketInputs, *, end: str = "2026-01-01"
) -> tuple[str, str]:
    left, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs, "XETRA:AAA:IE0000000001", end=end),
        payload={"returns": [0.01, 0.02]},
    )
    right, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs, "XETRA:BBB:IE0000000002", end=end),
        payload={"returns": [0.03, 0.04]},
    )
    return left.artifact_id, right.artifact_id


def _portfolio_key(
    dependency_ids: tuple[str, ...],
    *,
    selection_hash: str = "selection-members-v1",
    risk_model: str = "sample-covariance",
    constraints_hash: str = "long-only",
    algorithm_version: str = "portfolio-v1",
) -> PortfolioArtifactKey:
    return PortfolioArtifactKey(
        listing_input_artifact_ids=dependency_ids,
        selection_definition_hash="definition-hash",
        selection_membership_hash=selection_hash,
        return_matrix_hash="return-matrix-hash",
        risk_model={"name": risk_model, "lookback_days": 756},
        constraints={"hash": constraints_hash, "long_only": True},
        optimizer_settings={"objective": "minimum_variance", "grid_size": 101},
        costs={"broker": "flatex", "fee_bps": 10},
        walk_forward_windows={"train_days": 756, "test_days": 63},
        stress_settings={"scenarios": ["covid", "rate-shock"]},
        recommendation_template="default-v1",
        algorithm_versions={"portfolio": algorithm_version, "risk_model": "risk-v1"},
    )


def test_identical_authorized_portfolio_inputs_reuse_physical_artifact_across_users() -> None:
    cache = InMemoryArtifactCache()
    runs = InMemoryAnalysisRunStore()
    first_inputs = _inputs("user-a")
    second_inputs = _inputs("user-b")
    first_dependencies = _return_artifact_ids(cache, first_inputs)
    second_dependencies = _return_artifact_ids(cache, second_inputs)
    runs.create_project(
        user_id="user-a", project_id="project-a", current_snapshot_id="snapshot-user-a"
    )
    runs.create_project(
        user_id="user-b", project_id="project-b", current_snapshot_id="snapshot-user-b"
    )

    first, first_run = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=first_inputs,
        project_id="project-a",
        key=_portfolio_key(first_dependencies),
        payload={"candidates": 4},
    )
    second, second_run = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=second_inputs,
        project_id="project-b",
        key=_portfolio_key(tuple(reversed(second_dependencies))),
        payload={"candidates": 4},
    )

    assert first.artifact_id == second.artifact_id
    assert first_run.run_id != second_run.run_id
    assert first_run.user_id == "user-a"
    assert second_run.user_id == "user-b"
    assert first.dependency_ids == tuple(sorted(first_dependencies))


def test_portfolio_artifact_key_excludes_user_and_project_identity() -> None:
    dependencies = ("returns-b", "returns-a")

    assert (
        _portfolio_key(dependencies).artifact_id()
        == _portfolio_key(tuple(reversed(dependencies))).artifact_id()
    )
    assert "user_id" not in _portfolio_key(dependencies).as_payload()
    assert "project_id" not in _portfolio_key(dependencies).as_payload()


def test_portfolio_input_or_setting_changes_create_distinct_artifacts() -> None:
    cache = InMemoryArtifactCache()
    runs = InMemoryAnalysisRunStore()
    inputs = _inputs()
    dependencies = _return_artifact_ids(cache, inputs)
    changed_date_dependencies = _return_artifact_ids(cache, inputs, end="2026-01-02")
    runs.create_project(
        user_id="user-a", project_id="project-a", current_snapshot_id="snapshot-user-a"
    )

    base, _ = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=_portfolio_key(dependencies),
        payload={"candidates": 4},
    )
    changed_inputs, _ = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=_portfolio_key(changed_date_dependencies),
        payload={"candidates": 4},
    )
    changed_constraints, _ = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=_portfolio_key(dependencies, constraints_hash="target-volatility"),
        payload={"candidates": 4},
    )
    changed_model, _ = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=_portfolio_key(dependencies, risk_model="shrinkage"),
        payload={"candidates": 4},
    )
    changed_algorithm, _ = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=_portfolio_key(dependencies, algorithm_version="portfolio-v2"),
        payload={"candidates": 4},
    )

    artifact_ids = {
        base.artifact_id,
        changed_inputs.artifact_id,
        changed_constraints.artifact_id,
        changed_model.artifact_id,
        changed_algorithm.artifact_id,
    }
    assert len(artifact_ids) == 5


def test_portfolio_creation_requires_dependency_closure_access() -> None:
    cache = InMemoryArtifactCache()
    runs = InMemoryAnalysisRunStore()
    first_inputs = _inputs("user-a")
    second_inputs = _inputs("user-b", snapshot_hash="quote-hash-user-b")
    left_id, _ = _return_artifact_ids(cache, first_inputs)
    _, right_id = _return_artifact_ids(cache, second_inputs)
    runs.create_project(
        user_id="user-a", project_id="project-a", current_snapshot_id="snapshot-user-a"
    )

    with pytest.raises(ArtifactCacheError, match="not visible"):
        create_portfolio_artifact(
            cache=cache,
            run_store=runs,
            inputs=first_inputs,
            project_id="project-a",
            key=_portfolio_key((left_id, right_id)),
            payload={"candidates": 4},
        )


def test_portfolio_access_requires_user_project_run_and_current_snapshot() -> None:
    cache = InMemoryArtifactCache()
    runs = InMemoryAnalysisRunStore()
    inputs = _inputs("user-a")
    dependencies = _return_artifact_ids(cache, inputs)
    runs.create_project(
        user_id="user-a", project_id="project-a", current_snapshot_id="snapshot-user-a"
    )
    runs.create_project(
        user_id="user-b", project_id="project-b", current_snapshot_id="snapshot-user-b"
    )
    artifact, run_ref = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=_portfolio_key(dependencies),
        payload={"candidates": 4},
    )

    with pytest.raises(ArtifactCacheError, match="not visible"):
        cache.require_ref(
            user_id="user-a", snapshot_id="snapshot-user-a", artifact_id=artifact.artifact_id
        )
    with pytest.raises(ArtifactCacheError, match="not visible"):
        runs.require_run(user_id="user-b", project_id="project-b", run_id=run_ref.run_id)

    resolved = runs.require_run(user_id="user-a", project_id="project-a", run_id=run_ref.run_id)
    assert resolved.artifact_id == artifact.artifact_id

    runs.set_current_snapshot(
        user_id="user-a", project_id="project-a", snapshot_id="snapshot-user-a-v2"
    )
    with pytest.raises(ArtifactCacheError, match="stale project snapshot"):
        runs.require_run(user_id="user-a", project_id="project-a", run_id=run_ref.run_id)


def test_repeated_identical_portfolio_analysis_reuses_run_and_artifact() -> None:
    cache = InMemoryArtifactCache()
    runs = InMemoryAnalysisRunStore()
    inputs = _inputs()
    dependencies = _return_artifact_ids(cache, inputs)
    key = _portfolio_key(dependencies)
    runs.create_project(
        user_id="user-a", project_id="project-a", current_snapshot_id="snapshot-user-a"
    )

    first_artifact, first_run = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=key,
        payload={"candidates": 4},
    )
    second_artifact, second_run = create_portfolio_artifact(
        cache=cache,
        run_store=runs,
        inputs=inputs,
        project_id="project-a",
        key=key,
        payload={"candidates": 4},
    )

    assert first_artifact.artifact_id == second_artifact.artifact_id
    assert first_run.run_id == second_run.run_id
