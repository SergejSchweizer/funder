"""Deterministic lake paths shared by modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LakePaths:
    """Simple Bronze/Silver/Gold/Meta lake path contract."""

    root: Path = Path("data")

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
    def meta(self) -> Path:
        return self.root / "meta"

    def bronze_search_run(self, run_date: str) -> Path:
        return self.bronze / "eodhd" / "search" / f"run_date={run_date}"

    def silver_search_run(self, search_run_id: str) -> Path:
        return self.silver / "search" / f"search_run_id={search_run_id}"

    def canonical_universe(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "canonical_universe.parquet"

    def candidates(self, search_run_id: str) -> Path:
        return self.silver_search_run(search_run_id) / "candidates.parquet"

    def current_universe(self) -> Path:
        return self.meta / "current_universe.json"
