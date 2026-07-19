"""Shared content-addressed market observation store for hosted mode."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from founder.table_io import JsonRow, read_json, read_rows, write_json, write_rows


class SharedObservationStoreError(RuntimeError):
    """Raised when shared market observation storage fails closed."""


@dataclass(frozen=True)
class MarketObservation:
    """Normalized provider observation before shared publication."""

    provider: str
    dataset_type: str
    listing_identity: str
    business_key: str
    payload: JsonRow
    schema_version: int = 1

    def normalized_payload(self) -> JsonRow:
        """Return deterministic payload without hosted authorization metadata."""

        forbidden = {"user_id", "credential_id", "session_token", "credential_fingerprint"}
        leaked = sorted(forbidden.intersection(self.payload))
        if leaked:
            raise SharedObservationStoreError(f"forbidden payload fields: {', '.join(leaked)}")
        return {key: self.payload[key] for key in sorted(self.payload)}

    def payload_hash(self) -> str:
        """Return stable hash of the normalized payload."""

        return _stable_hash(self.normalized_payload())

    def observation_id(self) -> str:
        """Return stable content-addressed observation id."""

        return _stable_hash(
            {
                "provider": self.provider,
                "dataset_type": self.dataset_type,
                "listing_identity": self.listing_identity,
                "business_key": self.business_key,
                "payload_hash": self.payload_hash(),
                "schema_version": self.schema_version,
            }
        )

    def row(self) -> JsonRow:
        """Return persisted shared observation row."""

        return {
            "market_object_id": self.observation_id(),
            "provider": self.provider,
            "dataset_type": self.dataset_type,
            "listing_identity": self.listing_identity,
            "business_key": self.business_key,
            "payload_hash": self.payload_hash(),
            "schema_version": self.schema_version,
            **self.normalized_payload(),
        }


@dataclass(frozen=True)
class SharedObservationManifest:
    """Manifest for one immutable shared observation segment."""

    segment_id: str
    provider: str
    dataset_type: str
    segment_hash: str
    row_count: int
    storage_uri: str
    observation_ids: tuple[str, ...]

    def as_dict(self) -> JsonRow:
        """Return JSON-serializable manifest payload."""

        return {
            "segment_id": self.segment_id,
            "provider": self.provider,
            "dataset_type": self.dataset_type,
            "segment_hash": self.segment_hash,
            "row_count": self.row_count,
            "storage_uri": self.storage_uri,
            "observation_ids": list(self.observation_ids),
        }


class SharedObservationCatalog:
    """In-memory catalog of shared observation manifests for tests/local adapters."""

    def __init__(self) -> None:
        self._manifests_by_hash: dict[str, SharedObservationManifest] = {}
        self._objects_by_id: dict[str, JsonRow] = {}

    def publish(self, manifest: SharedObservationManifest, rows: list[JsonRow]) -> None:
        """Publish a manifest and its rows idempotently."""

        existing = self._manifests_by_hash.get(manifest.segment_hash)
        if existing is not None:
            return
        self._manifests_by_hash[manifest.segment_hash] = manifest
        for row in rows:
            self._objects_by_id[str(row["market_object_id"])] = row

    def manifest_for_hash(self, segment_hash: str) -> SharedObservationManifest | None:
        """Return an already published manifest for a segment hash."""

        return self._manifests_by_hash.get(segment_hash)

    def object_count(self) -> int:
        """Return unique shared observation count."""

        return len(self._objects_by_id)


class SharedMarketObservationStore:
    """Append-only content-addressed shared market observation store."""

    def __init__(self, *, root: Path, catalog: SharedObservationCatalog) -> None:
        self._root = root
        self._catalog = catalog

    def publish_segment(
        self,
        *,
        provider: str,
        dataset_type: str,
        observations: list[MarketObservation],
    ) -> SharedObservationManifest:
        """Normalize, deduplicate, and atomically publish one immutable segment."""

        if not observations:
            raise SharedObservationStoreError("observations are required")
        rows_by_id = {
            observation.observation_id(): observation.row() for observation in observations
        }
        rows = [rows_by_id[key] for key in sorted(rows_by_id)]
        segment_hash = _stable_hash({"rows": rows})
        existing = self._catalog.manifest_for_hash(segment_hash)
        if existing is not None:
            return existing
        segment_id = _stable_hash(
            {
                "provider": provider,
                "dataset_type": dataset_type,
                "segment_hash": segment_hash,
            }
        )
        segment_path = self._segment_path(provider, dataset_type, segment_id)
        _atomic_write_rows(segment_path, rows)
        manifest = SharedObservationManifest(
            segment_id=segment_id,
            provider=provider,
            dataset_type=dataset_type,
            segment_hash=segment_hash,
            row_count=len(rows),
            storage_uri=str(segment_path),
            observation_ids=tuple(str(row["market_object_id"]) for row in rows),
        )
        write_json(self._manifest_path(provider, dataset_type, segment_id), manifest.as_dict())
        self._catalog.publish(manifest, rows)
        return manifest

    def read_segment(self, manifest: SharedObservationManifest) -> list[JsonRow]:
        """Read a previously published segment and verify its content hash."""

        try:
            rows = read_rows(Path(manifest.storage_uri))
        except Exception as error:
            raise SharedObservationStoreError("shared segment cannot be read") from error
        if _stable_hash({"rows": rows}) != manifest.segment_hash:
            raise SharedObservationStoreError("shared segment hash mismatch")
        return rows

    def read_manifest(
        self,
        *,
        provider: str,
        dataset_type: str,
        segment_id: str,
    ) -> SharedObservationManifest:
        """Read a manifest from disk."""

        payload = read_json(self._manifest_path(provider, dataset_type, segment_id))
        return SharedObservationManifest(
            segment_id=str(payload["segment_id"]),
            provider=str(payload["provider"]),
            dataset_type=str(payload["dataset_type"]),
            segment_hash=str(payload["segment_hash"]),
            row_count=int(payload["row_count"]),
            storage_uri=str(payload["storage_uri"]),
            observation_ids=tuple(str(value) for value in payload["observation_ids"]),
        )

    def _segment_path(self, provider: str, dataset_type: str, segment_id: str) -> Path:
        return (
            self._root
            / "shared"
            / "market_observations"
            / f"provider={provider}"
            / f"dataset_type={dataset_type}"
            / f"{segment_id}.parquet"
        )

    def _manifest_path(self, provider: str, dataset_type: str, segment_id: str) -> Path:
        return (
            self._root
            / "shared"
            / "market_observations"
            / f"provider={provider}"
            / f"dataset_type={dataset_type}"
            / f"{segment_id}.json"
        )


def _stable_hash(payload: JsonRow) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _atomic_write_rows(path: Path, rows: list[JsonRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp{path.suffix}")
    try:
        write_rows(tmp_path, rows)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
