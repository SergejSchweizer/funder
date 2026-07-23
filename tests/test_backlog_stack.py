import csv
from datetime import UTC, date, datetime
from math import log
from pathlib import Path

import pytest

from camovar.bronze import (
    build_bronze_plan,
    build_coverage,
    build_gap_bronze_plan,
    build_quote_gap_rows,
    normalize_quote_rows,
    read_silver_quotes,
    write_bronze_manifests,
    write_quotes_to_bronze,
)
from camovar.gold import (
    build_correlation_and_covariance,
    build_correlation_edges,
    build_returns,
    write_correlation_edges,
    write_gold_inputs,
)
from camovar.paths import LakePaths
from camovar.pipeline import run_dry_run
from camovar.schemas import dataset_contract, required_fields, validate_fields, validate_rows
from camovar.search import (
    approve_universe,
    resolve_current_universe,
    select_canonical,
    write_canonical_universe,
    write_search_run,
)
from camovar.silver import write_silver_quotes
from camovar.table_io import read_json, read_rows, write_rows


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


def test_dataset_contract_registry_preserves_required_fields() -> None:
    contract = dataset_contract("returns")

    assert contract.name == "returns"
    assert contract.owner == "gold"
    assert contract.version == 1
    assert contract.required_fields == required_fields("returns")
    assert contract.sort_key == ("isin", "exchange", "code", "date")
    validate_rows("returns", [{field: "value" for field in required_fields("returns")}])
    with pytest.raises(ValueError, match="unknown dataset contract"):
        dataset_contract("missing")


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

    assert returns[0]["return"] == pytest.approx(log(110 / 100))
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


def test_gold_returns_use_adjusted_close_log_returns() -> None:
    returns = build_returns(
        [
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
                "adjusted_close": 0,
            },
            {
                "isin": "IE2",
                "exchange": "AS",
                "code": "BBB",
                "date": "2026-07-11",
                "adjusted_close": 50,
            },
        ]
    )

    assert [row["return"] for row in returns] == [pytest.approx(log(110 / 100))]
    assert all(row["isin"] == "IE1" for row in returns)
    assert returns[0]["simple_return"] == pytest.approx(0.10)


def test_gold_correlation_edges_store_upper_triangle_by_bucket(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-10", "return": 0.01},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-11", "return": 0.02},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-12", "return": 0.03},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-10", "return": 0.03},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-11", "return": 0.02},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-12", "return": 0.01},
    ]

    edges = build_correlation_edges(return_rows, version="snapshot-1", top_k_per_left=1)
    written = write_correlation_edges(
        paths,
        return_rows,
        version="snapshot-1",
        min_abs_correlation=0.5,
        top_k_per_left=1,
        bucket_count=2,
    )

    assert [(row["left_isin"], row["right_isin"]) for row in edges] == [("IE1", "IE2")]
    assert written[0]["version"] == "snapshot-1"
    assert written[0]["metric"] == "pearson"
    assert written[0]["left_id"] < written[0]["right_id"]
    assert written[0]["date_start"] == "2026-07-10"
    assert written[0]["date_end"] == "2026-07-12"
    assert written[0]["n_observations"] == 3
    assert written[0]["value"] == pytest.approx(-1.0)
    assert read_rows(paths.gold_correlation_edges("snapshot-1", "pearson", 0)) == written


def test_gold_correlation_edges_skip_same_isin_across_listings() -> None:
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-10", "return": 0.01},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-11", "return": 0.02},
        {"isin": "IE1", "exchange": "AS", "code": "AAA2", "date": "2026-07-10", "return": 0.01},
        {"isin": "IE1", "exchange": "AS", "code": "AAA2", "date": "2026-07-11", "return": 0.02},
        {"isin": "IE2", "exchange": "LSE", "code": "BBB", "date": "2026-07-10", "return": 0.02},
        {"isin": "IE2", "exchange": "LSE", "code": "BBB", "date": "2026-07-11", "return": 0.01},
    ]

    edges = build_correlation_edges(return_rows, version="snapshot-1", metric="pearson")

    assert {(row["left_isin"], row["right_isin"]) for row in edges} == {("IE1", "IE2")}
    assert all(row["left_isin"] != row["right_isin"] for row in edges)


def test_gold_pearson_correlation_uses_incremental_calculation() -> None:
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-10", "return": 1e9},
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-11",
            "return": 1e9 + 1,
        },
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-12",
            "return": 1e9 + 2,
        },
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-10", "return": 2e9},
        {
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "date": "2026-07-11",
            "return": 2e9 + 2,
        },
        {
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "date": "2026-07-12",
            "return": 2e9 + 4,
        },
    ]

    correlations, _ = build_correlation_and_covariance(return_rows)
    edges = build_correlation_edges(return_rows, version="snapshot-1", metric="pearson")

    assert edges[0]["value"] == pytest.approx(1.0)
    assert [
        row["correlation"]
        for row in correlations
        if row["left_isin"] == "IE1" and row["right_isin"] == "IE2"
    ] == [pytest.approx(1.0)]


def test_gold_covariance_uses_online_calculation() -> None:
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-10", "return": 1e12},
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-11",
            "return": 1e12 + 1,
        },
        {
            "isin": "IE1",
            "exchange": "XETRA",
            "code": "AAA",
            "date": "2026-07-12",
            "return": 1e12 + 2,
        },
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-10", "return": 2e12},
        {
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "date": "2026-07-11",
            "return": 2e12 + 2,
        },
        {
            "isin": "IE2",
            "exchange": "AS",
            "code": "BBB",
            "date": "2026-07-12",
            "return": 2e12 + 4,
        },
    ]

    _, covariances = build_correlation_and_covariance(return_rows)

    assert [
        row["covariance"]
        for row in covariances
        if row["left_isin"] == "IE1" and row["right_isin"] == "IE2"
    ] == [pytest.approx(2.0)]


def test_gold_correlations_use_common_date_intersection_only() -> None:
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-09", "return": 999.0},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-10", "return": 1.0},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-11", "return": 2.0},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-12", "return": 3.0},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-10", "return": 3.0},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-11", "return": 2.0},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-12", "return": 1.0},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-13", "return": -999.0},
    ]

    correlations, covariances = build_correlation_and_covariance(return_rows)
    pearson_edges = build_correlation_edges(return_rows, version="snapshot-1", metric="pearson")
    spearman_edges = build_correlation_edges(return_rows, version="snapshot-1", metric="spearman")

    pair_correlation = [
        row["correlation"]
        for row in correlations
        if row["left_isin"] == "IE1" and row["right_isin"] == "IE2"
    ]
    pair_covariance = [
        row["covariance"]
        for row in covariances
        if row["left_isin"] == "IE1" and row["right_isin"] == "IE2"
    ]
    assert pair_correlation == [pytest.approx(-1.0)]
    assert pair_covariance == [pytest.approx(-1.0)]
    assert pearson_edges[0]["date_start"] == "2026-07-10"
    assert pearson_edges[0]["date_end"] == "2026-07-12"
    assert pearson_edges[0]["n_observations"] == 3
    assert pearson_edges[0]["value"] == pytest.approx(-1.0)
    assert spearman_edges[0]["n_observations"] == 3


def test_gold_correlation_edges_support_spearman_metric(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    return_rows = [
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-10", "return": 1.0},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-11", "return": 2.0},
        {"isin": "IE1", "exchange": "XETRA", "code": "AAA", "date": "2026-07-12", "return": 3.0},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-10", "return": 1.0},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-11", "return": 4.0},
        {"isin": "IE2", "exchange": "AS", "code": "BBB", "date": "2026-07-12", "return": 9.0},
    ]

    pearson = build_correlation_edges(return_rows, version="snapshot-1", metric="pearson")
    spearman = write_correlation_edges(
        paths,
        return_rows,
        version="snapshot-1",
        metric="spearman",
        bucket_count=2,
    )

    assert pearson[0]["value"] == pytest.approx(0.989743318610787)
    assert spearman[0]["metric"] == "spearman"
    assert spearman[0]["value"] == pytest.approx(1.0)
    assert read_rows(paths.gold_correlation_edges("snapshot-1", "spearman", 0)) == spearman


def test_gold_spearman_correlation_uses_online_approximation() -> None:
    return_rows = []
    for index, (left_return, right_return) in enumerate(
        zip([1.0, 2.0, 3.0, 4.0, 100.0], [1.0, 4.0, 9.0, 16.0, 25.0], strict=True),
        start=1,
    ):
        return_rows.extend(
            [
                {
                    "isin": "IE1",
                    "exchange": "XETRA",
                    "code": "AAA",
                    "date": f"2026-07-{index:02d}",
                    "return": left_return,
                },
                {
                    "isin": "IE2",
                    "exchange": "AS",
                    "code": "BBB",
                    "date": f"2026-07-{index:02d}",
                    "return": right_return,
                },
            ]
        )

    spearman = build_correlation_edges(return_rows, version="snapshot-1", metric="spearman")

    assert spearman[0]["value"] == pytest.approx(0.3722369419746893)


def test_silver_writes_are_parallelized_by_listing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = LakePaths(root=tmp_path / "lake")
    rows = [
        {
            "run_id": "bronze-1",
            "isin": "IE1",
            "code": "AAA",
            "exchange": "XETRA",
            "date": "2026-07-10",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "adjusted_close": 100.0,
            "volume": 0,
            "currency": "EUR",
            "bronzed_at": "2026-07-10T00:00:00+00:00",
        },
        {
            "run_id": "bronze-1",
            "isin": "IE2",
            "code": "BBB",
            "exchange": "AS",
            "date": "2026-07-10",
            "open": 50.0,
            "high": 50.0,
            "low": 50.0,
            "close": 50.0,
            "adjusted_close": 50.0,
            "volume": 0,
            "currency": "EUR",
            "bronzed_at": "2026-07-10T00:00:00+00:00",
        },
    ]

    summary = write_silver_quotes(paths, rows, concurrency=2)

    assert summary == [
        {"exchange": "AS", "isin": "IE2", "rows": 1},
        {"exchange": "XETRA", "isin": "IE1", "rows": 1},
    ]
    assert read_rows(paths.silver_quote_file("XETRA", "IE1")) == [rows[0]]
    assert read_rows(paths.silver_quote_file("AS", "IE2")) == [rows[1]]


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
