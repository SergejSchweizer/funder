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
    assert paths.gold_correlation_edges("snapshot-1", "pearson", 7) == Path(
        "lake/gold/correlation_edges/version=snapshot-1/metric=pearson/bucket=007.parquet"
    )
    assert paths.gold_asset_features("XETRA", "IE0000000001") == Path(
        "lake/gold/features/XETRA/IE0000000001.parquet"
    )
    assert paths.gold_runs() == Path("lake/gold/runs/gold_runs.parquet")
    assert paths.gold_return_matrix("eval-1") == Path(
        "lake/gold/evaluation/return_matrices/eval-1.parquet"
    )
    assert paths.gold_asset_metrics("eval-1") == Path(
        "lake/gold/evaluation/asset_metrics/eval-1.parquet"
    )
    assert paths.gold_portfolio_returns("eval-1") == Path(
        "lake/gold/evaluation/portfolio_returns/eval-1.parquet"
    )
    assert paths.gold_drawdowns("eval-1", "equal-weight") == Path(
        "lake/gold/evaluation/drawdowns/eval-1/equal-weight.parquet"
    )
    assert paths.gold_portfolio_metrics("eval-1") == Path(
        "lake/gold/evaluation/portfolio_metrics/eval-1.parquet"
    )
    assert paths.gold_frontier_points("eval-1") == Path(
        "lake/gold/evaluation/frontier_points/eval-1.parquet"
    )
    assert paths.gold_frontier_weights("eval-1") == Path(
        "lake/gold/evaluation/frontier_weights/eval-1.parquet"
    )
    assert paths.gold_optimized_weights("minimum_variance", "eval-1") == Path(
        "lake/gold/weights/minimum_variance/eval-1.parquet"
    )
    assert paths.bronze_plan("bronze-1") == Path("lake/silver/plans/bronze_plans/bronze-1.parquet")
    assert paths.coverage() == Path("lake/silver/coverage/coverage.parquet")
    assert paths.quote_gaps() == Path("lake/silver/coverage/quote_gaps.parquet")
    assert paths.current_universe() == Path("lake/silver/universe/current_universe.json")
