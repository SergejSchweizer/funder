from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_pytest_shard_module() -> ModuleType:
    """Load the repository script module without relying on test import paths."""
    spec = importlib.util.spec_from_file_location(
        "pytest_shard", REPOSITORY_ROOT / "scripts" / "pytest_shard.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load pytest_shard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PYTEST_SHARD = load_pytest_shard_module()


def test_select_shard_partitions_files_deterministically() -> None:
    files = [Path(f"tests/test_{index}.py") for index in range(7)]

    assert PYTEST_SHARD.select_shard(files, shard_index=1, shard_count=3) == [
        Path("tests/test_0.py"),
        Path("tests/test_3.py"),
        Path("tests/test_6.py"),
    ]
    assert PYTEST_SHARD.select_shard(files, shard_index=2, shard_count=3) == [
        Path("tests/test_1.py"),
        Path("tests/test_4.py"),
    ]
    assert PYTEST_SHARD.select_shard(files, shard_index=3, shard_count=3) == [
        Path("tests/test_2.py"),
        Path("tests/test_5.py"),
    ]


def test_filter_suite_splits_unit_and_integration_files() -> None:
    files = [
        Path("tests/test_cli.py"),
        Path("tests/test_http.py"),
        Path("tests/test_risk_model.py"),
        Path("tests/test_portfolio_solvers.py"),
    ]

    assert PYTEST_SHARD.filter_suite(files, suite="integration") == [
        Path("tests/test_cli.py"),
        Path("tests/test_http.py"),
    ]
    assert PYTEST_SHARD.filter_suite(files, suite="unit") == [
        Path("tests/test_risk_model.py"),
        Path("tests/test_portfolio_solvers.py"),
    ]
    assert PYTEST_SHARD.filter_suite(files, suite="all") == files


def test_select_shard_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="shard_count"):
        PYTEST_SHARD.select_shard([], shard_index=1, shard_count=0)
    with pytest.raises(ValueError, match="shard_index"):
        PYTEST_SHARD.select_shard([], shard_index=0, shard_count=1)


def test_filter_suite_rejects_unknown_suite() -> None:
    with pytest.raises(ValueError, match="unknown test suite"):
        PYTEST_SHARD.filter_suite([], suite="slow")
