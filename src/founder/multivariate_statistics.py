"""Multivariate portfolio statistics for selected ISIN listings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from founder.evaluation import (
    build_asset_metrics,
    build_return_matrix,
    equal_weight_portfolio,
    write_efficient_frontier,
    write_portfolio_evaluation,
    write_rebalance_simulation,
    write_tail_risk_evaluation,
    write_walk_forward_backtest,
)
from founder.gold import write_gold_inputs
from founder.paths import LakePaths
from founder.portfolio import (
    PortfolioConstraints,
    write_hierarchical_risk_parity,
    write_maximum_diversification,
    write_optimized_weights,
)
from founder.silver import read_silver_quotes
from founder.table_io import JsonRow, write_rows

DEFAULT_OBJECTIVES: tuple[str, ...] = (
    "equal_weight",
    "minimum_variance",
    "maximum_sharpe",
    "risk_parity",
)


@dataclass(frozen=True)
class MultivariateStatisticsConfig:
    """Configuration for one multivariate statistics run."""

    evaluation_id: str = "multivariate-latest"
    portfolio_id_prefix: str = "multivariate"
    confidence_level: float = 0.95
    grid_step: float = 0.1
    train_window: int = 2
    test_window: int = 1
    walk_forward_profile: str = "development"
    rebalance_schedule: str = "monthly"
    transaction_cost_rate: float = 0.0
    drift_threshold: float | None = None
    constraints: PortfolioConstraints = PortfolioConstraints(max_weight=1.0)
    objectives: tuple[str, ...] = DEFAULT_OBJECTIVES
    frontier_target_returns: tuple[float, ...] = (-0.01, 0.0, 0.01)
    concurrency: int = 2


def write_multivariate_statistics(
    paths: LakePaths,
    selected_rows: Sequence[Mapping[str, Any]],
    *,
    config: MultivariateStatisticsConfig | None = None,
) -> dict[str, Any]:
    """Write portfolio analytics for the selected listings.

    The selected rows are expected to come from Univariate Filter membership.
    This function intentionally filters Silver quotes first, then builds all
    downstream Gold, Evaluation, and Portfolio artifacts from that pinned set.
    """
    resolved_config = config or MultivariateStatisticsConfig()
    quotes = _filter_quotes_to_selection(read_silver_quotes(paths), selected_rows)
    returns, _correlations, _covariances, _features = write_gold_inputs(
        paths,
        quotes,
        concurrency=resolved_config.concurrency,
    )
    matrix = build_return_matrix(returns, resolved_config.evaluation_id)
    asset_metrics = build_asset_metrics(
        matrix,
        resolved_config.evaluation_id,
        confidence_level=resolved_config.confidence_level,
    )
    write_rows(paths.gold_return_matrix(resolved_config.evaluation_id), matrix)
    write_rows(paths.gold_asset_metrics(resolved_config.evaluation_id), asset_metrics)

    if not matrix:
        return {
            "asset_metric_rows": len(asset_metrics),
            "backtest_rows": 0,
            "backtest_weight_rows": 0,
            "evaluation_id": resolved_config.evaluation_id,
            "frontier_points": 0,
            "frontier_weight_rows": 0,
            "hrp_cluster_rows": 0,
            "hrp_linkage_rows": 0,
            "matrix_rows": 0,
            "maximum_diversification_metric_rows": 0,
            "optimized_weight_rows": 0,
            "portfolio_count": 0,
            "quote_rows": len(quotes),
            "return_rows": len(returns),
            "selected_listing_count": len(
                {
                    (str(row["isin"]), str(row["exchange"]), str(row["code"]))
                    for row in selected_rows
                }
            ),
        }

    written_portfolios = 0
    equal_weight_id = _portfolio_id(resolved_config, "equal_weight")
    if matrix:
        equal_weights = equal_weight_portfolio(matrix)
        _write_portfolio_bundle(
            paths,
            evaluation_id=resolved_config.evaluation_id,
            portfolio_id=equal_weight_id,
            objective="equal_weight",
            weights=equal_weights,
            confidence_level=resolved_config.confidence_level,
            rebalance_schedule=resolved_config.rebalance_schedule,
            transaction_cost_rate=resolved_config.transaction_cost_rate,
            drift_threshold=resolved_config.drift_threshold,
        )
        written_portfolios += 1

    optimized_weight_rows: list[JsonRow] = []
    for objective in resolved_config.objectives:
        if objective == "equal_weight":
            continue
        rows = write_optimized_weights(
            paths,
            evaluation_id=resolved_config.evaluation_id,
            objective=objective,
            portfolio_id=_portfolio_id(resolved_config, objective),
            constraints=resolved_config.constraints,
            grid_step=resolved_config.grid_step,
        )
        optimized_weight_rows.extend(rows)
        _write_portfolio_bundle(
            paths,
            evaluation_id=resolved_config.evaluation_id,
            portfolio_id=_portfolio_id(resolved_config, objective),
            objective=objective,
            weights=_weights_from_rows(rows),
            confidence_level=resolved_config.confidence_level,
            rebalance_schedule=resolved_config.rebalance_schedule,
            transaction_cost_rate=resolved_config.transaction_cost_rate,
            drift_threshold=resolved_config.drift_threshold,
        )
        written_portfolios += 1

    hrp_weights, hrp_clusters, hrp_linkage = write_hierarchical_risk_parity(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "hierarchical_risk_parity"),
        constraints=resolved_config.constraints,
    )
    _write_portfolio_bundle(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "hierarchical_risk_parity"),
        objective="hierarchical_risk_parity",
        weights=_weights_from_rows(hrp_weights),
        confidence_level=resolved_config.confidence_level,
        rebalance_schedule=resolved_config.rebalance_schedule,
        transaction_cost_rate=resolved_config.transaction_cost_rate,
        drift_threshold=resolved_config.drift_threshold,
    )
    written_portfolios += 1

    max_div_weights, max_div_metrics = write_maximum_diversification(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "maximum_diversification"),
        constraints=resolved_config.constraints,
        grid_step=resolved_config.grid_step,
    )
    _write_portfolio_bundle(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        portfolio_id=_portfolio_id(resolved_config, "maximum_diversification"),
        objective="maximum_diversification",
        weights=_weights_from_rows(max_div_weights),
        confidence_level=resolved_config.confidence_level,
        rebalance_schedule=resolved_config.rebalance_schedule,
        transaction_cost_rate=resolved_config.transaction_cost_rate,
        drift_threshold=resolved_config.drift_threshold,
    )
    written_portfolios += 1

    frontier_points, frontier_weights = write_efficient_frontier(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        constraints=resolved_config.constraints,
        target_returns=resolved_config.frontier_target_returns,
        grid_step=resolved_config.grid_step,
    )
    backtests, backtest_weights = write_walk_forward_backtest(
        paths,
        evaluation_id=resolved_config.evaluation_id,
        run_id=f"{resolved_config.evaluation_id}-walk-forward",
        objective="minimum_variance",
        constraints=resolved_config.constraints,
        train_window=resolved_config.train_window,
        test_window=resolved_config.test_window,
        grid_step=resolved_config.grid_step,
        profile=resolved_config.walk_forward_profile,
        transaction_cost_rate=resolved_config.transaction_cost_rate,
    )
    return {
        "asset_metric_rows": len(asset_metrics),
        "backtest_rows": len(backtests),
        "backtest_weight_rows": len(backtest_weights),
        "evaluation_id": resolved_config.evaluation_id,
        "frontier_points": len(frontier_points),
        "frontier_weight_rows": len(frontier_weights),
        "hrp_cluster_rows": len(hrp_clusters),
        "hrp_linkage_rows": len(hrp_linkage),
        "matrix_rows": len(matrix),
        "maximum_diversification_metric_rows": len(max_div_metrics),
        "optimized_weight_rows": len(optimized_weight_rows)
        + len(hrp_weights)
        + len(max_div_weights),
        "portfolio_count": written_portfolios,
        "quote_rows": len(quotes),
        "return_rows": len(returns),
        "selected_listing_count": len(
            {(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in selected_rows}
        ),
    }


def _write_portfolio_bundle(
    paths: LakePaths,
    *,
    evaluation_id: str,
    portfolio_id: str,
    objective: str,
    weights: Mapping[str, float],
    confidence_level: float,
    rebalance_schedule: str,
    transaction_cost_rate: float,
    drift_threshold: float | None,
) -> None:
    write_portfolio_evaluation(
        paths,
        evaluation_id=evaluation_id,
        portfolio_id=portfolio_id,
        weights=weights,
        objective=objective,
    )
    write_tail_risk_evaluation(
        paths,
        evaluation_id=evaluation_id,
        run_id=f"{evaluation_id}-tail-risk",
        portfolio_id=portfolio_id,
        weights=weights,
        confidence_level=confidence_level,
    )
    write_rebalance_simulation(
        paths,
        evaluation_id=evaluation_id,
        run_id=f"{evaluation_id}-rebalance-{rebalance_schedule}",
        portfolio_id=portfolio_id,
        target_weights=weights,
        schedule=rebalance_schedule,
        transaction_cost_rate=transaction_cost_rate,
        drift_threshold=drift_threshold,
    )


def _filter_quotes_to_selection(
    quotes: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
) -> list[JsonRow]:
    selected = {(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in selected_rows}
    return [
        dict(row)
        for row in quotes
        if (str(row["isin"]), str(row["exchange"]), str(row["code"])) in selected
    ]


def _portfolio_id(config: MultivariateStatisticsConfig, objective: str) -> str:
    return f"{config.portfolio_id_prefix}-{objective.replace('_', '-')}"


def _weights_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {str(row["isin"]): float(row["weight"]) for row in rows}


__all__ = [
    "DEFAULT_OBJECTIVES",
    "MultivariateStatisticsConfig",
    "write_multivariate_statistics",
]
