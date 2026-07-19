from __future__ import annotations

import pytest

from founder.entitlements import (
    EntitlementError,
    InMemoryEntitlementStore,
    ProviderDownloadRun,
    delete_user_entitlements,
    publish_user_data_snapshot,
    resolve_user_snapshot,
)


def _run(
    user_id: str,
    observations: tuple[str, ...],
    status: str = "succeeded",
) -> ProviderDownloadRun:
    return ProviderDownloadRun(
        download_run_id=f"run-{user_id}-{len(observations)}",
        user_id=user_id,
        credential_id=f"credential-{user_id}",
        provider="eodhd",
        status=status,  # type: ignore[arg-type]
        returned_observation_ids=observations,
        request_hash=f"request-{user_id}-{len(observations)}",
    )


def test_new_user_sees_no_shared_objects_until_own_successful_run() -> None:
    store = InMemoryEntitlementStore()

    assert store.visible_observation_ids("user-a") == ()
    with pytest.raises(EntitlementError, match="no data snapshot"):
        resolve_user_snapshot(store=store, user_id="user-a")

    snapshot = publish_user_data_snapshot(
        store=store,
        run=_run("user-a", ("obs-1", "obs-2")),
    )

    assert snapshot.observation_ids == ("obs-1", "obs-2")
    assert store.visible_observation_ids("user-a") == ("obs-1", "obs-2")


def test_other_users_refreshes_do_not_expand_visibility() -> None:
    store = InMemoryEntitlementStore()
    publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-1",)))
    publish_user_data_snapshot(store=store, run=_run("user-b", ("obs-1", "obs-2")))

    assert store.visible_observation_ids("user-a") == ("obs-1",)
    assert store.visible_observation_ids("user-b") == ("obs-1", "obs-2")

    newer = publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-2",)))
    assert newer.observation_ids == ("obs-1", "obs-2")


def test_failed_partial_or_empty_runs_cannot_grant_data() -> None:
    store = InMemoryEntitlementStore()

    for status in ("failed", "partial", "planned", "running"):
        with pytest.raises(EntitlementError, match="succeeded"):
            publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-1",), status))
    with pytest.raises(EntitlementError, match="no observations"):
        publish_user_data_snapshot(store=store, run=_run("user-a", ()))
    assert store.visible_observation_ids("user-a") == ()


def test_snapshots_are_immutable_owned_and_idempotent() -> None:
    store = InMemoryEntitlementStore()
    first = publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-2", "obs-1")))
    repeated = publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-1", "obs-2")))
    second = publish_user_data_snapshot(store=store, run=_run("user-a", ("obs-3",)))

    assert first == repeated
    assert first.observation_ids == ("obs-1", "obs-2")
    assert second.parent_snapshot_id == first.snapshot_id
    assert (
        resolve_user_snapshot(store=store, user_id="user-a", snapshot_id=first.snapshot_id) == first
    )
    with pytest.raises(EntitlementError, match="not owned"):
        resolve_user_snapshot(store=store, user_id="user-b", snapshot_id=first.snapshot_id)


def test_account_deletion_removes_user_grants_not_shared_identity_strings() -> None:
    store = InMemoryEntitlementStore()
    publish_user_data_snapshot(store=store, run=_run("user-a", ("shared-obs",)))
    publish_user_data_snapshot(store=store, run=_run("user-b", ("shared-obs",)))

    delete_user_entitlements(store=store, user_id="user-a")

    assert store.visible_observation_ids("user-a") == ()
    assert store.visible_observation_ids("user-b") == ("shared-obs",)
    with pytest.raises(EntitlementError, match="deleted"):
        publish_user_data_snapshot(store=store, run=_run("user-a", ("new-obs",)))
