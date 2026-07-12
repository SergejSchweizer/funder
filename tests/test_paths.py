from pathlib import Path

from founder.paths import LakePaths


def test_lake_paths_are_deterministic() -> None:
    paths = LakePaths(root=Path("lake"))

    assert paths.bronze == Path("lake/bronze")
    assert paths.silver == Path("lake/silver")
    assert paths.gold == Path("lake/gold")
    assert paths.metadata == Path("lake/silver")
    assert paths.bronze_search_run("2026-07-12") == Path(
        "lake/bronze/eodhd/search/run_date=2026-07-12"
    )
    assert paths.canonical_universe("search-1") == Path(
        "lake/silver/search/search_run_id=search-1/canonical_universe.parquet"
    )
    assert paths.candidates("search-1") == Path(
        "lake/silver/search/search_run_id=search-1/candidates.parquet"
    )
    assert paths.bronze_quote_file("XETRA", 2026, "IE0000000001") == Path(
        "lake/bronze/quotes/XETRA/2026/IE0000000001.parquet"
    )
    assert paths.bronze_dataset_file("dividends", "XETRA", 2026, "IE0000000001") == Path(
        "lake/bronze/dividends/XETRA/2026/IE0000000001.parquet"
    )
    assert paths.silver_quote_file("XETRA", "IE0000000001") == Path(
        "lake/silver/quotes/XETRA/IE0000000001.parquet"
    )
    assert paths.gold_returns("XETRA", "IE0000000001") == Path(
        "lake/gold/returns/XETRA/IE0000000001.parquet"
    )
    assert paths.gold_correlation("XETRA", "IE0000000001") == Path(
        "lake/gold/correlation/XETRA/IE0000000001.parquet"
    )
    assert paths.gold_covariance("XETRA", "IE0000000001") == Path(
        "lake/gold/covariance/XETRA/IE0000000001.parquet"
    )
    assert paths.fetch_plan("fetch-1") == Path("lake/silver/plans/fetch_plans/fetch-1.parquet")
    assert paths.coverage() == Path("lake/silver/coverage/coverage.parquet")
    assert paths.quote_gaps() == Path("lake/silver/coverage/quote_gaps.parquet")
    assert paths.current_universe() == Path("lake/silver/universe/current_universe.json")
