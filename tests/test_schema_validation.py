from __future__ import annotations

import pytest

import camovar.schema_validation as schema_validation
from camovar.schemas import DATASET_CONTRACTS, SCHEMAS, DatasetContract


def test_registered_schemas_are_valid() -> None:
    assert schema_validation.validate_schema_registry() == []
    assert schema_validation.main() == 0


def test_schema_validation_reports_contract_errors() -> None:
    contracts = dict(DATASET_CONTRACTS)
    contracts["returns"] = DatasetContract(
        name="wrong-name",
        version=0,
        owner="unknown",
        required_fields=("isin", "isin"),
        optional_fields=("isin",),
        sort_key=("missing",),
    )

    errors = schema_validation.validate_schema_registry(contracts)

    assert "contract key/name mismatch: returns != wrong-name" in errors
    assert "contract version must be positive: returns" in errors
    assert "contract owner is not explicit: returns" in errors
    assert "contract has duplicate required fields: returns" in errors
    assert "contract fields are both required and optional: returns: isin" in errors
    assert "contract sort key references unknown fields: returns: missing" in errors


def test_schema_validation_reports_registry_relationship_errors() -> None:
    contracts = dict(DATASET_CONTRACTS)
    contracts.pop("coverage")
    contracts["unknown"] = DatasetContract(
        name="unknown",
        version=1,
        owner="test",
        required_fields=(),
        optional_fields=("value", "value"),
    )

    errors = schema_validation.validate_schema_registry(
        contracts,
        schemas=SCHEMAS,
        owners={"orphan": "test"},
        sort_keys={"orphan": ("value",)},
    )

    assert "schema without dataset contract: coverage" in errors
    assert "dataset contract without schema: unknown" in errors
    assert "owner for unknown schema: orphan" in errors
    assert "sort key for unknown schema: orphan" in errors
    assert "contract has no required fields: unknown" in errors
    assert "contract has duplicate optional fields: unknown" in errors


def test_schema_validation_main_reports_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        schema_validation,
        "validate_schema_registry",
        lambda: ["schema failed"],
    )

    assert schema_validation.main() == 1
    assert "schema failed" in capsys.readouterr().err
