"""Tests for PR75 multivariate selection-cache consumption."""

from __future__ import annotations

from pathlib import Path

from camovar.multivariate_statistics import (
    MultivariateStatisticsConfig,
    write_multivariate_statistics,
)
from camovar.paths import LakePaths
from camovar.portfolio import PortfolioConstraints
from camovar.table_io import read_rows, write_rows


def _quote(
    isin: str, exchange: str, code: str, date: str, adjusted_close: float
) -> dict[str, object]:
    return {
        "run_id": "bronze-1",
        "isin": isin,
        "code": code,
        "exchange": exchange,
        "date": date,
        "open": adjusted_close,
        "high": adjusted_close,
        "low": adjusted_close,
        "close": adjusted_close,
        "adjusted_close": adjusted_close,
        "volume": 100,
        "currency": "EUR",
        "bronzed_at": "2026-01-06T00:00:00+00:00",
    }


def _write_quotes(paths: LakePaths) -> None:
    for isin, exchange, code, prices in (
        ("IE1", "XETRA", "AAA", (100.0, 101.0, 102.0, 103.0, 104.0, 105.0)),
        ("IE2", "AS", "BBB", (100.0, 99.0, 101.0, 104.0, 103.0, 106.0)),
        ("IE3", "PA", "CCC", (50.0, 51.0, 53.0, 54.0, 55.0, 56.0)),
    ):
        write_rows(
            paths.silver_quote_file(exchange, isin),
            [
                _quote(isin, exchange, code, f"2026-01-0{index}", close)
                for index, close in enumerate(prices, start=1)
            ],
        )


def _selection(
    selection_id: str, listings: tuple[tuple[str, str, str], ...]
) -> list[dict[str, object]]:
    return [
        {
            "selection_id": selection_id,
            "isin": isin,
            "exchange": exchange,
            "code": code,
            "name": "",
            "source_module": "univariate_filter",
        }
        for isin, exchange, code in listings
    ]


def _config(selection_id: str, evaluation_id: str) -> MultivariateStatisticsConfig:
    return MultivariateStatisticsConfig(
        evaluation_id=evaluation_id,
        portfolio_id_prefix=evaluation_id,
        confidence_level=0.75,
        grid_step=0.5,
        train_window=2,
        test_window=1,
        constraints=PortfolioConstraints(max_weight=1.0),
        concurrency=1,
        selection_id=selection_id,
        use_selection_statistics_cache=True,
    )


def test_multivariate_statistics_reuses_unchanged_selection_portfolio_run(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    _write_quotes(paths)
    selected_rows = _selection("sel-two", (("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")))

    first = write_multivariate_statistics(
        paths, selected_rows, config=_config("sel-two", "eval-cache")
    )
    second = write_multivariate_statistics(
        paths, selected_rows, config=_config("sel-two", "eval-cache")
    )

    assert first["cache_status"] == "prepared"
    assert second["cache_status"] == "portfolio_reused"
    assert second["portfolio_run_id"]
    assert {row["isin"] for row in read_rows(paths.gold_return_matrix("eval-cache"))} == {
        "IE1",
        "IE2",
    }
    assert read_rows(paths.gold_optimized_weights("minimum_variance", "eval-cache"))
    assert read_rows(paths.gold_tail_risk("eval-cache-tail-risk"))


def test_multivariate_statistics_expanded_selection_adds_only_selected_inputs(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    _write_quotes(paths)
    first_selection = _selection("sel-two", (("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB")))
    expanded_selection = _selection(
        "sel-three",
        (("IE1", "XETRA", "AAA"), ("IE2", "AS", "BBB"), ("IE3", "PA", "CCC")),
    )

    write_multivariate_statistics(paths, first_selection, config=_config("sel-two", "eval-two"))
    expanded = write_multivariate_statistics(
        paths, expanded_selection, config=_config("sel-three", "eval-three")
    )

    assert expanded["selected_listing_count"] == 3
    assert expanded["selection_statistics_pair_count"] == 3
    assert {row["isin"] for row in read_rows(paths.gold_return_matrix("eval-three"))} == {
        "IE1",
        "IE2",
        "IE3",
    }
    assert read_rows(paths.gold_returns("XETRA", "IE1"))
    assert read_rows(paths.gold_returns("AS", "IE2"))
    assert read_rows(paths.gold_returns("PA", "IE3"))
