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
        return self.silver / "metadata"

    def bronze_search_run(self, run_date: str) -> Path:
        return self.bronze / "eodhd" / "search" / f"run_date={run_date}"

    def silver_search_run(self, search_run_id: str) -> Path:
        return self.silver / "search" / f"search_run_id={search_run_id}"

    def canonical_universe(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "canonical_universe.parquet"

    def candidates(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "candidates.parquet"

    def search_summary(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "search_summary.json"

    def review_csv(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "canonical_universe_review.csv"

    def fetch_plan(self, run_id: str) -> Path:
        return self.metadata / "fetch_plans" / f"{run_id}.parquet"

    def bronze_quote_file(self, exchange: str, year: int, isin: str) -> Path:
        return self.bronze / "quotes" / exchange / str(year) / f"{isin}.parquet"

    def bronze_dataset_file(self, dataset: str, exchange: str, year: int, isin: str) -> Path:
        return self.bronze / dataset / exchange / str(year) / f"{isin}.parquet"

    def silver_quotes_year(self, year: int) -> Path:
        return self.silver / "quotes" / f"year={year}" / "quotes.parquet"

    def fetch_runs(self) -> Path:
        return self.metadata / "fetch_runs.parquet"

    def coverage(self) -> Path:
        return self.silver / "coverage" / "coverage.parquet"

    def quote_gaps(self) -> Path:
        return self.silver / "coverage" / "quote_gaps.parquet"

    def dry_run_summary(self) -> Path:
        return self.metadata / "dry_run_summary.json"

    def gold_returns(self, as_of: str) -> Path:
        return self.gold / "returns" / f"as_of={as_of}" / "returns.parquet"

    def gold_correlation(self, as_of: str) -> Path:
        return self.gold / "correlation" / f"as_of={as_of}" / "correlation.parquet"

    def gold_covariance(self, as_of: str) -> Path:
        return self.gold / "covariance" / f"as_of={as_of}" / "covariance.parquet"

    def current_universe(self) -> Path:
        return self.metadata / "current_universe.json"
