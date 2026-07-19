from __future__ import annotations

import pytest

from founder.artifact_cache import (
    ArtifactCacheError,
    InMemoryArtifactCache,
    ReturnArtifactKey,
    UnivariateArtifactKey,
    create_return_artifact,
    create_univariate_artifact,
)
from founder.scoped_inputs import ScopedMarketInputs, SelectionInputRef, UserDataSnapshotRef


def _inputs(user_id: str = "user-a", snapshot_hash: str = "quote-hash") -> ScopedMarketInputs:
    snapshot = UserDataSnapshotRef(
        user_id=user_id,
        snapshot_id=f"snapshot-{user_id}",
        snapshot_hash=snapshot_hash,
    )
    selection = SelectionInputRef("selection-1", "selection-hash", ("obs-1",))
    return ScopedMarketInputs(
        snapshot=snapshot,
        selection=selection,
        quote_rows=({"market_object_id": "obs-1", "close": 100},),
        input_hash=snapshot_hash,
    )


def _return_key(inputs: ScopedMarketInputs, *, end: str = "2026-01-01") -> ReturnArtifactKey:
    return ReturnArtifactKey(
        listing_id="XETRA:ABC:IE0000000001",
        quote_snapshot_hash=inputs.input_hash,
        dividend_snapshot_hash="dividend-hash",
        date_window=("2025-01-01", end),
        return_parameters={"return_type": "log"},
        quality_policy_version="quality-v1",
        algorithm_version="returns-v1",
    )


def test_identical_authorized_inputs_reuse_physical_artifact_across_users() -> None:
    cache = InMemoryArtifactCache()
    first_inputs = _inputs("user-a")
    second_inputs = _inputs("user-b")

    first, first_ref = create_return_artifact(
        cache=cache,
        inputs=first_inputs,
        key=_return_key(first_inputs),
        payload={"rows": 1},
    )
    second, second_ref = create_return_artifact(
        cache=cache,
        inputs=second_inputs,
        key=_return_key(second_inputs),
        payload={"rows": 1},
    )

    assert first.artifact_id == second.artifact_id
    assert first_ref.user_id == "user-a"
    assert second_ref.user_id == "user-b"
    assert len(cache.artifacts_by_id) == 1


def test_material_input_changes_create_distinct_artifacts() -> None:
    cache = InMemoryArtifactCache()
    inputs = _inputs()
    first, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs, end="2026-01-01"),
        payload={"rows": 1},
    )
    changed_date, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs, end="2026-01-02"),
        payload={"rows": 2},
    )
    changed_dividend_key = _return_key(inputs)
    changed_dividend_key = ReturnArtifactKey(
        **{**changed_dividend_key.__dict__, "dividend_snapshot_hash": "changed-dividend"}
    )
    changed_dividend, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=changed_dividend_key,
        payload={"rows": 1},
    )

    assert len({first.artifact_id, changed_date.artifact_id, changed_dividend.artifact_id}) == 3


def test_univariate_artifact_depends_on_return_artifact_and_parameters() -> None:
    cache = InMemoryArtifactCache()
    inputs = _inputs()
    returns, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs),
        payload={"returns": [0.01]},
    )
    first, _ = create_univariate_artifact(
        cache=cache,
        inputs=inputs,
        return_artifact=returns,
        key=UnivariateArtifactKey(
            return_artifact_id=returns.artifact_id,
            metric_parameters={"window": 252},
            confidence_level=0.95,
            quality_policy_version="quality-v1",
            algorithm_version="univariate-v1",
        ),
        payload={"sharpe": 1.0},
    )
    changed, _ = create_univariate_artifact(
        cache=cache,
        inputs=inputs,
        return_artifact=returns,
        key=UnivariateArtifactKey(
            return_artifact_id=returns.artifact_id,
            metric_parameters={"window": 252},
            confidence_level=0.99,
            quality_policy_version="quality-v1",
            algorithm_version="univariate-v1",
        ),
        payload={"sharpe": 1.0},
    )

    assert first.artifact_id != changed.artifact_id


def test_direct_artifact_id_access_without_user_ref_is_rejected() -> None:
    cache = InMemoryArtifactCache()
    inputs = _inputs("user-a")
    artifact, _ = create_return_artifact(
        cache=cache,
        inputs=inputs,
        key=_return_key(inputs),
        payload={"rows": 1},
    )

    with pytest.raises(ArtifactCacheError, match="not visible"):
        cache.require_ref(
            user_id="user-b",
            snapshot_id="snapshot-user-b",
            artifact_id=artifact.artifact_id,
        )
    with pytest.raises(ArtifactCacheError, match="authorized inputs"):
        create_return_artifact(
            cache=cache,
            inputs=inputs,
            key=ReturnArtifactKey(
                **{**_return_key(inputs).__dict__, "quote_snapshot_hash": "wrong"}
            ),
            payload={"rows": 1},
        )
