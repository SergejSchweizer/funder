from __future__ import annotations

import pytest

from founder.entitlements import (
    InMemoryEntitlementStore,
    ProviderDownloadRun,
    publish_user_data_snapshot,
)
from founder.scoped_inputs import (
    EntitledSnapshotReader,
    LocalLakeSnapshotReader,
    ScopedInputError,
    UserDataSnapshotRef,
    build_selection_ref,
)


def _run(user_id: str, observations: tuple[str, ...]) -> ProviderDownloadRun:
    return ProviderDownloadRun(
        download_run_id=f"run-{user_id}",
        user_id=user_id,
        credential_id=f"credential-{user_id}",
        provider="eodhd",
        status="succeeded",
        returned_observation_ids=observations,
        request_hash=f"request-{user_id}",
    )


def _snapshot_ref(user_id: str, snapshot_id: str, snapshot_hash: str) -> UserDataSnapshotRef:
    return UserDataSnapshotRef(
        user_id=user_id,
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
    )


def test_entitled_reader_rejects_cross_user_and_global_extra_rows() -> None:
    store = InMemoryEntitlementStore()
    user_a = publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-1",)))
    user_b = publish_user_data_snapshot(store=store, run=_run("user-b", ("obs-1", "obs-2")))
    rows = {
        "obs-1": {"market_object_id": "obs-1", "close": 100},
        "obs-2": {"market_object_id": "obs-2", "close": 999},
        "global-extra": {"market_object_id": "global-extra", "close": 1},
    }
    reader = EntitledSnapshotReader(entitlement_store=store, rows_by_observation_id=rows)

    scoped = reader.read_inputs(
        snapshot=_snapshot_ref("user-a", user_a.snapshot_id, user_a.snapshot_hash),
        selection=build_selection_ref(selection_id="sel-a", member_ids=("obs-1",)),
    )

    assert [row["market_object_id"] for row in scoped.quote_rows] == ["obs-1"]
    with pytest.raises(ScopedInputError, match="outside snapshot"):
        reader.read_inputs(
            snapshot=_snapshot_ref("user-a", user_a.snapshot_id, user_a.snapshot_hash),
            selection=build_selection_ref(selection_id="sel-leak", member_ids=("obs-2",)),
        )
    with pytest.raises(Exception, match="not owned|outside snapshot"):
        reader.read_inputs(
            snapshot=_snapshot_ref("user-a", user_b.snapshot_id, user_b.snapshot_hash),
            selection=build_selection_ref(selection_id="sel-b", member_ids=("obs-2",)),
        )


def test_scoped_input_hashes_are_deterministic_and_selection_specific() -> None:
    store = InMemoryEntitlementStore()
    snapshot = publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-1", "obs-2")))
    rows = {
        "obs-1": {"market_object_id": "obs-1", "close": 100},
        "obs-2": {"market_object_id": "obs-2", "close": 101},
    }
    reader = EntitledSnapshotReader(entitlement_store=store, rows_by_observation_id=rows)
    snapshot_ref = _snapshot_ref("user-a", snapshot.snapshot_id, snapshot.snapshot_hash)
    selection = build_selection_ref(selection_id="sel", member_ids=("obs-2", "obs-1"))

    first = reader.read_inputs(snapshot=snapshot_ref, selection=selection)
    second = reader.read_inputs(snapshot=snapshot_ref, selection=selection)

    assert first == second
    assert first.input_hash == second.input_hash


def test_local_reader_preserves_explicit_local_adapter_behavior() -> None:
    reader = LocalLakeSnapshotReader(
        rows_by_observation_id={"obs-1": {"market_object_id": "obs-1", "close": 100}}
    )
    snapshot = UserDataSnapshotRef(
        user_id="local",
        snapshot_id="local-snapshot",
        snapshot_hash="local-hash",
    )

    scoped = reader.read_inputs(
        snapshot=snapshot,
        selection=build_selection_ref(selection_id="local", member_ids=("obs-1",)),
    )

    assert scoped.quote_rows == ({"market_object_id": "obs-1", "close": 100},)
