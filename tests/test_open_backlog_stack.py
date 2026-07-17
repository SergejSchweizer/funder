from pathlib import Path

import pytest

from founder.evaluation import (
    build_efficient_frontier,
    build_rebalance_events,
    build_tail_risk_rows,
    build_walk_forward_backtest,
    write_efficient_frontier,
    write_rebalance_simulation,
    write_tail_risk_evaluation,
    write_walk_forward_backtest,
)
from founder.paths import LakePaths
from founder.portfolio import (
    PortfolioConstraints,
    build_diversification_metric_rows,
    build_hrp_cluster_rows,
    hierarchical_risk_parity_weights,
    optimize_portfolio,
    write_hierarchical_risk_parity,
    write_maximum_diversification,
)
from founder.table_io import read_rows, write_rows


def _matrix_rows() -> list[dict[str, object]]:
    returns = {
        "2026-07-10": (0.01, 0.00),
        "2026-07-11": (0.02, -0.01),
        "2026-07-12": (-0.01, 0.03),
        "2026-07-13": (0.01, 0.02),
        "2026-07-14": (0.00, 0.01),
    }
    rows: list[dict[str, object]] = []
    for item_date, (left_return, right_return) in returns.items():
        rows.extend(
            [
                {
                    "evaluation_id": "eval-1",
                    "date": item_date,
                    "isin": "IE1",
                    "exchange": "XETRA",
                    "code": "AAA",
                    "return": left_return,
                },
                {
                    "evaluation_id": "eval-1",
                    "date": item_date,
                    "isin": "IE2",
                    "exchange": "AS",
                    "code": "BBB",
                    "return": right_return,
                },
            ]
        )
    return rows


def _covariance_rows() -> list[dict[str, object]]:
    return [
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
            "covariance": 0.002,
        },
        {
            "left_isin": "IE2",
            "left_exchange": "AS",
            "left_code": "BBB",
            "right_isin": "IE1",
            "right_exchange": "XETRA",
            "right_code": "AAA",
            "covariance": 0.002,
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


def _prepare_lake(paths: LakePaths) -> None:
    matrix = _matrix_rows()
    covariances = _covariance_rows()
    write_rows(paths.gold_return_matrix("eval-1"), matrix)
    write_rows(paths.gold_covariance("XETRA", "IE1"), covariances[:2])
    write_rows(paths.gold_covariance("AS", "IE2"), covariances[2:])


def test_walk_forward_frontier_rebalance_and_tail_risk_outputs(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    _prepare_lake(paths)
    constraints = PortfolioConstraints(max_weight=1.0)

    backtests, backtest_weights = write_walk_forward_backtest(
        paths,
        evaluation_id="eval-1",
        run_id="bt-1",
        objective="minimum_variance",
        constraints=constraints,
        train_window=2,
        test_window=1,
        grid_step=0.5,
    )
    frontier_points, frontier_weights = write_efficient_frontier(
        paths,
        evaluation_id="eval-1",
        constraints=constraints,
        target_returns=[0.0, 0.01],
        grid_step=0.5,
    )
    rebalance_events, rebalance_weights = write_rebalance_simulation(
        paths,
        evaluation_id="eval-1",
        run_id="rebalance-1",
        portfolio_id="equal-weight",
        schedule="monthly",
        transaction_cost_rate=0.001,
    )
    tail_rows = write_tail_risk_evaluation(
        paths,
        evaluation_id="eval-1",
        run_id="tail-1",
        portfolio_id="equal-weight",
        confidence_level=0.8,
    )

    assert [row["split_id"] for row in backtests] == ["split-001", "split-002", "split-003"]
    assert len(backtest_weights) == 6
    assert read_rows(paths.gold_backtests("bt-1")) == backtests
    assert [row["frontier_point_id"] for row in frontier_points] == ["frontier-001", "frontier-002"]
    assert len(frontier_weights) == 4
    assert read_rows(paths.gold_frontier_points("eval-1")) == frontier_points
    assert rebalance_events[0]["is_rebalance"] is True
    assert read_rows(paths.gold_rebalance_events("rebalance-1")) == rebalance_events
    assert read_rows(paths.gold_rebalance_weights("rebalance-1")) == rebalance_weights
    assert tail_rows[0]["tail_observation_count"] >= 1
    assert read_rows(paths.gold_tail_risk("tail-1")) == tail_rows


def test_builders_cover_rejections_and_threshold_rebalance() -> None:
    matrix = _matrix_rows()
    constraints = PortfolioConstraints(max_weight=1.0)

    with pytest.raises(ValueError, match="mode"):
        build_walk_forward_backtest(
            matrix,
            run_id="bt-1",
            evaluation_id="eval-1",
            objective="minimum_variance",
            constraints=constraints,
            train_window=2,
            test_window=1,
            mode="bad",
        )
    events, event_weights = build_rebalance_events(
        matrix,
        run_id="rebalance-1",
        evaluation_id="eval-1",
        portfolio_id="threshold",
        target_weights={"IE1": 0.5, "IE2": 0.5},
        schedule="threshold",
        drift_threshold=0.0,
    )
    tail = build_tail_risk_rows(
        matrix,
        run_id="tail-1",
        evaluation_id="eval-1",
        portfolio_id="equal-weight",
        weights={"IE1": 0.5, "IE2": 0.5},
        confidence_level=0.8,
    )
    points, weights = build_efficient_frontier(
        matrix,
        evaluation_id="eval-1",
        constraints=constraints,
        target_returns=[0.5],
        grid_step=0.5,
    )

    assert any(row["is_rebalance"] for row in events)
    assert any(row["is_rebalance"] for row in event_weights)
    assert tail[0]["cvar"] >= tail[0]["var"]
    assert points[0]["is_feasible"] is False
    assert {row["weight"] for row in weights} == {0.0}


def test_hrp_and_maximum_diversification_write_deterministic_gold_outputs(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    _prepare_lake(paths)
    listings = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA"},
        {"isin": "IE2", "exchange": "AS", "code": "BBB"},
    ]
    constraints = PortfolioConstraints(max_weight=1.0)

    hrp_weights = hierarchical_risk_parity_weights(listings, _covariance_rows(), constraints)
    cluster_rows = build_hrp_cluster_rows(
        listings,
        _covariance_rows(),
        evaluation_id="eval-1",
        portfolio_id="hrp",
    )
    max_div_weights = optimize_portfolio(
        listings,
        _covariance_rows(),
        {},
        objective="maximum_diversification",
        constraints=constraints,
        grid_step=0.5,
    )
    metric_rows = build_diversification_metric_rows(
        listings,
        _covariance_rows(),
        max_div_weights,
        evaluation_id="eval-1",
        portfolio_id="max-div",
    )
    hrp_written, clusters_written, linkage_written = write_hierarchical_risk_parity(
        paths,
        evaluation_id="eval-1",
        portfolio_id="hrp",
        constraints=constraints,
    )
    max_div_written, max_div_metrics = write_maximum_diversification(
        paths,
        evaluation_id="eval-1",
        portfolio_id="max-div",
        constraints=constraints,
        grid_step=0.5,
    )

    assert sum(hrp_weights.values()) == pytest.approx(1.0)
    assert cluster_rows[0]["ordered_isins"] == "IE1,IE2"
    assert metric_rows[0]["diversification_ratio"] >= 1.0
    assert read_rows(paths.gold_hrp_clusters("eval-1")) == clusters_written
    assert read_rows(paths.gold_hrp_linkage("eval-1")) == linkage_written
    assert len(linkage_written) == 1
    assert read_rows(paths.gold_diversification_metrics("eval-1")) == max_div_metrics
    assert len(hrp_written) == 2
    assert len(max_div_written) == 2
