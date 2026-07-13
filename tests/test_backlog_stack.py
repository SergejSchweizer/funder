import csv
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from founder.bronze import (
    build_bronze_plan,
    build_coverage,
    build_gap_bronze_plan,
    build_quote_gap_rows,
    normalize_quote_rows,
    read_silver_quotes,
    write_bronze_manifests,
    write_quotes_to_bronze,
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
from founder.table_io import read_json, read_rows, write_rows


def test_lake_schemas_and_paths_cover_backlog_tables(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")

    assert "isin" in required_fields("canonical_universe")
    validate_fields("coverage", {field: "value" for field in required_fields("coverage")})
    assert paths.bronze_plan("bronze-1").as_posix().endswith("data") is False
    assert paths.search_summary("search-1").name == "search_summary.json"
    assert paths.review_csv("search-1").name == "canonical_universe_review.csv"
    assert (
        paths.silver_quote_file("XETRA", "IE1")
        .as_posix()
        .endswith("silver/quotes/XETRA/IE1.parquet")
    )
    assert (
        paths.gold_covariance("XETRA", "IE1")
        .as_posix()
        .endswith("gold/covariance/XETRA/IE1.parquet")
    )

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


def test_resolve_current_universe_fails_for_stale_pointer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    write_search_run(
        [
            {
                "Code": "XET1",
                "Exchange": "XETRA",
                "Type": "ETF",
                "Country": "DE",
                "Currency": "EUR",
                "Isin": "IE1",
                "Name": "Fund A",
            }
        ],
        paths=paths,
        search_run_id="search-1",
        run_date=date(2026, 7, 12),
        found_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    write_canonical_universe(paths, "search-1")
    approve_universe(paths, "search-1")
    paths.canonical_universe("search-1").unlink()

    with pytest.raises(FileNotFoundError, match="approved canonical universe does not exist"):
        resolve_current_universe(paths)


def test_search_ucits_etf_dataset_finds_expected_fund_counts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    dataset = Path("docs/eodhd_ucits_etf_matches.csv")

    with dataset.open(encoding="utf-8", newline="") as csv_file:
        raw = [row for row in csv.DictReader(csv_file) if "ucits etf" in row["name"].casefold()]

    candidates = write_search_run(
        raw,
        paths=paths,
        search_run_id="search-ucits-etf",
        query="UCITS ETF",
        run_date=date(2026, 7, 12),
        found_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    canonical = write_canonical_universe(paths, "search-ucits-etf")

    assert len(candidates) == 8_165
    assert len(canonical) == 3_104
    assert read_json(paths.search_summary("search-ucits-etf")) == {
        "candidate_rows": 8_165,
        "canonical_rows": 3_104,
        "missing_isin_rows": 1_505,
        "search_run_id": "search-ucits-etf",
    }


def test_bronze_plan_quotes_and_coverage(tmp_path) -> None:  # type: ignore[no-untyped-def]
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
    plan = build_bronze_plan(
        canonical, run_id="bronze-1", start_date=date(2026, 7, 10), end_date=date(2026, 7, 12)
    )

    assert plan[0]["symbol"] == "AAA.XETRA"
    with pytest.raises(ValueError, match="duplicate ISIN"):
        build_bronze_plan(
            [canonical[0], canonical[0]],
            run_id="bad",
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 12),
        )

    successes, errors = write_quotes_to_bronze(
        paths,
        plan,
        run_date=date(2026, 7, 12),
        loader=lambda item: (
            (_ for _ in ()).throw(RuntimeError("offline"))
            if item["code"] == "BBB"
            else [{"date": "2026-07-10", "close": 100, "adjusted_close": 100}]
        ),
    )
    assert successes[0]["rows"] == 1
    assert errors[0]["message"] == "offline"
    assert read_rows(paths.bronze_quote_file("XETRA", 2026, "IE1"))[0]["symbol"] == "AAA.XETRA"
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
        bronzed_at=datetime(2026, 7, 12, tzinfo=UTC),
        currency_by_isin={"IE1": "EUR", "IE2": "EUR"},
    )
    write_silver_quotes(paths, quotes)
    coverage = write_bronze_manifests(paths, run_id="bronze-1", quote_rows=quotes)

    assert read_rows(paths.silver_quote_file("XETRA", "IE1")) == quotes[:2]
    assert read_rows(paths.silver_quote_file("AS", "IE2")) == quotes[2:]
    assert build_coverage(quotes, run_id="bronze-1")[0]["missing_periods"] == 1
    assert read_rows(paths.coverage()) == coverage


def test_bronze_plan_accepts_existing_bronze_selection_field(tmp_path) -> None:  # type: ignore[no-untyped-def]
    plan = build_bronze_plan(
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
                "selection_reason": "preferred_xetra",
                "selected_for_bronze": True,
            }
        ],
        run_id="bronze-1",
        start_date=None,
        end_date=None,
    )

    assert plan[0]["symbol"] == "AAA.XETRA"


def test_gap_plan_and_quote_writes_preserve_existing_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    plan = build_bronze_plan(
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
                "selection_reason": "preferred_exchange",
                "selected_for_bronze": True,
            }
        ],
        run_id="bronze-2",
        start_date=None,
        end_date=date(2026, 7, 13),
    )
    first_quotes = normalize_quote_rows(
        plan,
        {"AAA.XETRA": [{"date": "2026-07-01", "close": 100, "adjusted_close": 100}]},
        bronzed_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    gap_plan = build_gap_bronze_plan(plan, first_quotes, end_date=date(2026, 7, 13))

    assert [(row["window_reason"], row["start_date"], row["end_date"]) for row in gap_plan] == [
        ("tail", "2026-07-02", "2026-07-13")
    ]

    delta_quotes = normalize_quote_rows(
        gap_plan,
        {"AAA.XETRA": [{"date": "2026-07-13", "close": 101, "adjusted_close": 101}]},
        bronzed_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    write_silver_quotes(paths, first_quotes)
    write_silver_quotes(paths, delta_quotes)

    accumulated = read_silver_quotes(paths)
    assert [row["date"] for row in accumulated] == ["2026-07-01", "2026-07-13"]
    coverage = write_bronze_manifests(paths, run_id="bronze-2", quote_rows=accumulated)
    assert coverage[0]["first_quote_date"] == "2026-07-01"
    assert coverage[0]["last_quote_date"] == "2026-07-13"


def test_gap_bronze_plan_backfills_holes_before_tail_windows() -> None:
    plan = [
        {
            "run_id": "bronze-2",
            "isin": "IE1",
            "code": "AAA",
            "exchange": "XETRA",
            "symbol": "AAA.XETRA",
            "start_date": "",
            "end_date": "2026-07-17",
        }
    ]
    quotes = [
        {"isin": "IE1", "code": "AAA", "exchange": "XETRA", "date": "2026-07-10"},
        {"isin": "IE1", "code": "AAA", "exchange": "XETRA", "date": "2026-07-14"},
    ]

    gaps = build_quote_gap_rows(plan, quotes, run_id="bronze-2", as_of=date(2026, 7, 17))
    gap_plan = build_gap_bronze_plan(plan, quotes, end_date=date(2026, 7, 17))

    assert [(row["gap_type"], row["gap_start"], row["gap_end"]) for row in gaps] == [
        ("historical_gap", "2026-07-13", "2026-07-13"),
        ("tail", "2026-07-15", "2026-07-17"),
    ]
    assert [(row["window_reason"], row["start_date"], row["end_date"]) for row in gap_plan] == [
        ("gap_backfill", "2026-07-13", "2026-07-17"),
    ]


def test_gold_inputs_are_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    quotes = [
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-10",
            "adjusted_close": 100,
        },
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-11",
            "adjusted_close": 110,
        },
        {
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "date": "2026-07-10",
            "adjusted_close": 50,
        },
        {
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "date": "2026-07-11",
            "adjusted_close": 55,
        },
    ]

    returns = build_returns(quotes)
    correlations, covariances = build_correlation_and_covariance(returns)
    written_returns, written_correlations, written_covariances, written_features = (
        write_gold_inputs(paths, quotes, concurrency=2)
    )

    assert returns[0]["return"] == pytest.approx(0.1)
    assert correlations == written_correlations
    assert covariances == written_covariances
    assert written_features[0]["total_return"] == pytest.approx(0.1)
    assert written_features[0]["max_drawdown"] == 0.0
    assert read_rows(paths.gold_returns("XETRA", "IE1")) == written_returns[:1]
    assert read_rows(paths.gold_correlation("XETRA", "IE1")) == written_correlations[:2]
    assert read_rows(paths.gold_covariance("XETRA", "IE1")) == written_covariances[:2]
    assert read_rows(paths.gold_asset_features("XETRA", "IE1")) == written_features[:1]
    assert read_rows(paths.gold_runs())[0]["input_last_quote_date"] == "2026-07-11"
    assert read_rows(paths.gold_runs())[0]["input_snapshot_date"] == "2026-07-11"
    assert read_rows(paths.gold_runs())[0]["input_listing_count"] == 2


def test_gold_inputs_resume_completed_listings_by_last_quote_date(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    quotes = [
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-10",
            "adjusted_close": 100,
        },
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-11",
            "adjusted_close": 110,
        },
    ]

    first = write_gold_inputs(paths, quotes, concurrency=1)
    stale_feature = [{**first[3][0], "total_return": 99.0}]
    write_rows(paths.gold_asset_features("XETRA", "IE1"), stale_feature)
    second = write_gold_inputs(paths, quotes, concurrency=1)

    assert second[3] == stale_feature
    assert read_rows(paths.gold_asset_features("XETRA", "IE1")) == stale_feature


def test_dry_run_pipeline_is_repeatable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = run_dry_run(tmp_path / "lake")
    second = run_dry_run(tmp_path / "lake")

    assert first == second
    assert first["canonical_rows"] == 2
    assert first["quote_rows"] == 6
