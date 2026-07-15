"""Public Update contracts (versioned DTOs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from founder.contract_versioning import ContractVersion, stable_contract_id

UPDATE_CONTRACT_VERSION = ContractVersion(name="update", version=1)


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    version: int = 1
    window: str = "trailing_3y"
    annualization_days: int = 252

    @property
    def metric_spec_id(self) -> str:
        return stable_contract_id("metric_spec", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "annualization_days": self.annualization_days,
            "contract": UPDATE_CONTRACT_VERSION.qualified_name,
            "name": self.name,
            "version": self.version,
            "window": self.window,
        }


@dataclass(frozen=True, slots=True)
class PinnedUpdateInput:
    selection_id: str
    candidate_membership_id: str
    refresh_snapshot_id: str
    final_membership_id: str = ""


@dataclass(frozen=True, slots=True)
class MetricCacheKey:
    kind: str
    subject_id: str
    metric_spec_id: str
    input_version_id: str

    @property
    def cache_key_id(self) -> str:
        return stable_contract_id("metric_cache", self.canonical_payload())

    def canonical_payload(self) -> dict[str, str]:
        return {
            "input_version_id": self.input_version_id,
            "kind": self.kind,
            "metric_spec_id": self.metric_spec_id,
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True, slots=True)
class MetricArtifactRef:
    cache_key_id: str
    artifact_id: str
    status: str = "ready"


class UpdateWorkKind(Enum):
    ASSET_METRIC = "asset_metric"
    SELECTION_FINALIZATION = "selection_finalization"
    CALENDAR_METRIC = "calendar_metric"
    PAIR_METRIC = "pair_metric"
    ANALYSIS = "analysis"


class UpdateRunStatus(Enum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class UpdateWorkItem:
    work_id: str
    kind: UpdateWorkKind
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    pinned_input: PinnedUpdateInput
    work_items: tuple[UpdateWorkItem, ...] = field(default_factory=tuple)

    @property
    def plan_id(self) -> str:
        return stable_contract_id("update_plan", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract": UPDATE_CONTRACT_VERSION.qualified_name,
            "pinned_input": {
                "candidate_membership_id": self.pinned_input.candidate_membership_id,
                "final_membership_id": self.pinned_input.final_membership_id,
                "refresh_snapshot_id": self.pinned_input.refresh_snapshot_id,
                "selection_id": self.pinned_input.selection_id,
            },
            "work_items": sorted(
                (
                    {
                        "depends_on": tuple(sorted(item.depends_on)),
                        "kind": item.kind.value,
                        "work_id": item.work_id,
                    }
                    for item in self.work_items
                ),
                key=lambda row: str(row["work_id"]),
            ),
        }


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    selection_id: str
    run_id: str
    concurrency: int = 2
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class UpdateRunManifest:
    run_id: str
    plan_id: str
    status: UpdateRunStatus
    published: bool = False
    stale_reason: str = ""


@dataclass(frozen=True, slots=True)
class UpdateResult:
    run_id: str
    plan_id: str
    artifact_refs: tuple[MetricArtifactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class CurrentUpdatePointer:
    run_id: str
    plan_id: str


__all__ = [
    "CurrentUpdatePointer",
    "MetricArtifactRef",
    "MetricCacheKey",
    "MetricSpec",
    "PinnedUpdateInput",
    "UPDATE_CONTRACT_VERSION",
    "UpdatePlan",
    "UpdateRequest",
    "UpdateResult",
    "UpdateRunManifest",
    "UpdateRunStatus",
    "UpdateWorkItem",
    "UpdateWorkKind",
]
