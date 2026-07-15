"""Public Selection contracts (versioned DTOs)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from founder.contract_versioning import ContractVersion, stable_contract_id

SELECTION_CONTRACT_VERSION = ContractVersion(name="selection", version=1)

type PredicateValue = str | int | float | bool | None | tuple[str | int | float | bool, ...]


class FilterPhase(Enum):
    CATALOG = "catalog"
    RAW_METRIC = "raw_metric"
    CLASSIFICATION = "classification"


class FieldType(Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"


class SelectionState(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    EMPTY = "empty"
    PENDING_UPDATE = "pending_update"
    READY = "ready"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class MetricRequirement:
    metric_name: str
    phase: FilterPhase
    benchmark_required: bool = False
    profile: str = "default"

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise ValueError("metric_name must not be empty")


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    name: str
    field_type: FieldType
    phase: FilterPhase
    scope: str
    nullable: bool
    allowed_operators: tuple[str, ...]
    metric_requirement: MetricRequirement | None = None
    benchmark_required: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("field name must not be empty")
        if not self.allowed_operators:
            raise ValueError("field definition must allow at least one operator")


CATALOG_OPERATORS = ("eq", "ne", "in", "not-in", "contains", "starts-with", "regex")
ORDERED_OPERATORS = ("lt", "lte", "gt", "gte", "between")
NULL_OPERATORS = ("is-null", "not-null")


FIELD_REGISTRY: dict[str, FieldDefinition] = {
    "exchange": FieldDefinition(
        name="exchange",
        field_type=FieldType.STRING,
        phase=FilterPhase.CATALOG,
        scope="listing",
        nullable=False,
        allowed_operators=(*CATALOG_OPERATORS, *NULL_OPERATORS),
    ),
    "trading_currency": FieldDefinition(
        name="trading_currency",
        field_type=FieldType.STRING,
        phase=FilterPhase.CATALOG,
        scope="listing",
        nullable=True,
        allowed_operators=(*CATALOG_OPERATORS, *NULL_OPERATORS),
    ),
    "declared_payout_frequency": FieldDefinition(
        name="declared_payout_frequency",
        field_type=FieldType.ENUM,
        phase=FilterPhase.CATALOG,
        scope="instrument",
        nullable=True,
        allowed_operators=("eq", "ne", "in", "not-in", *NULL_OPERATORS),
    ),
    "annualized_volatility": FieldDefinition(
        name="annualized_volatility",
        field_type=FieldType.NUMBER,
        phase=FilterPhase.RAW_METRIC,
        scope="instrument",
        nullable=True,
        allowed_operators=(*ORDERED_OPERATORS, *NULL_OPERATORS),
        metric_requirement=MetricRequirement("annualized_volatility", FilterPhase.RAW_METRIC),
    ),
    "expected_shortfall": FieldDefinition(
        name="expected_shortfall",
        field_type=FieldType.NUMBER,
        phase=FilterPhase.RAW_METRIC,
        scope="instrument",
        nullable=True,
        allowed_operators=(*ORDERED_OPERATORS, *NULL_OPERATORS),
        metric_requirement=MetricRequirement("expected_shortfall", FilterPhase.RAW_METRIC),
    ),
    "downside_capture_ratio": FieldDefinition(
        name="downside_capture_ratio",
        field_type=FieldType.NUMBER,
        phase=FilterPhase.CLASSIFICATION,
        scope="instrument",
        nullable=True,
        allowed_operators=(*ORDERED_OPERATORS, *NULL_OPERATORS),
        metric_requirement=MetricRequirement(
            "downside_capture_ratio",
            FilterPhase.CLASSIFICATION,
            benchmark_required=True,
        ),
        benchmark_required=True,
    ),
    "risk_type": FieldDefinition(
        name="risk_type",
        field_type=FieldType.ENUM,
        phase=FilterPhase.CLASSIFICATION,
        scope="instrument",
        nullable=True,
        allowed_operators=("eq", "ne", "in", "not-in", *NULL_OPERATORS),
        metric_requirement=MetricRequirement("risk_type", FilterPhase.CLASSIFICATION),
    ),
}


@dataclass(frozen=True, slots=True)
class Predicate:
    field: str
    operator: str
    value: PredicateValue = None

    def __post_init__(self) -> None:
        field_definition(self.field)
        validate_predicate(self)

    def canonical_payload(self) -> dict[str, object]:
        definition = field_definition(self.field)
        return {
            "contract": SELECTION_CONTRACT_VERSION.qualified_name,
            "field": definition.name,
            "operator": self.operator,
            "phase": definition.phase.value,
            "value": _normalized_value(self.value),
        }


@dataclass(frozen=True, slots=True)
class MetricEvidence:
    metric_name: str
    artifact_id: str
    available: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ClassificationProfileRef:
    profile_id: str
    version: int = 1


@dataclass(frozen=True, slots=True)
class BenchmarkRef:
    listing_id: str
    refresh_snapshot_id: str


@dataclass(frozen=True, slots=True)
class PredicateSet:
    predicates: tuple[Predicate, ...] = field(default_factory=tuple)

    @property
    def predicate_set_id(self) -> str:
        return stable_contract_id("predicate_set", self.canonical_payload())

    @property
    def metric_requirements(self) -> tuple[MetricRequirement, ...]:
        requirements = {
            requirement.metric_name: requirement
            for predicate in self.predicates
            if (requirement := field_definition(predicate.field).metric_requirement) is not None
        }
        return tuple(requirements[name] for name in sorted(requirements))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract": SELECTION_CONTRACT_VERSION.qualified_name,
            "predicates": sorted(
                (predicate.canonical_payload() for predicate in self.predicates),
                key=lambda row: (
                    str(row["phase"]),
                    str(row["field"]),
                    str(row["operator"]),
                    str(row["value"]),
                ),
            ),
        }


@dataclass(frozen=True, slots=True)
class SelectionDefinition:
    predicates: PredicateSet
    refresh_snapshot_id: str
    canonical_listing_policy_id: str
    benchmark: BenchmarkRef | None = None
    name: str = ""

    @property
    def selection_id(self) -> str:
        return stable_contract_id("selection", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "benchmark": None
            if self.benchmark is None
            else {
                "listing_id": self.benchmark.listing_id,
                "refresh_snapshot_id": self.benchmark.refresh_snapshot_id,
            },
            "canonical_listing_policy_id": self.canonical_listing_policy_id,
            "contract": SELECTION_CONTRACT_VERSION.qualified_name,
            "predicates": self.predicates.canonical_payload(),
            "refresh_snapshot_id": self.refresh_snapshot_id,
        }


@dataclass(frozen=True, slots=True)
class CandidateMembership:
    selection_id: str
    catalog_snapshot_id: str
    listing_ids: tuple[str, ...]

    @property
    def candidate_membership_id(self) -> str:
        return stable_contract_id("candidate_membership", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "catalog_snapshot_id": self.catalog_snapshot_id,
            "contract": SELECTION_CONTRACT_VERSION.qualified_name,
            "listing_ids": tuple(sorted(self.listing_ids)),
            "selection_id": self.selection_id,
        }


@dataclass(frozen=True, slots=True)
class MetricEvidenceManifestRef:
    manifest_id: str
    candidate_membership_id: str


@dataclass(frozen=True, slots=True)
class FinalMembership:
    candidate_membership_id: str
    evidence_manifest_id: str
    listing_ids: tuple[str, ...]

    @property
    def membership_id(self) -> str:
        return stable_contract_id("final_membership", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "candidate_membership_id": self.candidate_membership_id,
            "contract": SELECTION_CONTRACT_VERSION.qualified_name,
            "evidence_manifest_id": self.evidence_manifest_id,
            "listing_ids": tuple(sorted(self.listing_ids)),
        }


@dataclass(frozen=True, slots=True)
class CurrentSelectionPointer:
    selection_id: str
    candidate_membership_id: str
    state: SelectionState
    membership_id: str = ""

    def __post_init__(self) -> None:
        if self.state is SelectionState.READY and not self.membership_id:
            raise ValueError("ready selection pointer requires a final membership id")


@dataclass(frozen=True, slots=True)
class SelectionMembershipDiff:
    previous_membership_id: str
    current_membership_id: str
    added_listing_ids: tuple[str, ...]
    removed_listing_ids: tuple[str, ...]


def field_definition(field_name: str) -> FieldDefinition:
    try:
        return FIELD_REGISTRY[field_name]
    except KeyError as error:
        raise ValueError(f"unknown selection field: {field_name}") from error


def validate_predicate(predicate: Predicate) -> None:
    definition = field_definition(predicate.field)
    if predicate.operator not in definition.allowed_operators:
        raise ValueError(f"operator {predicate.operator} is not valid for {predicate.field}")
    if predicate.operator in NULL_OPERATORS and predicate.value is not None:
        raise ValueError(f"operator {predicate.operator} does not accept a value")
    if predicate.operator not in NULL_OPERATORS and predicate.value is None:
        raise ValueError(f"operator {predicate.operator} requires a value")
    if predicate.operator == "between" and (
        not isinstance(predicate.value, tuple) or len(predicate.value) != 2
    ):
        raise ValueError("between requires a two-item tuple value")
    if predicate.operator in {"in", "not-in"} and not isinstance(predicate.value, tuple):
        raise ValueError(f"operator {predicate.operator} requires a tuple value")


def _normalized_value(value: PredicateValue) -> object:
    if isinstance(value, tuple):
        return tuple(
            sorted(str(item).casefold() if isinstance(item, str) else item for item in value)
        )
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def public_field_listing() -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "allowed_operators": definition.allowed_operators,
            "benchmark_required": definition.benchmark_required,
            "field_type": definition.field_type.value,
            "metric_requirement": None
            if definition.metric_requirement is None
            else definition.metric_requirement.metric_name,
            "name": definition.name,
            "nullable": definition.nullable,
            "phase": definition.phase.value,
            "scope": definition.scope,
        }
        for definition in sorted(FIELD_REGISTRY.values(), key=lambda item: item.name)
    )


__all__ = [
    "BenchmarkRef",
    "CandidateMembership",
    "ClassificationProfileRef",
    "CurrentSelectionPointer",
    "FIELD_REGISTRY",
    "FieldDefinition",
    "FieldType",
    "FinalMembership",
    "FilterPhase",
    "MetricEvidence",
    "MetricEvidenceManifestRef",
    "MetricRequirement",
    "Predicate",
    "PredicateSet",
    "PredicateValue",
    "SELECTION_CONTRACT_VERSION",
    "SelectionDefinition",
    "SelectionMembershipDiff",
    "SelectionState",
    "field_definition",
    "public_field_listing",
    "validate_predicate",
]
