"""Content-addressed hosted analytical artifact cache contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from founder.scoped_inputs import ScopedMarketInputs
from founder.table_io import JsonRow


class ArtifactCacheError(RuntimeError):
    """Raised when artifact cache access fails closed."""


ArtifactKind = Literal["returns", "univariate", "bivariate"]


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
class BivariateArtifactKey:
    """Exact bivariate artifact identity for one unordered return-artifact pair."""

    left_return_artifact_id: str
    right_return_artifact_id: str
    alignment_hash: str
    metric_parameters: JsonRow
    minimum_observation_policy: JsonRow
    algorithm_version: str

    def __post_init__(self) -> None:
        """Reject ambiguous same-input pairs before an artifact id can be built."""

        if self.left_return_artifact_id == self.right_return_artifact_id:
            raise ArtifactCacheError("same return artifact pairs are not allowed")

    def artifact_id(self) -> str:
        """Return deterministic bivariate artifact id."""

        return _artifact_id("bivariate", self.as_payload())

    def as_payload(self) -> JsonRow:
        """Return canonical key payload independent of selection order."""

        left, right = self.ordered_return_artifact_ids()
        return {
            "left_return_artifact_id": left,
            "right_return_artifact_id": right,
            "alignment_hash": self.alignment_hash,
            "metric_parameters": self.metric_parameters,
            "minimum_observation_policy": self.minimum_observation_policy,
            "algorithm_version": self.algorithm_version,
        }

    def ordered_return_artifact_ids(self) -> tuple[str, str]:
        """Return canonical unordered-pair orientation."""

        left, right = sorted((self.left_return_artifact_id, self.right_return_artifact_id))
        return left, right


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


def create_bivariate_artifact(
    *,
    cache: InMemoryArtifactCache,
    inputs: ScopedMarketInputs,
    left_return_artifact: SharedArtifact,
    right_return_artifact: SharedArtifact,
    key: BivariateArtifactKey,
    payload: JsonRow,
) -> tuple[SharedArtifact, UserArtifactRef]:
    """Create or reuse a bivariate artifact after authorizing both return inputs."""

    required_return_ids = key.ordered_return_artifact_ids()
    actual_return_ids = tuple(
        sorted((left_return_artifact.artifact_id, right_return_artifact.artifact_id))
    )
    if required_return_ids != actual_return_ids:
        raise ArtifactCacheError("bivariate key does not match return artifact dependencies")
    for return_artifact_id in required_return_ids:
        cache.require_ref(
            user_id=inputs.snapshot.user_id,
            snapshot_id=inputs.snapshot.snapshot_id,
            artifact_id=return_artifact_id,
        )
    artifact = cache.get_or_create(
        artifact_kind="bivariate",
        artifact_id=key.artifact_id(),
        input_hash=_stable_hash(key.as_payload()),
        payload=payload,
        dependency_ids=required_return_ids,
    )
    ref = cache.grant_ref(
        user_id=inputs.snapshot.user_id,
        snapshot_id=inputs.snapshot.snapshot_id,
        artifact=artifact,
    )
    return artifact, ref


def build_bivariate_alignment_hash(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    date_key: str = "date",
    value_key: str = "return",
) -> str:
    """Hash exact common-date return alignment, including values and row order."""

    left_by_date = _return_values_by_date(left_rows, date_key=date_key, value_key=value_key)
    right_by_date = _return_values_by_date(right_rows, date_key=date_key, value_key=value_key)
    common_dates = sorted(set(left_by_date).intersection(right_by_date))
    if not common_dates:
        raise ArtifactCacheError("bivariate alignment has no common dates")
    aligned_rows: list[JsonRow] = [
        {
            "date": current_date,
            "left_return": left_by_date[current_date],
            "right_return": right_by_date[current_date],
        }
        for current_date in common_dates
    ]
    return _stable_hash({"aligned_rows": aligned_rows})


def bivariate_bucket_for_artifact_id(artifact_id: str, *, bucket_count: int) -> int:
    """Assign a bivariate artifact id to a deterministic storage bucket."""

    if bucket_count < 1:
        raise ArtifactCacheError("bucket_count must be positive")
    digest = hashlib.sha256(artifact_id.encode()).hexdigest()
    return int(digest[:16], 16) % bucket_count


def validate_bivariate_bucket_rows(
    *, artifact: SharedArtifact, rows: Sequence[Mapping[str, Any]]
) -> None:
    """Fail closed when bucket rows do not contain the expected bivariate artifact."""

    if artifact.artifact_kind != "bivariate":
        raise ArtifactCacheError("bucket validation requires a bivariate artifact")
    if not any(row.get("artifact_id") == artifact.artifact_id for row in rows):
        raise ArtifactCacheError("bivariate bucket is missing expected artifact")


def _assert_key_matches_inputs(key_input_hash: str, scoped_input_hash: str) -> None:
    if key_input_hash != scoped_input_hash:
        raise ArtifactCacheError("artifact key does not match authorized inputs")


def _return_values_by_date(
    rows: Sequence[Mapping[str, Any]], *, date_key: str, value_key: str
) -> dict[str, Any]:
    values_by_date: dict[str, Any] = {}
    for row in rows:
        current_date = row.get(date_key)
        if current_date is None:
            raise ArtifactCacheError("return row is missing date")
        if value_key not in row:
            raise ArtifactCacheError("return row is missing value")
        values_by_date[str(current_date)] = row[value_key]
    return values_by_date


def _artifact_id(kind: str, payload: JsonRow) -> str:
    return f"{kind}-{_stable_hash(payload)}"


def _stable_hash(payload: JsonRow) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
