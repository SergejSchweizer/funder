"""Tests for PR74's selection statistics views."""

from pathlib import Path

import pytest

from camovar.bivariate_statistics import write_bivariate_statistics
from camovar.paths import LakePaths
from camovar.statistics_views import (
    build_selection_statistics_view,
    read_selection_statistics,
    write_selection_statistics_view,
)
from camovar.table_io import read_json
from camovar.univariate_statistics import build_quote_returns, write_univariate_statistics


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
        "bronzed_at": "2026-01-04T00:00:00+00:00",
    }


_LISTINGS = [
    ("IE1", "XETRA", "AAA"),
    ("IE2", "AS", "BBB"),
    ("IE3", "PA", "CCC"),
]


def _quotes_for(isin: str, exchange: str, code: str) -> list[dict[str, object]]:
    prices = [100.0, 101.0, 99.0, 103.0, 104.0]
    return [
        _quote(isin, exchange, code, f"2026-01-0{index}", price)
        for index, price in enumerate(prices, start=1)
    ]


def _populate_cache(paths: LakePaths) -> list[dict[str, object]]:
    selected_rows: list[dict[str, object]] = []
    all_returns: list[dict[str, object]] = []
    for isin, exchange, code in _LISTINGS:
        quotes = _quotes_for(isin, exchange, code)
        write_univariate_statistics(paths, quotes, confidence_level=0.75)
        all_returns.extend(build_quote_returns(quotes))
        selected_rows.append({"isin": isin, "exchange": exchange, "code": code})
    write_bivariate_statistics(paths, all_returns, version="current")
    return selected_rows


def test_build_selection_statistics_view_reports_complete_when_cache_is_populated(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _populate_cache(paths)

    view = build_selection_statistics_view(
        paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
    )

    assert view["univariate_status"] == "complete"
    assert view["bivariate_status"] == "complete"
    assert view["present_univariate_count"] == 3
    assert view["present_bivariate_pair_count"] == 3  # C(3,2) with no same-ISIN pairs
    assert view["missing_univariate_listings"] == []
    assert view["missing_bivariate_pairs"] == []


def test_build_selection_statistics_view_reports_missing_rows_deterministically(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    # Only populate the cache for two of the three listings.
    selected_rows: list[dict[str, object]] = []
    all_returns: list[dict[str, object]] = []
    for isin, exchange, code in _LISTINGS[:2]:
        quotes = _quotes_for(isin, exchange, code)
        write_univariate_statistics(paths, quotes, confidence_level=0.75)
        all_returns.extend(build_quote_returns(quotes))
        selected_rows.append({"isin": isin, "exchange": exchange, "code": code})
    write_bivariate_statistics(paths, all_returns, version="current")
    # Selection references a third, never-computed listing.
    selected_rows.append({"isin": "IE3", "exchange": "PA", "code": "CCC"})

    view = build_selection_statistics_view(
        paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
    )

    assert view["univariate_status"] == "missing_rows"
    assert view["missing_univariate_listings"] == [{"isin": "IE3", "exchange": "PA", "code": "CCC"}]
    assert view["bivariate_status"] == "missing_rows"
    assert len(view["missing_bivariate_pairs"]) == 2


def test_build_selection_statistics_view_is_deterministic(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _populate_cache(paths)

    first = build_selection_statistics_view(
        paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
    )
    second = build_selection_statistics_view(
        paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
    )

    assert first == second
    assert first["view_id"] == second["view_id"]


def test_write_selection_statistics_view_persists_and_is_idempotent(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _populate_cache(paths)

    first = write_selection_statistics_view(
        paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
    )
    persisted = read_json(paths.selection_statistics_view("metadata_filter", "sel-1"))
    assert persisted == first

    second = write_selection_statistics_view(
        paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
    )
    assert second == first


def test_read_selection_statistics_returns_cached_rows_without_recomputing(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _populate_cache(paths)

    univariate_rows, bivariate_rows, view = read_selection_statistics(
        paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
    )

    assert len(univariate_rows) == 3
    assert len(bivariate_rows) == 3
    assert view["univariate_status"] == "complete"
    assert {row["isin"] for row in univariate_rows} == {"IE1", "IE2", "IE3"}


def test_read_selection_statistics_raises_when_cache_rows_are_missing(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    selected_rows = _populate_cache(paths)
    selected_rows.append({"isin": "IE4", "exchange": "MU", "code": "DDD"})

    with pytest.raises(ValueError, match="selection statistics incomplete"):
        read_selection_statistics(
            paths, selection_id="sel-1", source_module="metadata_filter", listing_rows=selected_rows
        )
