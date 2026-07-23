from __future__ import annotations

import pytest

from camovar.artifact_cache import (
    ArtifactCacheError,
    BivariateArtifactKey,
    InMemoryArtifactCache,
    ReturnArtifactKey,
    bivariate_bucket_for_artifact_id,
    build_bivariate_alignment_hash,
    create_bivariate_artifact,
    create_return_artifact,
    validate_bivariate_bucket_rows,
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


def _return_key(inputs: ScopedMarketInputs, listing_id: str) -> ReturnArtifactKey:
    return ReturnArtifactKey(
        listing_id=listing_id,
        quote_snapshot_hash=inputs.input_hash,
        dividend_snapshot_hash="dividend-hash",
        date_window=("2025-01-01", "2026-01-01"),
        return_parameters={"return_type": "log"},
        quality_policy_version="quality-v1",
        algorithm_version="returns-v1",
    )


def _return_artifacts(cache: InMemoryArtifactCache, inputs: ScopedMarketInputs) -> tuple[str, str]:
    left, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs, "XETRA:AAA:IE0000000001"),
        payload={"returns": [0.01, 0.02]},
    )
    right, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs, "XETRA:BBB:IE0000000002"),
        payload={"returns": [0.03, 0.04]},
    )
    return left.artifact_id, right.artifact_id


def _bivariate_key(
    left_id: str, right_id: str, *, alignment_hash: str = "alignment-hash"
) -> BivariateArtifactKey:
    return BivariateArtifactKey(
        left_return_artifact_id=left_id,
        right_return_artifact_id=right_id,
        alignment_hash=alignment_hash,
        metric_parameters={"metrics": ["pearson", "spearman"], "mode": "top-k"},
        minimum_observation_policy={"minimum_common_observations": 252},
        algorithm_version="bivariate-v1",
    )


def test_identical_authorized_pair_inputs_reuse_one_physical_artifact_across_users() -> None:
    cache = InMemoryArtifactCache()
    first_inputs = _inputs("user-a")
    second_inputs = _inputs("user-b")
    first_left_id, first_right_id = _return_artifacts(cache, first_inputs)
    second_left_id, second_right_id = _return_artifacts(cache, second_inputs)

    first, first_ref = create_bivariate_artifact(
        cache=cache,
        inputs=first_inputs,
        left_return_artifact=cache.require_ref(
            user_id="user-a", snapshot_id="snapshot-user-a", artifact_id=first_left_id
        ),
        right_return_artifact=cache.require_ref(
            user_id="user-a", snapshot_id="snapshot-user-a", artifact_id=first_right_id
        ),
        key=_bivariate_key(first_left_id, first_right_id),
        payload={"pearson": 0.5},
    )
    second, second_ref = create_bivariate_artifact(
        cache=cache,
        inputs=second_inputs,
        left_return_artifact=cache.require_ref(
            user_id="user-b", snapshot_id="snapshot-user-b", artifact_id=second_left_id
        ),
        right_return_artifact=cache.require_ref(
            user_id="user-b", snapshot_id="snapshot-user-b", artifact_id=second_right_id
        ),
        key=_bivariate_key(second_right_id, second_left_id),
        payload={"pearson": 0.5},
    )

    assert first.artifact_id == second.artifact_id
    assert first_ref.user_id == "user-a"
    assert second_ref.user_id == "user-b"
    assert first.dependency_ids == tuple(sorted((first_left_id, first_right_id)))


def test_reversed_pair_order_keeps_same_artifact_id() -> None:
    key = _bivariate_key("returns-b", "returns-a")

    assert key.artifact_id() == _bivariate_key("returns-a", "returns-b").artifact_id()
    assert key.ordered_return_artifact_ids() == ("returns-a", "returns-b")


def test_alignment_hash_changes_for_value_corrections_and_newly_common_dates() -> None:
    left = (
        {"date": "2026-01-01", "return": 0.01},
        {"date": "2026-01-02", "return": 0.02},
    )
    right = (
        {"date": "2026-01-01", "return": 0.03},
        {"date": "2026-01-02", "return": 0.04},
    )
    corrected_right = (
        {"date": "2026-01-01", "return": 0.03},
        {"date": "2026-01-02", "return": 0.05},
    )
    extended_right = (
        {"date": "2026-01-01", "return": 0.03},
        {"date": "2026-01-02", "return": 0.04},
        {"date": "2026-01-03", "return": 0.06},
    )
    extended_left = (*left, {"date": "2026-01-03", "return": 0.07})

    base_hash = build_bivariate_alignment_hash(left, right)

    assert build_bivariate_alignment_hash(left, corrected_right) != base_hash
    assert build_bivariate_alignment_hash(extended_left, extended_right) != base_hash


def test_alignment_hash_rejects_no_common_dates() -> None:
    with pytest.raises(ArtifactCacheError, match="no common dates"):
        build_bivariate_alignment_hash(
            ({"date": "2026-01-01", "return": 0.01},),
            ({"date": "2026-01-02", "return": 0.02},),
        )


def test_bivariate_artifact_requires_access_to_both_return_dependencies() -> None:
    cache = InMemoryArtifactCache()
    first_inputs = _inputs("user-a")
    second_inputs = _inputs("user-b", snapshot_hash="quote-hash-user-b")
    left_id, _ = _return_artifacts(cache, first_inputs)
    _, right_id = _return_artifacts(cache, second_inputs)

    with pytest.raises(ArtifactCacheError, match="not visible"):
        create_bivariate_artifact(
            cache=cache,
            inputs=first_inputs,
            left_return_artifact=cache.artifacts_by_id[left_id],
            right_return_artifact=cache.artifacts_by_id[right_id],
            key=_bivariate_key(left_id, right_id),
            payload={"pearson": 0.5},
        )


def test_same_input_pairs_and_dependency_mismatches_are_rejected() -> None:
    cache = InMemoryArtifactCache()
    inputs = _inputs()
    left_id, right_id = _return_artifacts(cache, inputs)

    with pytest.raises(ArtifactCacheError, match="same return artifact"):
        _bivariate_key(left_id, left_id)
    with pytest.raises(ArtifactCacheError, match="does not match"):
        create_bivariate_artifact(
            cache=cache,
            inputs=inputs,
            left_return_artifact=cache.artifacts_by_id[left_id],
            right_return_artifact=cache.artifacts_by_id[right_id],
            key=_bivariate_key(left_id, "returns-missing"),
            payload={"pearson": 0.5},
        )


def test_bucket_assignment_and_bucket_corruption_detection_are_deterministic() -> None:
    cache = InMemoryArtifactCache()
    inputs = _inputs()
    left_id, right_id = _return_artifacts(cache, inputs)
    artifact, _ = create_bivariate_artifact(
        cache=cache,
        inputs=inputs,
        left_return_artifact=cache.artifacts_by_id[left_id],
        right_return_artifact=cache.artifacts_by_id[right_id],
        key=_bivariate_key(left_id, right_id),
        payload={"pearson": 0.5},
    )

    first_bucket = bivariate_bucket_for_artifact_id(artifact.artifact_id, bucket_count=16)
    second_bucket = bivariate_bucket_for_artifact_id(artifact.artifact_id, bucket_count=16)

    assert first_bucket == second_bucket
    validate_bivariate_bucket_rows(artifact=artifact, rows=({"artifact_id": artifact.artifact_id},))
    with pytest.raises(ArtifactCacheError, match="missing expected artifact"):
        validate_bivariate_bucket_rows(artifact=artifact, rows=({"artifact_id": "wrong"},))
    with pytest.raises(ArtifactCacheError, match="positive"):
        bivariate_bucket_for_artifact_id(artifact.artifact_id, bucket_count=0)


def test_repeated_pair_requests_are_idempotent() -> None:
    cache = InMemoryArtifactCache()
    inputs = _inputs()
    left_id, right_id = _return_artifacts(cache, inputs)
    key = _bivariate_key(left_id, right_id)

    first, _ = create_bivariate_artifact(
        cache=cache,
        inputs=inputs,
        left_return_artifact=cache.artifacts_by_id[left_id],
        right_return_artifact=cache.artifacts_by_id[right_id],
        key=key,
        payload={"pearson": 0.5},
    )
    second, _ = create_bivariate_artifact(
        cache=cache,
        inputs=inputs,
        left_return_artifact=cache.artifacts_by_id[left_id],
        right_return_artifact=cache.artifacts_by_id[right_id],
        key=key,
        payload={"pearson": 0.5},
    )

    assert first.artifact_id == second.artifact_id
