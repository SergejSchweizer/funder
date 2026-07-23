"""Scoped market input contracts for hosted analytical workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from camovar.entitlements import InMemoryEntitlementStore, resolve_user_snapshot
from camovar.table_io import JsonRow, read_rows


class ScopedInputError(RuntimeError):
    """Raised when scoped market input resolution fails closed."""


@dataclass(frozen=True)
class UserDataSnapshotRef:
    """Reference to an immutable user-owned data snapshot."""

    user_id: str
    snapshot_id: str
    snapshot_hash: str


@dataclass(frozen=True)
class SelectionInputRef:
    """Reference to a persisted selection over a scoped snapshot."""

    selection_id: str
    selection_hash: str
    member_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScopedMarketInputs:
    """Resolved authorized input boundary for hosted analytics."""

    snapshot: UserDataSnapshotRef
    selection: SelectionInputRef
    quote_rows: tuple[JsonRow, ...]
    input_hash: str


class SnapshotReader(Protocol):
    """Port for resolving immutable scoped market inputs."""

    def read_inputs(
        self,
        *,
        snapshot: UserDataSnapshotRef,
        selection: SelectionInputRef,
    ) -> ScopedMarketInputs:
        """Read already authorized inputs for one snapshot and selection."""
        ...


class LocalLakeSnapshotReader:
    """Local CLI compatibility reader over explicit files."""

    def __init__(self, *, rows_by_observation_id: dict[str, JsonRow]) -> None:
        self._rows_by_observation_id = rows_by_observation_id

    @classmethod
    def from_parquet_files(cls, paths: tuple[Path, ...]) -> LocalLakeSnapshotReader:
        """Create a local reader from explicit Parquet files."""

        rows: dict[str, JsonRow] = {}
        for path in paths:
            for row in read_rows(path):
                observation_id = str(row.get("market_object_id", row.get("observation_id", "")))
                if not observation_id:
                    raise ScopedInputError(f"row in {path} has no observation id")
                rows[observation_id] = row
        return cls(rows_by_observation_id=rows)

    def read_inputs(
        self,
        *,
        snapshot: UserDataSnapshotRef,
        selection: SelectionInputRef,
    ) -> ScopedMarketInputs:
        """Read local rows by explicit selection membership."""

        rows = tuple(self._rows_by_observation_id[member] for member in selection.member_ids)
        return _scoped_inputs(snapshot=snapshot, selection=selection, quote_rows=rows)


class EntitledSnapshotReader:
    """Hosted reader that resolves rows only through user-owned snapshot membership."""

    def __init__(
        self,
        *,
        entitlement_store: InMemoryEntitlementStore,
        rows_by_observation_id: dict[str, JsonRow],
    ) -> None:
        self._entitlement_store = entitlement_store
        self._rows_by_observation_id = rows_by_observation_id

    def read_inputs(
        self,
        *,
        snapshot: UserDataSnapshotRef,
        selection: SelectionInputRef,
    ) -> ScopedMarketInputs:
        """Resolve hosted rows only when snapshot ownership and membership match."""

        resolved = resolve_user_snapshot(
            store=self._entitlement_store,
            user_id=snapshot.user_id,
            snapshot_id=snapshot.snapshot_id,
        )
        if resolved.snapshot_hash != snapshot.snapshot_hash:
            raise ScopedInputError("snapshot hash mismatch")
        allowed = set(resolved.observation_ids)
        requested = set(selection.member_ids)
        if not requested.issubset(allowed):
            raise ScopedInputError("selection requests observations outside snapshot")
        rows = tuple(self._rows_by_observation_id[member] for member in selection.member_ids)
        return _scoped_inputs(snapshot=snapshot, selection=selection, quote_rows=rows)


def build_selection_ref(*, selection_id: str, member_ids: tuple[str, ...]) -> SelectionInputRef:
    """Build deterministic selection input reference."""

    normalized = tuple(sorted(set(member_ids)))
    selection_hash = _stable_hash({"selection_id": selection_id, "member_ids": list(normalized)})
    return SelectionInputRef(
        selection_id=selection_id,
        selection_hash=selection_hash,
        member_ids=normalized,
    )


def _scoped_inputs(
    *,
    snapshot: UserDataSnapshotRef,
    selection: SelectionInputRef,
    quote_rows: tuple[JsonRow, ...],
) -> ScopedMarketInputs:
    input_hash = _stable_hash(
        {
            "snapshot_hash": snapshot.snapshot_hash,
            "selection_hash": selection.selection_hash,
            "row_ids": [
                str(row.get("market_object_id", row.get("observation_id"))) for row in quote_rows
            ],
        }
    )
    return ScopedMarketInputs(
        snapshot=snapshot,
        selection=selection,
        quote_rows=quote_rows,
        input_hash=input_hash,
    )


def _stable_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
