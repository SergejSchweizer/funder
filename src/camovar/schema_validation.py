"""Read-only validation for Camovar's dataset schema registry."""

from __future__ import annotations

import sys
from collections.abc import Mapping

from camovar.schemas import (
    DATASET_CONTRACTS,
    DATASET_OWNERS,
    DATASET_SORT_KEYS,
    SCHEMAS,
    DatasetContract,
)


def validate_schema_registry(
    contracts: Mapping[str, DatasetContract] = DATASET_CONTRACTS,
    *,
    schemas: Mapping[str, tuple[str, ...]] = SCHEMAS,
    owners: Mapping[str, str] = DATASET_OWNERS,
    sort_keys: Mapping[str, tuple[str, ...]] = DATASET_SORT_KEYS,
) -> list[str]:
    """Return deterministic validation errors for dataset contracts."""
    errors: list[str] = []
    contract_names = set(contracts)
    schema_names = set(schemas)
    for missing in sorted(schema_names - contract_names):
        errors.append(f"schema without dataset contract: {missing}")
    for unknown in sorted(contract_names - schema_names):
        errors.append(f"dataset contract without schema: {unknown}")
    for unknown in sorted(set(owners) - schema_names):
        errors.append(f"owner for unknown schema: {unknown}")
    for unknown in sorted(set(sort_keys) - schema_names):
        errors.append(f"sort key for unknown schema: {unknown}")

    for name, contract in sorted(contracts.items()):
        if contract.name != name:
            errors.append(f"contract key/name mismatch: {name} != {contract.name}")
        if contract.version < 1:
            errors.append(f"contract version must be positive: {name}")
        if not contract.owner or contract.owner == "unknown":
            errors.append(f"contract owner is not explicit: {name}")
        if not contract.required_fields:
            errors.append(f"contract has no required fields: {name}")
        if len(contract.required_fields) != len(set(contract.required_fields)):
            errors.append(f"contract has duplicate required fields: {name}")
        if len(contract.optional_fields) != len(set(contract.optional_fields)):
            errors.append(f"contract has duplicate optional fields: {name}")
        overlap = sorted(set(contract.required_fields) & set(contract.optional_fields))
        if overlap:
            errors.append(
                f"contract fields are both required and optional: {name}: {', '.join(overlap)}"
            )
        known_fields = set(contract.required_fields) | set(contract.optional_fields)
        missing_sort_fields = [field for field in contract.sort_key if field not in known_fields]
        if missing_sort_fields:
            errors.append(
                f"contract sort key references unknown fields: {name}: "
                f"{', '.join(missing_sort_fields)}"
            )
    return errors


def main() -> int:
    """Validate all registered schemas and return a process exit code."""
    errors = validate_schema_registry()
    if not errors:
        print(f"Validated {len(DATASET_CONTRACTS)} dataset contracts.")
        return 0
    for error in errors:
        print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
