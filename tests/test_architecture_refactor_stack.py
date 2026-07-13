from __future__ import annotations

import importlib
import json
from pathlib import Path

from founder.gold import write_gold_inputs
from founder.paths import LakePaths
from founder.portfolio import (
    BASELINE_OPTIMIZER_TYPE,
    PortfolioConstraints,
    build_optimizer_diagnostics,
    write_optimized_weights,
)
from founder.run_state import build_job_manifest, read_job_manifest, write_job_manifest
from founder.table_io import read_rows, write_rows


def test_internal_evaluation_and_portfolio_boundaries_preserve_public_imports() -> None:
    matrix = importlib.import_module("founder.evaluation_parts.matrix")
    objectives = importlib.import_module("founder.portfolio_parts.objectives")

    assert matrix.build_return_matrix.__module__ == "founder.evaluation"
    assert objectives.optimize_portfolio.__module__ == "founder.portfolio"


def test_internal_boundary_modules_expose_declared_reexports() -> None:
    module_names = [
        "founder.evaluation_parts.backtest",
        "founder.evaluation_parts.frontier",
        "founder.evaluation_parts.matrix",
        "founder.evaluation_parts.metrics",
        "founder.evaluation_parts.portfolio_returns",
        "founder.evaluation_parts.rebalance",
        "founder.evaluation_parts.tail_risk",
        "founder.portfolio_parts.constraints",
        "founder.portfolio_parts.diversification",
        "founder.portfolio_parts.hrp",
        "founder.portfolio_parts.objectives",
        "founder.portfolio_parts.risk_parity",
    ]

    for module_name in module_names:
        module = importlib.import_module(module_name)

        assert module.__all__
        assert all(
            getattr(module, name).__module__.startswith("founder.") for name in module.__all__
        )


def test_job_manifest_redacts_secrets_and_gold_writes_compatibility_manifest(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    manifest = build_job_manifest(
        job_type="bronze",
        run_id="run-1",
        status="failed",
        input_paths=["b", "a"],
        output_paths=["z", "y"],
        row_counts={"quotes": 1},
        concurrency=2,
        error_summary=[{"api_token": "secret", "message": "offline"}],
    )

    payload = write_job_manifest(paths, manifest)

    assert payload["input_paths"] == ["a", "b"]
    assert payload["error_summary"][0]["api_token"] == "<redacted>"
    assert read_job_manifest(paths, "bronze", "run-1") == payload

    write_gold_inputs(
        paths,
        [
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "date": "2026-07-10",
                "adjusted_close": 100,
            },
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "date": "2026-07-11",
                "adjusted_close": 101,
            },
        ],
        concurrency=1,
    )

    gold_manifest = read_job_manifest(paths, "gold", "gold-2026-07-11")
    assert gold_manifest["status"] == "completed"
    assert gold_manifest["row_counts"]["returns"] == 1
    assert gold_manifest["concurrency"] == 1


def test_optimizer_diagnostics_are_deterministic_metadata(tmp_path: Path) -> None:
    listings = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
        {"isin": "IE2", "exchange": "AS", "code": "BBB"},
    ]
    covariance_rows = [
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.01,
        },
        {
            "left_isin": "IE1",
            "left_exchange": "XETRA",
            "left_code": "AAA",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.0,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.0,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE2",
            "right_exchange": "AS",
            "right_code": "BBB",
            "covariance": 0.04,
        },
    ]
    constraints = PortfolioConstraints(max_weight=0.8)

    diagnostics = build_optimizer_diagnostics(
        listings,
        covariance_rows,
        {"IE1": 0.01, "IE2": 0.02},
        {"IE1": 0.8, "IE2": 0.2},
        objective="minimum_variance",
        constraints=constraints,
    )

    assert diagnostics["optimizer_type"] == BASELINE_OPTIMIZER_TYPE
    assert diagnostics["optimizer_status"] == "feasible"
    assert diagnostics["covariance_condition"] == "ok"
    assert diagnostics["constraint_violations"] == []

    paths = LakePaths(root=tmp_path / "lake")
    matrix_rows = [
        {
            "evaluation_id": "eval-1",
            "date": "2026-07-11",
            "isin": row["isin"],
            "exchange": row["exchange"],
            "code": row["code"],
            "return": 0.01,
        }
        for row in listings
    ]
    write_rows(paths.gold_return_matrix("eval-1"), matrix_rows)
    write_rows(paths.gold_covariance("XETRA", "IE1"), covariance_rows[:2])
    write_rows(paths.gold_covariance("AS", "IE2"), covariance_rows[2:])

    rows = write_optimized_weights(
        paths,
        evaluation_id="eval-1",
        objective="minimum_variance",
        portfolio_id="min-var",
        constraints=constraints,
        grid_step=0.1,
    )
    written_diagnostics = json.loads(str(rows[0]["diagnostics"]))

    assert read_rows(paths.gold_optimized_weights("minimum_variance", "eval-1")) == rows
    assert written_diagnostics["optimizer_type"] == BASELINE_OPTIMIZER_TYPE
    assert written_diagnostics["optimizer_status"] == "feasible"
