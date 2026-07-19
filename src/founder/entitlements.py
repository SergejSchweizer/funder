"""User data entitlements and immutable snapshot contracts for hosted mode."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Literal


class EntitlementError(RuntimeError):
    """Raised when hosted entitlement publication fails closed."""


RunStatus = Literal["planned", "running", "succeeded", "failed", "partial"]


@dataclass(frozen=True)
class ProviderDownloadRun:
    """Provider-backed download provenance required before granting data."""

    download_run_id: str
    user_id: str
    credential_id: str
    provider: str
    status: RunStatus
    returned_observation_ids: tuple[str, ...]
    request_hash: str


@dataclass(frozen=True)
class UserGrant:
    """User entitlement to one shared market observation."""

    grant_id: str
    user_id: str
    download_run_id: str
    market_object_id: str
    revision_policy: str


@dataclass(frozen=True)
class UserDataSnapshot:
    """Immutable user-visible observation set."""

    snapshot_id: str
    user_id: str
    snapshot_hash: str
    observation_ids: tuple[str, ...]
    parent_snapshot_id: str | None = None


@dataclass
class InMemoryEntitlementStore:
    """In-memory entitlement repository for tests and local hosted adapters."""

    grants_by_user: dict[str, dict[str, UserGrant]] = field(
        default_factory=lambda: dict[str, dict[str, UserGrant]]()
    )
    snapshots_by_user_hash: dict[tuple[str, str], UserDataSnapshot] = field(
        default_factory=lambda: dict[tuple[str, str], UserDataSnapshot]()
    )
    current_snapshot_by_user: dict[str, UserDataSnapshot] = field(
        default_factory=lambda: dict[str, UserDataSnapshot]()
    )
    deleted_users: set[str] = field(default_factory=lambda: set[str]())

    def visible_observation_ids(self, user_id: str) -> tuple[str, ...]:
        """Return currently granted observations for one user."""

        if user_id in self.deleted_users:
            return ()
        grants = self.grants_by_user.get(user_id, {})
        return tuple(sorted(grants))


def publish_user_data_snapshot(
    *,
    store: InMemoryEntitlementStore,
    run: ProviderDownloadRun,
    revision_policy: str = "latest-returned",
) -> UserDataSnapshot:
    """Publish grants and an immutable snapshot from a successful provider response."""

    if run.status != "succeeded":
        raise EntitlementError("only succeeded provider runs can create grants")
    if not run.returned_observation_ids:
        raise EntitlementError("provider run returned no observations")
    if run.user_id in store.deleted_users:
        raise EntitlementError("deleted user cannot receive grants")

    user_grants = store.grants_by_user.setdefault(run.user_id, {})
    for observation_id in sorted(set(run.returned_observation_ids)):
        user_grants.setdefault(
            observation_id,
            UserGrant(
                grant_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run.user_id}:{observation_id}")),
                user_id=run.user_id,
                download_run_id=run.download_run_id,
                market_object_id=observation_id,
                revision_policy=revision_policy,
            ),
        )

    observation_ids = tuple(sorted(user_grants))
    parent = store.current_snapshot_by_user.get(run.user_id)
    snapshot_hash = _snapshot_hash(
        user_id=run.user_id,
        observation_ids=observation_ids,
        revision_policy=revision_policy,
    )
    key = (run.user_id, snapshot_hash)
    snapshot = store.snapshots_by_user_hash.get(key)
    if snapshot is None:
        snapshot = UserDataSnapshot(
            snapshot_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run.user_id}:{snapshot_hash}")),
            user_id=run.user_id,
            snapshot_hash=snapshot_hash,
            observation_ids=observation_ids,
            parent_snapshot_id=None if parent is None else parent.snapshot_id,
        )
        store.snapshots_by_user_hash[key] = snapshot
    store.current_snapshot_by_user[run.user_id] = snapshot
    return snapshot


def resolve_user_snapshot(
    *,
    store: InMemoryEntitlementStore,
    user_id: str,
    snapshot_id: str | None = None,
) -> UserDataSnapshot:
    """Resolve a user-owned immutable snapshot."""

    if user_id in store.deleted_users:
        raise EntitlementError("user is deleted")
    if snapshot_id is None:
        snapshot = store.current_snapshot_by_user.get(user_id)
        if snapshot is None:
            raise EntitlementError("user has no data snapshot")
        return snapshot
    for candidate_user_id, _ in store.snapshots_by_user_hash:
        snapshot = store.snapshots_by_user_hash[(candidate_user_id, _)]
        if snapshot.snapshot_id == snapshot_id:
            if snapshot.user_id != user_id:
                raise EntitlementError("snapshot is not owned by user")
            return snapshot
    raise EntitlementError("snapshot not found")


def delete_user_entitlements(*, store: InMemoryEntitlementStore, user_id: str) -> None:
    """Delete user grants/snapshot pointers without deleting shared objects."""

    store.deleted_users.add(user_id)
    store.grants_by_user.pop(user_id, None)
    store.current_snapshot_by_user.pop(user_id, None)


def _snapshot_hash(
    *,
    user_id: str,
    observation_ids: tuple[str, ...],
    revision_policy: str,
) -> str:
    payload = {
        "user_id": user_id,
        "observation_ids": list(observation_ids),
        "revision_policy": revision_policy,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
