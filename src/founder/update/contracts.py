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


@dataclass(frozen=True, slots=True)
class PriceObservation:
    listing_id: str
    date: str
    adjusted_close: float
    close: float = 0.0
    dividend: float = 0.0
    nav: float | None = None


@dataclass(frozen=True, slots=True)
class AssetMetricArtifact:
    listing_id: str
    metric_spec_id: str
    observation_count: int
    first_return_date: str
    last_return_date: str
    mean_log_return: float
    annualized_volatility: float
    downside_deviation: float
    sharpe_ratio: float
    sortino_ratio: float
    expected_shortfall: float
    var: float
    max_drawdown: float
    positive_day_ratio: float
    cagr: float
    log_price_slope: float
    trend_r_squared: float
    availability_reason: str = ""

    @property
    def artifact_id(self) -> str:
        return stable_contract_id("asset_metric", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "annualized_volatility": round(self.annualized_volatility, 12),
            "availability_reason": self.availability_reason,
            "cagr": round(self.cagr, 12),
            "downside_deviation": round(self.downside_deviation, 12),
            "expected_shortfall": round(self.expected_shortfall, 12),
            "first_return_date": self.first_return_date,
            "last_return_date": self.last_return_date,
            "listing_id": self.listing_id,
            "log_price_slope": round(self.log_price_slope, 12),
            "max_drawdown": round(self.max_drawdown, 12),
            "mean_log_return": round(self.mean_log_return, 12),
            "metric_spec_id": self.metric_spec_id,
            "observation_count": self.observation_count,
            "positive_day_ratio": round(self.positive_day_ratio, 12),
            "sharpe_ratio": round(self.sharpe_ratio, 12),
            "sortino_ratio": round(self.sortino_ratio, 12),
            "trend_r_squared": round(self.trend_r_squared, 12),
            "var": round(self.var, 12),
        }


@dataclass(frozen=True, slots=True)
class ClassificationProfile:
    name: str = "default-screening"
    version: int = 1
    minimum_observations: int = 2
    expected_shortfall_confidence: float = 0.975

    @property
    def profile_id(self) -> str:
        return stable_contract_id(
            "classification_profile",
            {
                "expected_shortfall_confidence": self.expected_shortfall_confidence,
                "minimum_observations": self.minimum_observations,
                "name": self.name,
                "version": self.version,
            },
        )


@dataclass(frozen=True, slots=True)
class ScreeningClassification:
    listing_id: str
    profile_id: str
    asset_metric_artifact_id: str
    close_price_path_type: str
    nav_path_type: str
    total_return_type: str
    risk_type: str
    availability_reason: str = ""

    @property
    def classification_id(self) -> str:
        return stable_contract_id("classification", self.canonical_payload())

    def canonical_payload(self) -> dict[str, str]:
        return {
            "asset_metric_artifact_id": self.asset_metric_artifact_id,
            "availability_reason": self.availability_reason,
            "close_price_path_type": self.close_price_path_type,
            "listing_id": self.listing_id,
            "nav_path_type": self.nav_path_type,
            "profile_id": self.profile_id,
            "risk_type": self.risk_type,
            "total_return_type": self.total_return_type,
        }


@dataclass(frozen=True, slots=True)
class SelectionCalendar:
    final_membership_id: str
    dates: tuple[str, ...]
    policy_version: int = 1

    @property
    def calendar_id(self) -> str:
        return stable_contract_id(
            "selection_calendar",
            {
                "dates": self.dates,
                "final_membership_id": self.final_membership_id,
                "policy_version": self.policy_version,
            },
        )


@dataclass(frozen=True, slots=True)
class ComparableAssetMetric:
    listing_id: str
    calendar_id: str
    mean_return: float
    variance: float

    @property
    def comparable_metric_id(self) -> str:
        return stable_contract_id(
            "comparable_asset_metric",
            {
                "calendar_id": self.calendar_id,
                "listing_id": self.listing_id,
                "mean_return": round(self.mean_return, 12),
                "variance": round(self.variance, 12),
            },
        )


@dataclass(frozen=True, slots=True)
class PairMetricArtifact:
    left_listing_id: str
    right_listing_id: str
    metric_spec_id: str
    observation_count: int
    first_common_date: str
    last_common_date: str
    covariance: float
    pearson: float
    spearman: float

    def __post_init__(self) -> None:
        if self.left_listing_id >= self.right_listing_id:
            raise ValueError("pair metric listing ids must be sorted and distinct")

    @property
    def pair_id(self) -> str:
        return stable_contract_id(
            "pair",
            {"left_listing_id": self.left_listing_id, "right_listing_id": self.right_listing_id},
        )

    @property
    def artifact_id(self) -> str:
        return stable_contract_id("pair_metric", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "covariance": round(self.covariance, 12),
            "first_common_date": self.first_common_date,
            "last_common_date": self.last_common_date,
            "left_listing_id": self.left_listing_id,
            "metric_spec_id": self.metric_spec_id,
            "observation_count": self.observation_count,
            "pearson": round(self.pearson, 12),
            "right_listing_id": self.right_listing_id,
            "spearman": round(self.spearman, 12),
        }


@dataclass(frozen=True, slots=True)
class EvaluationProfile:
    name: str = "portfolio-full"
    version: int = 1
    max_members: int = 1_000
    include_pair_metrics: bool = True
    include_portfolio_outputs: bool = True

    @property
    def profile_id(self) -> str:
        return stable_contract_id(
            "evaluation_profile",
            {
                "include_pair_metrics": self.include_pair_metrics,
                "include_portfolio_outputs": self.include_portfolio_outputs,
                "max_members": self.max_members,
                "name": self.name,
                "version": self.version,
            },
        )


@dataclass(frozen=True, slots=True)
class SelectionAnalysisManifest:
    selection_id: str
    final_membership_id: str
    calendar_id: str
    evaluation_profile_id: str
    artifact_ids: tuple[str, ...]
    status: str = "ready"

    @property
    def analysis_id(self) -> str:
        return stable_contract_id("selection_analysis", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "artifact_ids": tuple(sorted(self.artifact_ids)),
            "calendar_id": self.calendar_id,
            "evaluation_profile_id": self.evaluation_profile_id,
            "final_membership_id": self.final_membership_id,
            "selection_id": self.selection_id,
            "status": self.status,
        }


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
    "AssetMetricArtifact",
    "ClassificationProfile",
    "ComparableAssetMetric",
    "EvaluationProfile",
    "MetricArtifactRef",
    "MetricCacheKey",
    "MetricSpec",
    "PairMetricArtifact",
    "PinnedUpdateInput",
    "PriceObservation",
    "ScreeningClassification",
    "SelectionAnalysisManifest",
    "SelectionCalendar",
    "UPDATE_CONTRACT_VERSION",
    "UpdatePlan",
    "UpdateRequest",
    "UpdateResult",
    "UpdateRunManifest",
    "UpdateRunStatus",
    "UpdateWorkItem",
    "UpdateWorkKind",
]
