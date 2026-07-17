"""Tests for the C03 pairwise scale-guard and bucketed-persistence primitives."""

from pathlib import Path

import pytest

from founder.bivariate_statistics import build_bivariate_statistics, write_bivariate_statistics
from founder.gold import build_correlation_and_covariance, build_correlation_edges
from founder.gold_pair_stats import (
    DEFAULT_BYTES_PER_PAIR,
    DEFAULT_MAX_WORKERS,
    build_pair_plan,
    chunked_pairs,
    index_returns,
    iter_pair_observations,
    resolve_worker_count,
)
from founder.paths import LakePaths


def _return(isin: str, exchange: str, code: str, date: str, value: float) -> dict[str, object]:
    return {
        "isin": isin,
        "exchange": exchange,
        "code": code,
        "date": date,
        "return": value,
    }


def test_build_pair_plan_rejects_universe_above_max_pair_count() -> None:
    plan = build_pair_plan(2_000, mode="dense", max_pair_count=500_000)

    assert plan.theoretical_pair_count == 2_000 * 1_999 // 2
    assert plan.accepted is False
    assert plan.rejection_reason is not None
    assert "exceeds max_pair_count" in plan.rejection_reason


def test_build_pair_plan_accepts_universe_within_limit() -> None:
    plan = build_pair_plan(100, mode="dense", max_pair_count=500_000, bucket_count=8)

    assert plan.theoretical_pair_count == 100 * 99 // 2
    assert plan.accepted is True
    assert plan.rejection_reason is None
    assert plan.expected_bucket_count == 8
    assert plan.estimated_memory_bytes == plan.theoretical_pair_count * DEFAULT_BYTES_PER_PAIR


def test_build_pair_plan_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="unsupported pair plan mode"):
        build_pair_plan(10, mode="unknown")
    with pytest.raises(ValueError, match="listing_count"):
        build_pair_plan(-1)
    with pytest.raises(ValueError, match="max_pair_count"):
        build_pair_plan(10, max_pair_count=0)
    with pytest.raises(ValueError, match="chunk_size"):
        build_pair_plan(10, chunk_size=0)
    with pytest.raises(ValueError, match="bucket_count"):
        build_pair_plan(10, bucket_count=0)


def test_resolve_worker_count_caps_to_explicit_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: 64)

    assert resolve_worker_count(None) == DEFAULT_MAX_WORKERS
    assert resolve_worker_count(None, max_workers=2) == 2
    assert resolve_worker_count(8) == 8
    assert resolve_worker_count(0) == 1


def test_chunked_pairs_streams_deterministic_bounded_chunks() -> None:
    returns = [_return(f"IE{i}", "XETRA", "AAA", "2026-01-01", 0.01 * i) for i in range(6)]
    pairs = list(iter_pair_observations(index_returns(returns), include_self=False))

    chunks = list(chunked_pairs(iter(pairs), chunk_size=4))

    assert [len(chunk) for chunk in chunks] == [4, 4, 4, 3]
    flattened = [pair for chunk in chunks for pair in chunk]
    assert flattened == pairs


def test_chunked_pairs_rejects_invalid_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        list(chunked_pairs(iter(()), chunk_size=0))


def test_correlation_and_covariance_reject_universe_above_max_pair_count() -> None:
    returns = [_return(f"IE{i}", "XETRA", "AAA", "2026-01-01", 0.01) for i in range(40)]

    with pytest.raises(ValueError, match="correlation/covariance build rejected"):
        build_correlation_and_covariance(returns, max_pair_count=100)


def test_correlation_edges_reject_universe_above_max_pair_count() -> None:
    returns = [_return(f"IE{i}", "XETRA", "AAA", "2026-01-01", 0.01) for i in range(40)]

    with pytest.raises(ValueError, match="correlation edges build rejected"):
        build_correlation_edges(returns, version="v1", max_pair_count=100)


def test_bivariate_bucket_count_grows_sublinearly_relative_to_pair_count(
    tmp_path: Path,
) -> None:
    paths = LakePaths(root=tmp_path / "lake")
    listing_count = 20
    returns = [
        _return(f"IE{i}", "XETRA", "AAA", date, value)
        for i in range(listing_count)
        for date, value in (("2026-01-01", 0.01 * (i + 1)), ("2026-01-02", 0.02 * (i + 1)))
    ]

    rows = write_bivariate_statistics(paths, returns, version="v1", bucket_count=8)
    theoretical_pair_count = listing_count * (listing_count - 1) // 2

    assert len(rows) == theoretical_pair_count
    bucket_dir = paths.gold / "bivariate_statistics" / "version=v1"
    written_files = list(bucket_dir.glob("bucket=*.parquet"))
    assert 0 < len(written_files) <= 8 < theoretical_pair_count


def test_bivariate_statistics_produces_no_duplicate_or_same_isin_pairs() -> None:
    returns = [
        _return("IE1", "XETRA", "AAA", "2026-01-01", 0.01),
        _return("IE1", "AS", "BBB", "2026-01-01", 0.02),
        _return("IE2", "PA", "CCC", "2026-01-01", 0.03),
    ]

    rows = build_bivariate_statistics(returns)
    pair_keys = [row["pair_key"] for row in rows]

    assert len(pair_keys) == len(set(pair_keys))
    assert all(row["left_isin"] != row["right_isin"] for row in rows)
