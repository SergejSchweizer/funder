from pathlib import Path

import pytest

from founder.bivariate_statistics import (
    build_bivariate_statistics,
    read_legacy_bivariate_pair,
    resolve_worker_count,
    write_bivariate_statistics,
)
from founder.paths import LakePaths
from founder.run_state import read_job_manifest
from founder.table_io import read_rows, write_rows


def _return(isin: str, exchange: str, code: str, date: str, value: float) -> dict[str, object]:
    return {
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "date": date,
        "return": value,
    }


def test_bivariate_statistics_use_common_dates_and_pairwise_metrics(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    returns = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "XETRA", "AAA", "2026-01-02", 0.02),
        _return("IE1", "XETRA", "AAA", "2026-01-03", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-01", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-02", 0.02),
        _return("IE2", "AS", "BBB", "2026-01-03", 0.01),
        _return("IE3", "XETRA", "CCC", "2026-01-02", 0.10),
    ]

    statistics = build_bivariate_statistics(returns)
    written = write_bivariate_statistics(paths, returns, version="v1")

    assert len(statistics) == 3
    row = statistics[0]
    assert row["left_isin"] == "IE1"
    assert row["right_isin"] == "IE2"
    assert row["left_listing_key"] == "XETRA__IE1__AAA"
    assert row["right_listing_key"] == "AS__IE2__BBB"
    assert row["pair_key"] == "XETRA__IE1__AAA___AS__IE2__BBB"
    assert row["date_start"] == "2026-01-01"
    assert row["date_end"] == "2026-01-03"
    assert row["n_observations"] == 3
    assert row["pearson_correlation"] == pytest.approx(-1.0)
    assert row["covariance"] == pytest.approx(-0.0001)
    assert row["left_variance"] == pytest.approx(0.0001)
    assert row["right_variance"] == pytest.approx(0.0001)
    assert row["left_beta_to_right"] == pytest.approx(-1.0)
    assert row["right_beta_to_left"] == pytest.approx(-1.0)
    assert "spearman_correlation" in row
    assert {k: v for k, v in written[0].items() if k not in {"version", "bucket"}} == statistics[0]
    written_row = next(item for item in written if item["pair_key"] == row["pair_key"])
    assert written_row["version"] == "v1"
    assert written_row["bucket"] == written_row["left_id"] % 128
    bucket_path = paths.gold_bivariate_statistics_bucket("v1", int(written_row["bucket"]))
    assert any(item["pair_key"] == row["pair_key"] for item in read_rows(bucket_path))

    manifest = read_job_manifest(paths, "bivariate-statistics-plan", "v1")
    assert manifest["status"] == "completed"
    assert manifest["row_counts"]["listing_count"] == 3


def test_bivariate_statistics_reuses_cached_buckets_and_writes_delta(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    first_selection = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "XETRA", "AAA", "2026-01-02", 0.02),
        _return("IE2", "AS", "BBB", "2026-01-01", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-02", 0.02),
    ]
    first = write_bivariate_statistics(paths, first_selection, version="v1")
    bucket_path = paths.gold_bivariate_statistics_bucket("v1", int(first[0]["bucket"]))
    first_mtime = bucket_path.stat().st_mtime_ns

    expanded_selection = [
        *first_selection,
        _return("IE3", "PA", "CCC", "2026-01-01", 0.04),
        _return("IE3", "PA", "CCC", "2026-01-02", 0.05),
    ]
    expanded = write_bivariate_statistics(paths, expanded_selection, version="v1")

    assert len(first) == 1
    assert len(expanded) == 3
    new_pair = next(row for row in expanded if row["right_isin"] == "IE3")
    new_bucket_path = paths.gold_bivariate_statistics_bucket("v1", int(new_pair["bucket"]))
    if new_bucket_path == bucket_path:
        assert bucket_path.stat().st_mtime_ns != first_mtime
    else:
        assert bucket_path.stat().st_mtime_ns == first_mtime
    assert any(row["pair_key"] == new_pair["pair_key"] for row in read_rows(new_bucket_path))


def test_bivariate_statistics_rejects_universes_above_max_pair_count(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    returns = [_return(f"IE{i}", "XETRA", "AAA", "2026-01-01", 0.01) for i in range(40)]

    with pytest.raises(ValueError, match="exceeds max_pair_count"):
        write_bivariate_statistics(paths, returns, version="v1", max_pair_count=100)

    manifest = read_job_manifest(paths, "bivariate-statistics-plan", "v1")
    assert manifest["status"] == "failed"
    assert manifest["error_summary"][0]["reason"] is not None
    with pytest.raises(ValueError, match="exceeds max_pair_count"):
        build_bivariate_statistics(returns, max_pair_count=100)


def test_bivariate_statistics_discards_corrupt_bucket_cache(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    returns = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "XETRA", "AAA", "2026-01-02", 0.02),
        _return("IE2", "AS", "BBB", "2026-01-01", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-02", 0.02),
    ]
    first = write_bivariate_statistics(paths, returns, version="v1")
    bucket = int(first[0]["bucket"])
    bucket_path = paths.gold_bivariate_statistics_bucket("v1", bucket)
    corrupted_row = dict(first[0])
    corrupted_row["bucket"] = bucket + 1
    write_rows(bucket_path, [corrupted_row])

    rewritten = write_bivariate_statistics(paths, returns, version="v1")

    assert rewritten[0]["bucket"] == bucket
    assert read_rows(bucket_path)[0]["bucket"] == bucket


def test_bivariate_statistics_skip_same_isin_pairs_by_default() -> None:
    returns = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "AS", "BBB", "2026-01-01", 0.02),
    ]

    assert build_bivariate_statistics(returns) == []
    assert len(build_bivariate_statistics(returns, skip_same_isin=False)) == 1


def test_bivariate_statistics_parallel_matches_serial() -> None:
    returns = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "XETRA", "AAA", "2026-01-02", 0.02),
        _return("IE1", "XETRA", "AAA", "2026-01-03", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-01", 0.03),
        _return("IE2", "AS", "BBB", "2026-01-02", 0.02),
        _return("IE2", "AS", "BBB", "2026-01-03", 0.01),
        _return("IE3", "PA", "CCC", "2026-01-01", 0.02),
        _return("IE3", "PA", "CCC", "2026-01-02", 0.03),
        _return("IE3", "PA", "CCC", "2026-01-03", 0.04),
    ]

    serial = build_bivariate_statistics(returns, concurrency=1)
    parallel = build_bivariate_statistics(returns, concurrency=2)

    assert parallel == serial


def test_resolve_worker_count_caps_default_and_honors_explicit_concurrency() -> None:
    assert resolve_worker_count(1) == 1
    assert resolve_worker_count(None, max_workers=4) <= 4
    assert resolve_worker_count(None, max_workers=1) == 1


def test_read_legacy_bivariate_pair_reads_pre_bucketed_layout(tmp_path: Path) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    left = ("IE1", "XETRA", "AAA")
    right = ("IE2", "AS", "BBB")
    legacy_row = {"pair_key": "legacy", "left_isin": "IE1", "right_isin": "IE2"}
    write_rows(
        paths.gold_bivariate_statistics_pair("XETRA", "IE1", "AAA", "AS", "IE2", "BBB"),
        [legacy_row],
    )

    assert read_legacy_bivariate_pair(paths, left, right) == legacy_row
    assert read_legacy_bivariate_pair(paths, right, left) is None
