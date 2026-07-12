from datetime import UTC, date, datetime

import pytest

from founder.fetch import (
    build_coverage,
    build_fetch_plan,
    fetch_fundamentals_to_silver,
    fetch_quotes_to_bronze,
    normalize_quote_rows,
    write_fetch_manifests,
    write_silver_quotes,
)
from founder.gold import build_correlation_and_covariance, build_returns, write_gold_inputs
from founder.paths import LakePaths
from founder.pipeline import run_dry_run
from founder.schemas import required_fields, validate_fields
from founder.search import (
    approve_universe,
    resolve_current_universe,
    select_canonical,
    write_canonical_universe,
    write_search_run,
)
from founder.table_io import read_json, read_rows


def test_lake_schemas_and_paths_cover_backlog_tables(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")

    assert "isin" in required_fields("canonical_universe")
    validate_fields("coverage", {field: "value" for field in required_fields("coverage")})
    assert paths.fetch_plan("fetch-1").as_posix().endswith("data") is False
    assert paths.search_summary("search-1").name == "search_summary.json"
    assert paths.review_csv("search-1").name == "canonical_universe_review.csv"
    assert paths.silver_quotes_year(2026).as_posix().endswith("year=2026/quotes.parquet")
    assert paths.gold_covariance("2026-07-12").as_posix().endswith("covariance.parquet")

    with pytest.raises(ValueError, match="unknown schema"):
        required_fields("unknown")


def test_search_writes_candidates_selects_canonical_and_approves_universe(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    raw = [
        {
            "Code": "LSE1",
            "Exchange": "LSE",
            "Type": "ETF",
            "Country": "UK",
            "Currency": "GBP",
            "Isin": "IE1",
            "Name": "Fund A",
        },
        {
            "Code": "XET1",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Isin": "IE1",
            "Name": "Fund A",
        },
        {
            "Code": "MISS",
            "Exchange": "XETRA",
            "Type": "ETF",
            "Country": "DE",
            "Currency": "EUR",
            "Name": "Missing ISIN",
        },
        {
            "Code": "AMS1",
            "Exchange": "AS",
            "Type": "ETF",
            "Country": "NL",
            "Currency": "EUR",
            "Isin": "IE2",
            "Name": "Fund B",
        },
    ]

    candidates = write_search_run(
        raw,
        paths=paths,
        search_run_id="search-1",
        run_date=date(2026, 7, 12),
        found_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    canonical = write_canonical_universe(paths, "search-1")
    pointer = approve_universe(paths, "search-1")

    assert len(candidates) == 4
    assert [row["isin"] for row in canonical] == ["IE1", "IE2"]
    assert canonical[0]["exchange"] == "XETRA"
    assert canonical[1]["selection_reason"] == "fallback_exchange"
    assert read_json(paths.search_summary("search-1"))["missing_isin_rows"] == 1
    assert resolve_current_universe(paths).as_posix() == pointer["canonical_universe_path"]


def test_fetch_plan_quotes_fundamentals_and_coverage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    canonical = select_canonical(
        [
            {
                "search_run_id": "search-1",
                "isin": "IE1",
                "code": "AAA",
                "exchange": "XETRA",
                "instrument_type": "ETF",
                "country": "DE",
                "currency": "EUR",
                "name": "A",
                "normalized_name": "a",
            },
            {
                "search_run_id": "search-1",
                "isin": "IE2",
                "code": "BBB",
                "exchange": "AS",
                "instrument_type": "ETF",
                "country": "NL",
                "currency": "EUR",
                "name": "B",
                "normalized_name": "b",
            },
        ]
    )
    plan = build_fetch_plan(
        canonical, run_id="fetch-1", start_date=date(2026, 7, 10), end_date=date(2026, 7, 12)
    )

    assert plan[0]["symbol"] == "AAA.XETRA"
    with pytest.raises(ValueError, match="duplicate ISIN"):
        build_fetch_plan(
            [canonical[0], canonical[0]],
            run_id="bad",
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 12),
        )

    successes, errors = fetch_quotes_to_bronze(
        paths,
        plan,
        run_date=date(2026, 7, 12),
        fetcher=lambda item: (
            (_ for _ in ()).throw(RuntimeError("offline"))
            if item["code"] == "BBB"
            else [{"date": "2026-07-10", "close": 100, "adjusted_close": 100}]
        ),
    )
    assert successes[0]["rows"] == 1
    assert errors[0]["message"] == "offline"

    raw_by_symbol = {
        "AAA.XETRA": [
            {"date": "2026-07-10", "close": 100, "adjusted_close": 100},
            {"date": "2026-07-12", "close": 110, "adjusted_close": 110},
        ],
        "BBB.AS": [{"date": "2026-07-10", "close": 50, "adjusted_close": 50}],
    }
    quotes = normalize_quote_rows(
        plan,
        raw_by_symbol,
        fetched_at=datetime(2026, 7, 12, tzinfo=UTC),
        currency_by_isin={"IE1": "EUR", "IE2": "EUR"},
    )
    write_silver_quotes(paths, quotes)
    profiles = fetch_fundamentals_to_silver(
        paths,
        plan,
        run_date=date(2026, 7, 12),
        fetcher=lambda item: {"General": {"Name": item["code"], "CurrencyCode": "EUR"}},
    )
    coverage = write_fetch_manifests(paths, run_id="fetch-1", quote_rows=quotes)

    assert read_rows(paths.silver_quotes_year(2026)) == quotes
    assert profiles[0]["name"] == "AAA"
    assert build_coverage(quotes, run_id="fetch-1")[0]["missing_periods"] == 1
    assert read_rows(paths.coverage()) == coverage


def test_gold_inputs_are_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    quotes = [
        {"isin": "IE1", "date": "2026-07-10", "adjusted_close": 100},
        {"isin": "IE1", "date": "2026-07-11", "adjusted_close": 110},
        {"isin": "IE2", "date": "2026-07-10", "adjusted_close": 50},
        {"isin": "IE2", "date": "2026-07-11", "adjusted_close": 55},
    ]

    returns = build_returns(quotes)
    correlations, covariances = build_correlation_and_covariance(returns)
    written_returns, written_correlations, written_covariances = write_gold_inputs(
        paths, quotes, as_of="2026-07-12"
    )

    assert returns[0]["return"] == pytest.approx(0.1)
    assert correlations == written_correlations
    assert covariances == written_covariances
    assert read_rows(paths.gold_returns("2026-07-12")) == written_returns


def test_dry_run_pipeline_is_repeatable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = run_dry_run(tmp_path / "lake")
    second = run_dry_run(tmp_path / "lake")

    assert first == second
    assert first["canonical_rows"] == 2
    assert first["quote_rows"] == 6
