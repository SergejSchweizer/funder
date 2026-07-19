"""Content-addressed hosted analytical artifact cache contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from founder.scoped_inputs import ScopedMarketInputs
from founder.table_io import JsonRow


class ArtifactCacheError(RuntimeError):
    """Raised when artifact cache access fails closed."""


ArtifactKind = Literal["returns", "univariate"]


@dataclass(frozen=True)
class ReturnArtifactKey:
    """Exact return artifact identity."""

    listing_id: str
    quote_snapshot_hash: str
    dividend_snapshot_hash: str
    date_window: tuple[str, str]
    return_parameters: JsonRow
    quality_policy_version: str
    algorithm_version: str

    def artifact_id(self) -> str:
        """Return deterministic return artifact id."""

        return _artifact_id("returns", self.as_payload())

    def as_payload(self) -> JsonRow:
        """Return canonical key payload."""

        return {
            "listing_id": self.listing_id,
            "quote_snapshot_hash": self.quote_snapshot_hash,
            "dividend_snapshot_hash": self.dividend_snapshot_hash,
            "date_window": list(self.date_window),
            "return_parameters": self.return_parameters,
            "quality_policy_version": self.quality_policy_version,
            "algorithm_version": self.algorithm_version,
        }


@dataclass(frozen=True)
class UnivariateArtifactKey:
    """Exact univariate artifact identity."""

    return_artifact_id: str
    metric_parameters: JsonRow
    confidence_level: float
    quality_policy_version: str
    algorithm_version: str

    def artifact_id(self) -> str:
        """Return deterministic univariate artifact id."""

        return _artifact_id("univariate", self.as_payload())

    def as_payload(self) -> JsonRow:
        """Return canonical key payload."""

        return {
            "return_artifact_id": self.return_artifact_id,
            "metric_parameters": self.metric_parameters,
            "confidence_level": self.confidence_level,
            "quality_policy_version": self.quality_policy_version,
            "algorithm_version": self.algorithm_version,
        }


@dataclass(frozen=True)
class SharedArtifact:
    """Physical globally deduplicated artifact."""

    artifact_id: str
    artifact_kind: ArtifactKind
    input_hash: str
    payload: JsonRow
    dependency_ids: tuple[str, ...]


@dataclass(frozen=True)
class UserArtifactRef:
    """User-visible reference to a shared artifact."""

    user_id: str
    snapshot_id: str
    artifact_id: str
    artifact_kind: ArtifactKind


@dataclass
class InMemoryArtifactCache:
    """In-memory shared artifact cache plus user references."""

    artifacts_by_id: dict[str, SharedArtifact] = field(
        default_factory=lambda: dict[str, SharedArtifact]()
    )
    refs: set[tuple[str, str, str]] = field(default_factory=lambda: set[tuple[str, str, str]]())

    def get_or_create(
        self,
        *,
        artifact_kind: ArtifactKind,
        artifact_id: str,
        input_hash: str,
        payload: JsonRow,
        dependency_ids: tuple[str, ...],
    ) -> SharedArtifact:
        """Create or reuse one shared physical artifact."""

        existing = self.artifacts_by_id.get(artifact_id)
        if existing is not None:
            if existing.input_hash != input_hash:
                raise ArtifactCacheError("artifact id collision with different input hash")
            return existing
        artifact = SharedArtifact(
            artifact_id=artifact_id,
            artifact_kind=artifact_kind,
            input_hash=input_hash,
            payload=payload,
            dependency_ids=dependency_ids,
        )
        self.artifacts_by_id[artifact_id] = artifact
        return artifact

    def grant_ref(
        self,
        *,
        user_id: str,
        snapshot_id: str,
        artifact: SharedArtifact,
    ) -> UserArtifactRef:
        """Create a user-visible reference without changing the physical artifact."""

        self.refs.add((user_id, snapshot_id, artifact.artifact_id))
        return UserArtifactRef(
            user_id=user_id,
            snapshot_id=snapshot_id,
            artifact_id=artifact.artifact_id,
            artifact_kind=artifact.artifact_kind,
        )

    def require_ref(self, *, user_id: str, snapshot_id: str, artifact_id: str) -> SharedArtifact:
        """Resolve an artifact only through a user-owned reference."""

        if (user_id, snapshot_id, artifact_id) not in self.refs:
            raise ArtifactCacheError("artifact is not visible to user snapshot")
        artifact = self.artifacts_by_id.get(artifact_id)
        if artifact is None:
            raise ArtifactCacheError("artifact not found")
        return artifact


def create_return_artifact(
    *,
    cache: InMemoryArtifactCache,
    inputs: ScopedMarketInputs,
    key: ReturnArtifactKey,
    payload: JsonRow,
) -> tuple[SharedArtifact, UserArtifactRef]:
    """Create or reuse a return artifact after scoped-input authorization."""

    _assert_key_matches_inputs(key.quote_snapshot_hash, inputs.input_hash)
    artifact_id = key.artifact_id()
    artifact = cache.get_or_create(
        artifact_kind="returns",
        artifact_id=artifact_id,
        input_hash=_stable_hash(key.as_payload()),
        payload=payload,
        dependency_ids=(inputs.snapshot.snapshot_id,),
    )
    ref = cache.grant_ref(
        user_id=inputs.snapshot.user_id,
        snapshot_id=inputs.snapshot.snapshot_id,
        artifact=artifact,
    )
    return artifact, ref


def create_univariate_artifact(
    *,
    cache: InMemoryArtifactCache,
    inputs: ScopedMarketInputs,
    return_artifact: SharedArtifact,
    key: UnivariateArtifactKey,
    payload: JsonRow,
) -> tuple[SharedArtifact, UserArtifactRef]:
    """Create or reuse a univariate artifact after dependency authorization."""

    cache.require_ref(
        user_id=inputs.snapshot.user_id,
        snapshot_id=inputs.snapshot.snapshot_id,
        artifact_id=return_artifact.artifact_id,
    )
    artifact = cache.get_or_create(
        artifact_kind="univariate",
        artifact_id=key.artifact_id(),
        input_hash=_stable_hash(key.as_payload()),
        payload=payload,
        dependency_ids=(return_artifact.artifact_id,),
    )
    ref = cache.grant_ref(
        user_id=inputs.snapshot.user_id,
        snapshot_id=inputs.snapshot.snapshot_id,
        artifact=artifact,
    )
    return artifact, ref


def _assert_key_matches_inputs(key_input_hash: str, scoped_input_hash: str) -> None:
    if key_input_hash != scoped_input_hash:
        raise ArtifactCacheError("artifact key does not match authorized inputs")


def _artifact_id(kind: str, payload: JsonRow) -> str:
    return f"{kind}-{_stable_hash(payload)}"


def _stable_hash(payload: JsonRow) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
