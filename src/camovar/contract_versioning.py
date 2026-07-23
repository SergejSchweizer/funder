"""Shared contract-version policy for Refresh, Selection, and Update DTOs.

Refresh, Selection, and Update publish immutable, versioned public contracts
(DTOs) to each other and to Evaluation/Portfolio compatibility adapters. This
module defines the one shared policy every domain `contracts` module must
follow so contract evolution stays predictable across the module boundary
stack introduced in the Refresh/Selection/Update PR series.

Policy:

- Every public contract has an explicit `ContractVersion` with a dotted
  `name` (for example ``"refresh.catalog_snapshot"``) and a positive integer
  `version`.
- Adding a new optional field with a safe default is an additive change and
  does not require a new `ContractVersion`.
- Removing a field, renaming a field, or changing a field's type or meaning
  is a breaking change and requires incrementing `version`.
- Canonical serialization for identity and hashing purposes is deterministic
  JSON: sorted keys, explicit field order independent of dict insertion
  order, and no floating-point-sensitive identity fields.
- Each domain module owns migration of its own contract versions; a
  consumer must not silently reinterpret a payload from an unknown or newer
  `ContractVersion` than it declares support for.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ContractChangeKind(Enum):
    """Classifies a proposed contract-schema change."""

    ADDITIVE = "additive"
    BREAKING = "breaking"


@dataclass(frozen=True, slots=True)
class ContractVersion:
    """An explicit, versioned identity for a public domain contract.

    Attributes:
        name: Dotted contract name, for example ``"refresh.catalog_snapshot"``.
        version: Positive integer version, incremented for every breaking change.
    """

    name: str
    version: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("contract name must not be empty")
        if self.version < 1:
            raise ValueError("contract version must be at least 1")

    @property
    def qualified_name(self) -> str:
        return f"{self.name}@v{self.version}"


def classify_contract_change(
    *,
    fields_removed_or_renamed: bool,
    field_types_changed: bool,
    fields_added: bool = False,
) -> ContractChangeKind:
    """Classify a proposed contract change as additive or breaking.

    Removing or renaming a field, or changing a field's type or meaning, is
    always breaking regardless of any fields also being added. Otherwise,
    adding fields (or making no structural change) is additive.
    """
    if fields_removed_or_renamed or field_types_changed:
        return ContractChangeKind.BREAKING
    del fields_added
    return ContractChangeKind.ADDITIVE


def canonical_json(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    """Return deterministic JSON for contract identity payloads."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_contract_id(prefix: str, payload: Mapping[str, Any] | Sequence[Any]) -> str:
    """Return a stable content id for a versioned contract payload."""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


__all__ = [
    "ContractChangeKind",
    "ContractVersion",
    "canonical_json",
    "classify_contract_change",
    "stable_contract_id",
]
