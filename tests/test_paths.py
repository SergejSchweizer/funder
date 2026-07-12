from pathlib import Path

from funder.paths import LakePaths


def test_lake_paths_are_deterministic() -> None:
    paths = LakePaths(root=Path("lake"))

    assert paths.bronze == Path("lake/bronze")
    assert paths.silver == Path("lake/silver")
    assert paths.gold == Path("lake/gold")
    assert paths.meta == Path("lake/meta")
    assert paths.bronze_search_run("2026-07-12") == Path(
        "lake/bronze/eodhd/search/run_date=2026-07-12"
    )
    assert paths.canonical_universe("search-1") == Path(
        "lake/silver/search/search_run_id=search-1/canonical_universe.parquet"
    )
