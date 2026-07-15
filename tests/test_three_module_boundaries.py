from __future__ import annotations

import importlib
from pathlib import Path

from founder.architecture_checks import check_architecture
from founder.contract_versioning import (
    ContractChangeKind,
    ContractVersion,
    classify_contract_change,
)
from founder.refresh.contracts import REFRESH_CONTRACT_VERSION
from founder.refresh.service import RefreshService
from founder.selection.contracts import SELECTION_CONTRACT_VERSION
from founder.selection.service import SelectionService
from founder.update.contracts import UPDATE_CONTRACT_VERSION
from founder.update.service import UpdateService


def test_three_domain_services_expose_stable_contract_versions() -> None:
    assert ContractVersion("refresh", 1) == REFRESH_CONTRACT_VERSION
    assert ContractVersion("selection", 1) == SELECTION_CONTRACT_VERSION
    assert ContractVersion("update", 1) == UPDATE_CONTRACT_VERSION
    assert RefreshService.contract_version() == "refresh@v1"
    assert SelectionService.contract_version() == "selection@v1"
    assert UpdateService.contract_version() == "update@v1"


def test_contract_change_classification_marks_breaking_changes() -> None:
    assert (
        classify_contract_change(
            fields_removed_or_renamed=False,
            field_types_changed=False,
            fields_added=True,
        )
        == ContractChangeKind.ADDITIVE
    )
    assert (
        classify_contract_change(
            fields_removed_or_renamed=True,
            field_types_changed=False,
            fields_added=True,
        )
        == ContractChangeKind.BREAKING
    )


def test_three_domain_cli_modules_are_parser_adapters_only() -> None:
    for module_name in (
        "founder.refresh.cli",
        "founder.selection.cli",
        "founder.update.cli",
    ):
        module = importlib.import_module(module_name)

        assert module.contract_version().endswith("@v1")
        assert "register_parser" in module.__all__


def test_three_domain_architecture_boundary_rejects_wrong_direction_imports(
    tmp_path: Path,
) -> None:
    root = tmp_path / "founder"
    (root / "refresh").mkdir(parents=True)
    (root / "selection").mkdir()
    (root / "update").mkdir()
    (root / "refresh" / "bad.py").write_text(
        "from founder.selection.service import SelectionService\n",
        encoding="utf-8",
    )
    (root / "selection" / "bad.py").write_text(
        "from founder.update.contracts import UPDATE_CONTRACT_VERSION\n",
        encoding="utf-8",
    )
    (root / "update" / "bad.py").write_text(
        "from founder.refresh.cli import register_parser\n",
        encoding="utf-8",
    )

    violations = check_architecture(root)

    assert any("refresh imports downstream modules" in item for item in violations)
    assert any("selection imports Update" in item for item in violations)
    assert any("update imports private founder.refresh modules" in item for item in violations)


def test_current_three_domain_architecture_has_no_boundary_violations() -> None:
    assert check_architecture() == []
