"""Lake table schema contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

GoldReturnRow = TypedDict(
    "GoldReturnRow",
    {
        "isin": str,
        "exchange": str,
        "code": str,
        "date": str,
        "return": float,
        "simple_return": float,
    },
)


class PairValueRow(TypedDict):
    left_isin: str
    left_exchange: str
    left_code: str
    right_isin: str
    right_exchange: str
    right_code: str


class CovarianceRow(PairValueRow):
    covariance: float


class CorrelationEdgeRow(TypedDict):
    version: str
    metric: str
    left_id: int
    right_id: int
    left_isin: str
    left_exchange: str
    left_code: str
    right_isin: str
    right_exchange: str
    right_code: str
    date_start: str
    date_end: str
    n_observations: int
    value: float


class BucketedCorrelationEdgeRow(CorrelationEdgeRow):
    bucket: int


ReturnMatrixRow = TypedDict(
    "ReturnMatrixRow",
    {
        "evaluation_id": str,
        "date": str,
        "isin": str,
        "exchange": str,
        "code": str,
        "return": float,
        "simple_return": float,
    },
)


class OptimizedWeightRow(TypedDict):
    evaluation_id: str
    objective: str
    portfolio_id: str
    isin: str
    exchange: str
    code: str
    weight: float
    constraints: str
    diagnostics: str


class JobManifestRow(TypedDict):
    job_id: str
    job_type: str
    run_id: str
    status: str
    started_at: str
    finished_at: str
    input_paths: str
    output_paths: str
    row_counts: str
    concurrency: int
    resume_marker: str
    error_summary: str


@dataclass(frozen=True)
class DatasetContract:
    name: str
    version: int
    owner: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    sort_key: tuple[str, ...] = ()


SCHEMAS: dict[str, tuple[str, ...]] = {
    "all_isins": (
        "isin",
        "exchange",
        "code",
        "name",
        "instrument_type",
        "country",
        "currency",
        "source_exchange",
        "fetched_at",
    ),
    "isin_selection": (
        "selection_id",
        "isin",
        "exchange",
        "code",
        "name",
        "source_module",
    ),
    "search_candidates": (
        "search_run_id",
        "query",
        "source_endpoint",
        "code",
        "exchange",
        "instrument_type",
        "country",
        "currency",
        "isin",
        "name",
        "normalized_name",
        "found_at",
    ),
    "canonical_universe": (
        "search_run_id",
        "isin",
        "code",
        "exchange",
        "instrument_type",
        "country",
        "currency",
        "name",
        "normalized_name",
        "selection_reason",
        "selected_for_bronze",
    ),
    "bronze_plan": ("run_id", "isin", "code", "exchange", "symbol", "start_date", "end_date"),
    "quotes": (
        "run_id",
        "isin",
        "code",
        "exchange",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "currency",
        "bronzed_at",
    ),
    "coverage": (
        "run_id",
        "isin",
        "code",
        "exchange",
        "first_quote_date",
        "last_quote_date",
        "observed_rows",
        "missing_periods",
        "next_bronze_start",
    ),
    "quote_gaps": (
        "run_id",
        "isin",
        "code",
        "exchange",
        "symbol",
        "data_type",
        "gap_type",
        "gap_start",
        "gap_end",
        "missing_dates",
    ),
    "errors": ("run_id", "code", "exchange", "endpoint", "error_type", "message"),
    "returns": ("isin", "exchange", "code", "date", "return", "simple_return"),
    "correlation": (
        "left_isin",
        "left_exchange",
        "left_code",
        "right_isin",
        "right_exchange",
        "right_code",
        "correlation",
    ),
    "covariance": (
        "left_isin",
        "left_exchange",
        "left_code",
        "right_isin",
        "right_exchange",
        "right_code",
        "covariance",
    ),
    "correlation_edges": (
        "version",
        "metric",
        "left_id",
        "right_id",
        "left_isin",
        "left_exchange",
        "left_code",
        "right_isin",
        "right_exchange",
        "right_code",
        "date_start",
        "date_end",
        "n_observations",
        "value",
        "bucket",
    ),
    "univariate_statistics": (
        "isin",
        "exchange",
        "code",
        "confidence_level",
        "first_quote_date",
        "last_quote_date",
        "quote_observation_count",
        "first_return_date",
        "last_return_date",
        "return_observation_count",
        "start_adjusted_close",
        "end_adjusted_close",
        "total_return",
        "cagr",
        "cumulative_log_return",
        "mean_log_return",
        "median_log_return",
        "min_log_return",
        "max_log_return",
        "mean_simple_return",
        "median_simple_return",
        "min_simple_return",
        "max_simple_return",
        "daily_log_return_std",
        "daily_simple_return_std",
        "annualized_return",
        "annualized_log_return",
        "annualized_simple_return",
        "annualized_geometric_return",
        "annualized_volatility",
        "realized_variance",
        "realized_volatility",
        "downside_deviation",
        "sharpe_ratio",
        "sortino_ratio",
        "var",
        "expected_shortfall",
        "tail_observation_count",
        "max_drawdown",
        "positive_day_ratio",
        "log_price_slope",
        "trend_r_squared",
        "availability_reason",
        "distribution_frequency",
        "distribution_events_per_year",
        "last_distribution_date",
        "distribution_observation_count",
        "quarantined_price_count",
        "non_positive_price_detected",
        "duplicate_date_detected",
        "stale_price_detected",
        "unexplained_gap_detected",
        "meets_min_history_252",
        "meets_min_history_504",
        "meets_min_history_756",
        "production_eligible",
        "data_quality_reason",
    ),
    "bivariate_statistics": (
        "pair_key",
        "left_listing_key",
        "right_listing_key",
        "left_id",
        "right_id",
        "left_isin",
        "left_exchange",
        "left_code",
        "right_isin",
        "right_exchange",
        "right_code",
        "date_start",
        "date_end",
        "n_observations",
        "pearson_correlation",
        "spearman_correlation",
        "covariance",
        "left_variance",
        "right_variance",
        "left_beta_to_right",
        "right_beta_to_left",
    ),
    "gold_runs": (
        "status",
        "isin",
        "exchange",
        "code",
        "input_last_quote_date",
        "input_snapshot_date",
        "input_listing_count",
        "completed_at",
    ),
    "job_manifests": (
        "job_id",
        "job_type",
        "run_id",
        "status",
        "started_at",
        "finished_at",
        "input_paths",
        "output_paths",
        "row_counts",
        "concurrency",
        "resume_marker",
        "error_summary",
    ),
    "return_matrix": (
        "evaluation_id",
        "date",
        "isin",
        "exchange",
        "code",
        "return",
        "simple_return",
    ),
    "asset_metrics": (
        "evaluation_id",
        "isin",
        "exchange",
        "code",
        "observation_count",
        "first_return_date",
        "last_return_date",
        "mean_return",
        "annualized_return",
        "annualized_volatility",
        "downside_deviation",
        "sharpe_ratio",
        "sortino_ratio",
        "confidence_level",
        "var",
        "cvar",
        "tail_observation_count",
        "meets_min_history_252",
        "meets_min_history_504",
        "meets_min_history_756",
        "production_eligible",
    ),
    "portfolio_returns": (
        "evaluation_id",
        "portfolio_id",
        "date",
        "return",
        "cumulative_wealth",
    ),
    "drawdowns": (
        "evaluation_id",
        "portfolio_id",
        "date",
        "cumulative_wealth",
        "running_peak",
        "drawdown",
        "drawdown_duration",
        "recovery_duration",
        "is_recovered",
    ),
    "portfolio_metrics": (
        "evaluation_id",
        "portfolio_id",
        "objective",
        "annualized_return",
        "annualized_volatility",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown",
        "calmar_ratio",
        "ulcer_index",
        "turnover",
    ),
    "frontier_points": (
        "evaluation_id",
        "frontier_point_id",
        "target_return",
        "expected_return",
        "volatility",
        "sharpe_ratio",
        "is_feasible",
        "diagnostics",
    ),
    "frontier_weights": (
        "evaluation_id",
        "frontier_point_id",
        "isin",
        "exchange",
        "code",
        "weight",
    ),
    "backtests": (
        "run_id",
        "evaluation_id",
        "split_id",
        "objective",
        "train_start_date",
        "train_end_date",
        "test_start_date",
        "test_end_date",
        "realized_return",
        "realized_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "turnover",
    ),
    "backtest_weights": (
        "run_id",
        "evaluation_id",
        "split_id",
        "isin",
        "exchange",
        "code",
        "weight",
    ),
    "rebalance_events": (
        "run_id",
        "evaluation_id",
        "portfolio_id",
        "date",
        "schedule",
        "pre_trade_value",
        "turnover",
        "transaction_cost",
        "post_cost_return",
        "portfolio_value",
        "cash_remainder",
        "is_rebalance",
    ),
    "rebalance_weights": (
        "run_id",
        "evaluation_id",
        "portfolio_id",
        "isin",
        "exchange",
        "code",
        "date",
        "pre_trade_value",
        "pre_trade_weight",
        "target_weight",
        "target_value",
        "trade_value",
        "is_rebalance",
    ),
    "tail_risk": (
        "run_id",
        "evaluation_id",
        "portfolio_id",
        "confidence_level",
        "var",
        "cvar",
        "tail_observation_count",
        "scenario_count",
    ),
    "optimized_weights": (
        "evaluation_id",
        "objective",
        "portfolio_id",
        "isin",
        "exchange",
        "code",
        "weight",
        "constraints",
        "diagnostics",
    ),
    "hrp_clusters": (
        "evaluation_id",
        "portfolio_id",
        "cluster_id",
        "left_cluster",
        "right_cluster",
        "cluster_variance",
        "allocation",
        "ordered_isins",
    ),
    "diversification_metrics": (
        "evaluation_id",
        "portfolio_id",
        "diversification_ratio",
        "portfolio_volatility",
        "weighted_asset_volatility",
        "diagnostics",
    ),
}

DATASET_OWNERS: dict[str, str] = {
    "all_isins": "fetch_all_isins",
    "isin_selection": "selection",
    "search_candidates": "search",
    "canonical_universe": "search",
    "bronze_plan": "bronze",
    "quotes": "silver",
    "coverage": "bronze",
    "quote_gaps": "bronze",
    "errors": "bronze",
    "returns": "gold",
    "correlation": "gold",
    "covariance": "gold",
    "correlation_edges": "gold",
    "univariate_statistics": "gold",
    "bivariate_statistics": "gold",
    "gold_runs": "gold",
    "job_manifests": "operations",
    "return_matrix": "evaluation",
    "asset_metrics": "evaluation",
    "portfolio_returns": "evaluation",
    "drawdowns": "evaluation",
    "portfolio_metrics": "evaluation",
    "frontier_points": "evaluation",
    "frontier_weights": "evaluation",
    "backtests": "evaluation",
    "backtest_weights": "evaluation",
    "rebalance_events": "evaluation",
    "rebalance_weights": "evaluation",
    "tail_risk": "evaluation",
    "optimized_weights": "portfolio",
    "hrp_clusters": "portfolio",
    "diversification_metrics": "portfolio",
}

DATASET_SORT_KEYS: dict[str, tuple[str, ...]] = {
    "all_isins": ("isin", "exchange", "code"),
    "isin_selection": ("selection_id", "isin", "exchange", "code"),
    "search_candidates": ("search_run_id", "isin", "exchange", "code"),
    "canonical_universe": ("isin",),
    "bronze_plan": ("run_id", "isin", "exchange", "code"),
    "quotes": ("isin", "exchange", "code", "date"),
    "coverage": ("isin", "exchange", "code"),
    "quote_gaps": ("isin", "gap_start", "gap_end"),
    "returns": ("isin", "exchange", "code", "date"),
    "correlation": ("left_isin", "left_exchange", "left_code", "right_isin"),
    "covariance": ("left_isin", "left_exchange", "left_code", "right_isin"),
    "correlation_edges": ("version", "metric", "bucket", "left_id", "right_id"),
    "univariate_statistics": ("isin", "exchange", "code"),
    "bivariate_statistics": ("pair_key",),
    "gold_runs": ("isin", "exchange", "code"),
    "job_manifests": ("job_type", "run_id"),
    "return_matrix": ("evaluation_id", "date", "isin"),
    "asset_metrics": ("evaluation_id", "isin"),
    "portfolio_returns": ("evaluation_id", "portfolio_id", "date"),
    "drawdowns": ("evaluation_id", "portfolio_id", "date"),
    "portfolio_metrics": ("evaluation_id", "portfolio_id"),
    "frontier_points": ("evaluation_id", "frontier_point_id"),
    "frontier_weights": ("evaluation_id", "frontier_point_id", "isin"),
    "backtests": ("run_id", "split_id"),
    "backtest_weights": ("run_id", "split_id", "isin"),
    "rebalance_events": ("run_id", "date"),
    "rebalance_weights": ("run_id", "date", "isin"),
    "tail_risk": ("run_id", "portfolio_id"),
    "optimized_weights": ("evaluation_id", "objective", "portfolio_id", "isin"),
    "hrp_clusters": ("evaluation_id", "portfolio_id", "cluster_id"),
    "diversification_metrics": ("evaluation_id", "portfolio_id"),
}


def _build_dataset_contracts() -> dict[str, DatasetContract]:
    contracts: dict[str, DatasetContract] = {}
    for name, fields in SCHEMAS.items():
        if len(set(fields)) != len(fields):
            raise ValueError(f"duplicate fields in schema: {name}")
        if name in contracts:
            raise ValueError(f"duplicate dataset contract: {name}")
        contracts[name] = DatasetContract(
            name=name,
            version=1,
            owner=DATASET_OWNERS.get(name, "unknown"),
            required_fields=fields,
            sort_key=DATASET_SORT_KEYS.get(name, ()),
        )
    return contracts


DATASET_CONTRACTS: dict[str, DatasetContract] = _build_dataset_contracts()


def required_fields(table_name: str) -> tuple[str, ...]:
    try:
        return DATASET_CONTRACTS[table_name].required_fields
    except KeyError as error:
        raise ValueError(f"unknown schema: {table_name}") from error


def dataset_contract(table_name: str) -> DatasetContract:
    try:
        return DATASET_CONTRACTS[table_name]
    except KeyError as error:
        raise ValueError(f"unknown dataset contract: {table_name}") from error


def validate_fields(table_name: str, row: Mapping[str, object]) -> None:
    missing = [field for field in required_fields(table_name) if field not in row]
    if missing:
        raise ValueError(f"{table_name} row missing fields: {', '.join(missing)}")


def validate_rows(table_name: str, rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        validate_fields(table_name, row)
