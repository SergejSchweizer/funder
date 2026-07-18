"""Deterministic lake paths shared by modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LakePaths:
    """Simple Bronze/Silver/Gold lake path contract."""

    root: Path = Path("lake")

    @property
    def bronze(self) -> Path:
        return self.root / "bronze"

    @property
    def silver(self) -> Path:
        return self.root / "silver"

    @property
    def gold(self) -> Path:
        return self.root / "gold"

    @property
    def metadata(self) -> Path:
        return self.silver

    def bronze_search_run(self, run_date: str) -> Path:
        return self.bronze / "eodhd" / "search" / f"run_date={run_date}"

    def silver_search_run(self, search_run_id: str) -> Path:
        return self.silver / "search" / f"search_run_id={search_run_id}"

    def all_isins(self) -> Path:
        return self.root / "reference" / "all_isins" / "all_isins.parquet"

    def all_isins_manifest(self) -> Path:
        return self.root / "reference" / "all_isins" / "manifest.json"

    def metadata_filter_run(self, selection_id: str) -> Path:
        return self.silver / "metadata_filter" / f"selection_id={selection_id}"

    def metadata_filter_isins(self, selection_id: str) -> Path:
        return self.metadata_filter_run(selection_id) / "isins.parquet"

    def metadata_filter_manifest(self, selection_id: str) -> Path:
        return self.metadata_filter_run(selection_id) / "manifest.json"

    def current_metadata_filter_selection(self) -> Path:
        return self.silver / "metadata_filter" / "current_selection.json"

    def univariate_filter_run(self, selection_id: str) -> Path:
        return self.silver / "univariate_filter" / f"selection_id={selection_id}"

    def univariate_filter_isins(self, selection_id: str) -> Path:
        return self.univariate_filter_run(selection_id) / "isins.parquet"

    def univariate_filter_manifest(self, selection_id: str) -> Path:
        return self.univariate_filter_run(selection_id) / "manifest.json"

    def current_univariate_filter_selection(self) -> Path:
        return self.silver / "univariate_filter" / "current_selection.json"

    def selection_statistics_view(self, source_module: str, selection_id: str) -> Path:
        return self.silver / source_module / f"selection_id={selection_id}" / "statistics_view.json"

    def canonical_universe(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "canonical_universe.parquet"

    def candidates(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "candidates.parquet"

    def search_summary(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "search_summary.json"

    def review_csv(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "canonical_universe_review.csv"

    def bronze_plan(self, run_id: str) -> Path:
        return self.silver / "plans" / "bronze_plans" / f"{run_id}.parquet"

    def bronze_quote_file(self, exchange: str, year: int, isin: str) -> Path:
        return self.bronze / "quotes" / exchange / str(year) / f"{isin}.parquet"

    def bronze_dataset_file(self, dataset: str, exchange: str, year: int, isin: str) -> Path:
        return self.bronze / dataset / exchange / str(year) / f"{isin}.parquet"

    def silver_quote_file(self, exchange: str, isin: str) -> Path:
        return self.silver / "quotes" / exchange / f"{isin}.parquet"

    def bronze_runs(self) -> Path:
        return self.silver / "runs" / "bronze_runs.parquet"

    def coverage(self) -> Path:
        return self.silver / "coverage" / "coverage.parquet"

    def quote_gaps(self) -> Path:
        return self.silver / "coverage" / "quote_gaps.parquet"

    def dry_run_summary(self) -> Path:
        return self.silver / "runs" / "dry_run_summary.json"

    def job_manifest(self, job_type: str, run_id: str) -> Path:
        return self.silver / "runs" / "jobs" / job_type / f"{run_id}.json"

    def gold_runs(self) -> Path:
        return self.gold / "runs" / "gold_runs.parquet"

    def gold_returns(self, exchange: str, isin: str) -> Path:
        return self.gold / "returns" / exchange / f"{isin}.parquet"

    def gold_univariate_statistics(self, exchange: str, isin: str) -> Path:
        return self.gold / "univariate_statistics" / exchange / f"{isin}.parquet"

    def gold_correlation(self, exchange: str, isin: str) -> Path:
        return self.gold / "correlation" / exchange / f"{isin}.parquet"

    def gold_covariance(self, exchange: str, isin: str) -> Path:
        return self.gold / "covariance" / exchange / f"{isin}.parquet"

    def gold_bivariate_statistics_pair(
        self,
        left_exchange: str,
        left_isin: str,
        left_code: str,
        right_exchange: str,
        right_isin: str,
        right_code: str,
    ) -> Path:
        pair_file = f"{right_exchange}__{right_isin}__{right_code}.parquet"
        return (
            self.gold / "bivariate_statistics" / left_exchange / left_isin / left_code / pair_file
        )

    def gold_bivariate_statistics_bucket(self, version: str, bucket: int) -> Path:
        return (
            self.gold
            / "bivariate_statistics"
            / f"version={version}"
            / f"bucket={bucket:03d}.parquet"
        )

    def gold_correlation_edges(self, version: str, metric: str, bucket: int) -> Path:
        return (
            self.gold
            / "correlation_edges"
            / f"version={version}"
            / f"metric={metric}"
            / f"bucket={bucket:03d}.parquet"
        )

    def gold_asset_features(self, exchange: str, isin: str) -> Path:
        return self.gold / "features" / exchange / f"{isin}.parquet"

    def gold_return_matrix(self, evaluation_id: str) -> Path:
        return self.gold / "evaluation" / "return_matrices" / f"{evaluation_id}.parquet"

    def gold_asset_metrics(self, evaluation_id: str) -> Path:
        return self.gold / "evaluation" / "asset_metrics" / f"{evaluation_id}.parquet"

    def gold_portfolio_returns(self, evaluation_id: str) -> Path:
        return self.gold / "evaluation" / "portfolio_returns" / f"{evaluation_id}.parquet"

    def gold_drawdowns(self, evaluation_id: str, portfolio_id: str) -> Path:
        return self.gold / "evaluation" / "drawdowns" / evaluation_id / f"{portfolio_id}.parquet"

    def gold_portfolio_metrics(self, evaluation_id: str) -> Path:
        return self.gold / "evaluation" / "portfolio_metrics" / f"{evaluation_id}.parquet"

    def gold_frontier_points(self, evaluation_id: str) -> Path:
        return self.gold / "evaluation" / "frontier_points" / f"{evaluation_id}.parquet"

    def gold_frontier_weights(self, evaluation_id: str) -> Path:
        return self.gold / "evaluation" / "frontier_weights" / f"{evaluation_id}.parquet"

    def gold_backtests(self, run_id: str) -> Path:
        return self.gold / "evaluation" / "backtests" / f"{run_id}.parquet"

    def gold_backtest_weights(self, run_id: str) -> Path:
        return self.gold / "evaluation" / "backtest_weights" / f"{run_id}.parquet"

    def gold_rebalance_events(self, run_id: str) -> Path:
        return self.gold / "evaluation" / "rebalance_events" / f"{run_id}.parquet"

    def gold_rebalance_weights(self, run_id: str) -> Path:
        return self.gold / "evaluation" / "rebalance_weights" / f"{run_id}.parquet"

    def gold_tail_risk(self, run_id: str) -> Path:
        return self.gold / "evaluation" / "tail_risk" / f"{run_id}.parquet"

    def gold_optimized_weights(self, objective: str, evaluation_id: str) -> Path:
        return self.gold / "weights" / objective / f"{evaluation_id}.parquet"

    def gold_risk_contributions(self, objective: str, evaluation_id: str) -> Path:
        return self.gold / "risk_contributions" / objective / f"{evaluation_id}.parquet"

    def gold_hrp_clusters(self, evaluation_id: str) -> Path:
        return self.gold / "clusters" / "hierarchical_risk_parity" / f"{evaluation_id}.parquet"

    def gold_hrp_linkage(self, evaluation_id: str) -> Path:
        return (
            self.gold / "clusters" / "hierarchical_risk_parity_linkage" / f"{evaluation_id}.parquet"
        )

    def gold_diversification_metrics(self, evaluation_id: str) -> Path:
        return self.gold / "metrics" / "maximum_diversification" / f"{evaluation_id}.parquet"

    def trading_flatex_export(self, evaluation_id: str, portfolio_id: str) -> Path:
        return self.root / "trading" / "flatex" / f"{evaluation_id}-{portfolio_id}.csv"

    def current_universe(self) -> Path:
        return self.silver / "universe" / "current_universe.json"
