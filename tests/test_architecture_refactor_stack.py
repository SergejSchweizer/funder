from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from founder.architecture_checks import check_architecture
from founder.gold import write_gold_inputs
from founder.gold_pair_stats import bucket_correlation_edges, index_returns, iter_pair_observations
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

    assert matrix.build_return_matrix.__module__ == "founder.evaluation_parts.matrix"
    assert objectives.optimize_portfolio.__module__ == "founder.portfolio_parts.objectives"


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


def test_evaluation_boundary_functions_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEvaluation:
        def __getattr__(self, name: str) -> Any:
            def delegated(*_args: object, **_kwargs: object) -> Any:
                if (
                    name.startswith("write_")
                    or name.startswith("build_walk")
                    or name.startswith("build_efficient")
                ):
                    return ([], [])
                return []

            return delegated

    fake = FakeEvaluation()
    modules = [
        importlib.import_module("founder.evaluation_parts.backtest"),
        importlib.import_module("founder.evaluation_parts.frontier"),
        importlib.import_module("founder.evaluation_parts.matrix"),
        importlib.import_module("founder.evaluation_parts.metrics"),
        importlib.import_module("founder.evaluation_parts.portfolio_returns"),
        importlib.import_module("founder.evaluation_parts.rebalance"),
        importlib.import_module("founder.evaluation_parts.tail_risk"),
    ]
    for module in modules:
        monkeypatch.setattr(module.importlib, "import_module", lambda _name, fake=fake: fake)

    modules[0].build_walk_forward_backtest(
        [],
        run_id="r",
        evaluation_id="e",
        objective="o",
        constraints=object(),
        train_window=1,
        test_window=1,
    )
    modules[0].write_walk_forward_backtest(
        Path("lake"),
        evaluation_id="e",
        run_id="r",
        objective="o",
        constraints=object(),
        train_window=1,
        test_window=1,
    )
    modules[1].build_efficient_frontier(
        [], [], {}, evaluation_id="e", constraints=object(), target_returns=[]
    )
    modules[1].write_efficient_frontier(
        Path("lake"), evaluation_id="e", constraints=object(), target_returns=[]
    )
    modules[2].read_gold_returns(Path("lake"))
    modules[2].build_return_matrix([], "e")
    modules[2].write_evaluation_outputs(Path("lake"), evaluation_id="e")
    modules[3].build_asset_metrics([], "e")
    modules[3].build_portfolio_metrics([], [], evaluation_id="e", portfolio_id="p")
    modules[4].build_portfolio_returns([], {}, evaluation_id="e", portfolio_id="p")
    modules[4].build_drawdowns([])
    modules[4].write_portfolio_evaluation(Path("lake"), evaluation_id="e", portfolio_id="p")
    modules[5].build_rebalance_events([], run_id="r", evaluation_id="e", portfolio_id="p")
    modules[5].write_rebalance_simulation(
        Path("lake"), evaluation_id="e", run_id="r", portfolio_id="p"
    )
    modules[6].build_tail_risk_rows([], run_id="r", evaluation_id="e", portfolio_id="p")
    modules[6].write_tail_risk_evaluation(
        Path("lake"), evaluation_id="e", run_id="r", portfolio_id="p"
    )


def test_portfolio_boundary_functions_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePortfolio:
        PortfolioConstraints = PortfolioConstraints

        def __getattr__(self, name: str) -> Any:
            def delegated(*_args: object, **_kwargs: object) -> Any:
                if name.startswith("write_hierarchical") or name.startswith("write_maximum"):
                    return ([], [])
                if "weights" in name or name.endswith("seed") or name.startswith("optimize"):
                    return {}
                return []

            return delegated

    fake = FakePortfolio()
    modules = [
        importlib.import_module("founder.portfolio_parts.constraints"),
        importlib.import_module("founder.portfolio_parts.diversification"),
        importlib.import_module("founder.portfolio_parts.hrp"),
        importlib.import_module("founder.portfolio_parts.objectives"),
        importlib.import_module("founder.portfolio_parts.risk_parity"),
    ]
    for module in modules:
        monkeypatch.setattr(module.importlib, "import_module", lambda _name, fake=fake: fake)

    modules[0].validate_weights({}, object())
    modules[0].equal_weight_seed([], object())
    modules[1].build_diversification_metric_rows(
        [], [], {}, evaluation_id="e", portfolio_id="p", diagnostics={}
    )
    modules[1].write_maximum_diversification(Path("lake"), evaluation_id="e")
    modules[2].hierarchical_risk_parity_weights([], [], object())
    modules[2].build_hrp_cluster_rows([], [], {}, evaluation_id="e", portfolio_id="p")
    modules[2].write_hierarchical_risk_parity(Path("lake"), evaluation_id="e")
    modules[3].optimize_portfolio([], [])
    modules[3].build_target_weight_rows(
        [],
        {},
        evaluation_id="e",
        objective="o",
        portfolio_id="p",
        constraints=object(),
        diagnostics={},
    )
    modules[3].write_optimized_weights(Path("lake"), evaluation_id="e")
    modules[4].build_risk_contribution_rows([], [], {}, evaluation_id="e", portfolio_id="p")


def test_architecture_checks_pass_current_import_boundaries() -> None:
    assert check_architecture() == []


def test_gold_pair_engine_streams_upper_triangle_observations() -> None:
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-01-01", "return": 0.01},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-01-02", "return": 0.02},
        {"isin": "IE2", "exchange": "XETRA", "code": "BBB", "date": "2026-01-01", "return": 0.03},
        {"isin": "IE2", "exchange": "XETRA", "code": "BBB", "date": "2026-01-02", "return": 0.04},
        {"isin": "IE3", "exchange": "XETRA", "code": "CCC", "date": "2026-01-02", "return": 0.05},
    ]

    observations = list(iter_pair_observations(index_returns(return_rows), include_self=False))

    assert [(item.left_id, item.right_id) for item in observations] == [(0, 1), (0, 2), (1, 2)]
    assert all(item.left_id < item.right_id for item in observations)
    assert observations[0].dates == ("2026-01-01", "2026-01-02")
    assert observations[1].dates == ("2026-01-02",)


def test_gold_pair_engine_assigns_deterministic_edge_buckets() -> None:
    rows = [
        {"left_id": 3, "right_id": 4, "value": 0.5},
        {"left_id": 2, "right_id": 3, "value": 0.4},
    ]

    by_bucket = bucket_correlation_edges(rows, bucket_count=2)

    assert list(by_bucket) == [0, 1]
    assert by_bucket[0][0]["bucket"] == 0
    assert by_bucket[1][0]["bucket"] == 1


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
