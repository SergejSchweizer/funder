"""Bivariate Statistics for approved ISIN listing pairs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from founder.gold_pair_stats import (
    DEFAULT_BUCKET_COUNT,
    DEFAULT_MAX_PAIR_COUNT,
    DEFAULT_PAIR_CHUNK_SIZE,
    PairObservation,
    PairPlan,
    build_pair_plan,
    chunked_pairs,
    correlation_value,
    index_returns,
    iter_pair_observations,
    resolve_worker_count,
    sample_covariance,
    sort_pair_rows,
)
from founder.paths import LakePaths
from founder.run_state import build_job_manifest, write_job_manifest
from founder.schemas import validate_rows
from founder.table_io import JsonRow, read_rows, write_rows

_CURRENT_VERSION = "current"


def build_bivariate_statistics(
    return_rows: Sequence[Mapping[str, Any]],
    *,
    skip_same_isin: bool = True,
    concurrency: int | None = None,
    max_pair_count: int = DEFAULT_MAX_PAIR_COUNT,
    chunk_size: int = DEFAULT_PAIR_CHUNK_SIZE,
) -> list[JsonRow]:
    """Compute pairwise statistics from aligned return rows.

    The output intentionally contains only two-listing statistics. Single-listing
    return summaries belong in the separate univariate statistics module. A
    universe whose theoretical pair count exceeds ``max_pair_count`` is rejected
    before any pair is enumerated.
    """
    returns_by_listing = index_returns(return_rows)
    plan = build_pair_plan(
        len(returns_by_listing),
        mode="dense",
        max_pair_count=max_pair_count,
        chunk_size=chunk_size,
        concurrency=concurrency,
    )
    if not plan.accepted:
        raise ValueError(f"bivariate statistics rejected: {plan.rejection_reason}")

    pairs = iter_pair_observations(
        returns_by_listing,
        include_self=False,
        skip_same_isin=skip_same_isin,
    )
    rows: list[JsonRow] = []
    executor = ProcessPoolExecutor(max_workers=plan.worker_count) if plan.worker_count > 1 else None
    try:
        for chunk in chunked_pairs(pairs, plan.chunk_size):
            if executor is None or len(chunk) <= 1:
                rows.extend(_build_bivariate_pair_statistics(pair) for pair in chunk)
            else:
                rows.extend(executor.map(_build_bivariate_pair_statistics, chunk))
    finally:
        if executor is not None:
            executor.shutdown()
    return sort_pair_rows(rows)


def write_bivariate_statistics(
    paths: LakePaths,
    return_rows: Sequence[Mapping[str, Any]],
    *,
    skip_same_isin: bool = True,
    concurrency: int | None = None,
    version: str = _CURRENT_VERSION,
    bucket_count: int = DEFAULT_BUCKET_COUNT,
    max_pair_count: int = DEFAULT_MAX_PAIR_COUNT,
    chunk_size: int = DEFAULT_PAIR_CHUNK_SIZE,
) -> list[JsonRow]:
    """Write Bivariate Statistics rows to deterministic bucketed Gold paths.

    Rows are grouped into ``bucket_count`` Parquet buckets keyed by
    ``left_id % bucket_count`` instead of one file per pair, so file count grows
    sublinearly with pair count. A universe whose theoretical pair count exceeds
    ``max_pair_count`` is rejected before any pair is materialized or submitted
    to a worker. Pair-plan diagnostics are persisted as a job manifest for every
    call, including rejected ones.
    """
    returns_by_listing = index_returns(return_rows)
    plan = build_pair_plan(
        len(returns_by_listing),
        mode="dense",
        max_pair_count=max_pair_count,
        chunk_size=chunk_size,
        bucket_count=bucket_count,
        concurrency=concurrency,
    )
    _write_pair_plan_manifest(paths, version=version, plan=plan)
    if not plan.accepted:
        raise ValueError(
            f"bivariate statistics rejected for version {version!r}: {plan.rejection_reason}"
        )

    existing_by_bucket = _read_existing_buckets(paths, version, plan.bucket_count)
    cache_index: dict[str, JsonRow] = {}
    for bucket_rows in existing_by_bucket.values():
        for row in bucket_rows:
            cache_index[str(row["pair_key"])] = row

    pairs = iter_pair_observations(
        returns_by_listing,
        include_self=False,
        skip_same_isin=skip_same_isin,
    )
    final_by_bucket: dict[int, list[JsonRow]] = {}
    dirty_buckets: set[int] = set()
    executor = ProcessPoolExecutor(max_workers=plan.worker_count) if plan.worker_count > 1 else None
    try:
        for chunk in chunked_pairs(pairs, plan.chunk_size):
            fresh_targets: list[PairObservation] = []
            for pair in chunk:
                bucket = pair.left_id % plan.bucket_count
                cached = cache_index.get(_pair_key(pair.left, pair.right))
                if cached is not None and _cache_row_matches(cached, pair, version, bucket):
                    final_by_bucket.setdefault(bucket, []).append(cached)
                    continue
                fresh_targets.append(pair)
            if not fresh_targets:
                continue
            if executor is None or len(fresh_targets) <= 1:
                fresh_rows = [_build_bivariate_pair_statistics(pair) for pair in fresh_targets]
            else:
                fresh_rows = list(executor.map(_build_bivariate_pair_statistics, fresh_targets))
            for pair, row in zip(fresh_targets, fresh_rows, strict=True):
                bucket = pair.left_id % plan.bucket_count
                bucketed_row = dict(row)
                bucketed_row["version"] = version
                bucketed_row["bucket"] = bucket
                final_by_bucket.setdefault(bucket, []).append(bucketed_row)
                dirty_buckets.add(bucket)
    finally:
        if executor is not None:
            executor.shutdown()

    validate_rows(
        "bivariate_statistics",
        [row for bucket_rows in final_by_bucket.values() for row in bucket_rows],
    )
    _write_dirty_buckets(paths, version, existing_by_bucket, final_by_bucket, dirty_buckets)
    return sort_pair_rows([row for bucket_rows in final_by_bucket.values() for row in bucket_rows])


def _write_pair_plan_manifest(paths: LakePaths, *, version: str, plan: PairPlan) -> None:
    manifest = build_job_manifest(
        job_type="bivariate-statistics-plan",
        run_id=version,
        status="completed" if plan.accepted else "failed",
        row_counts={
            "listing_count": plan.listing_count,
            "theoretical_pair_count": plan.theoretical_pair_count,
            "chunk_size": plan.chunk_size,
            "worker_count": plan.worker_count,
            "bucket_count": plan.bucket_count,
            "expected_bucket_count": plan.expected_bucket_count,
            "estimated_memory_bytes": plan.estimated_memory_bytes,
            "max_pair_count": plan.max_pair_count,
        },
        resume_marker=plan.mode,
        error_summary=() if plan.accepted else ({"reason": plan.rejection_reason},),
    )
    write_job_manifest(paths, manifest)


def _read_existing_buckets(
    paths: LakePaths, version: str, bucket_count: int
) -> dict[int, list[JsonRow]]:
    """Read existing bucket files, discarding any bucket whose content is corrupt."""
    by_bucket: dict[int, list[JsonRow]] = {}
    for bucket in range(bucket_count):
        path = paths.gold_bivariate_statistics_bucket(version, bucket)
        if not path.exists():
            continue
        rows = read_rows(path)
        if any(int(row.get("bucket", -1)) != bucket for row in rows):
            # Corrupt or foreign bucket content must never masquerade as a cache hit.
            continue
        by_bucket[bucket] = rows
    return by_bucket


def _write_dirty_buckets(
    paths: LakePaths,
    version: str,
    existing_by_bucket: Mapping[int, list[JsonRow]],
    final_by_bucket: Mapping[int, list[JsonRow]],
    dirty_buckets: set[int],
) -> None:
    for bucket in sorted(set(existing_by_bucket) | set(final_by_bucket)):
        final_rows = sort_pair_rows(final_by_bucket.get(bucket, []))
        existing_keys = {str(row["pair_key"]) for row in existing_by_bucket.get(bucket, [])}
        final_keys = {str(row["pair_key"]) for row in final_rows}
        if bucket not in dirty_buckets and existing_keys == final_keys:
            continue
        path = paths.gold_bivariate_statistics_bucket(version, bucket)
        if not final_rows:
            path.unlink(missing_ok=True)
            continue
        write_rows(path, final_rows)


def _cache_row_matches(cached: JsonRow, pair: PairObservation, version: str, bucket: int) -> bool:
    date_start = pair.dates[0] if pair.dates else ""
    date_end = pair.dates[-1] if pair.dates else ""
    return (
        str(cached.get("version")) == version
        and int(cached.get("bucket", -1)) == bucket
        and str(cached.get("left_listing_key")) == _listing_key(pair.left)
        and str(cached.get("right_listing_key")) == _listing_key(pair.right)
        and str(cached.get("date_start")) == date_start
        and str(cached.get("date_end")) == date_end
        and int(cached.get("n_observations", -1)) == len(pair.dates)
    )


def _build_bivariate_pair_statistics(pair: PairObservation) -> JsonRow:
    covariance = sample_covariance(pair.left_values, pair.right_values)
    left_variance = sample_covariance(pair.left_values, pair.left_values)
    right_variance = sample_covariance(pair.right_values, pair.right_values)
    return {
        "pair_key": _pair_key(pair.left, pair.right),
        "left_listing_key": _listing_key(pair.left),
        "right_listing_key": _listing_key(pair.right),
        "left_id": pair.left_id,
        "right_id": pair.right_id,
        "left_isin": pair.left[0],
        "left_exchange": pair.left[1],
        "left_code": pair.left[2],
        "right_isin": pair.right[0],
        "right_exchange": pair.right[1],
        "right_code": pair.right[2],
        "date_start": pair.dates[0] if pair.dates else "",
        "date_end": pair.dates[-1] if pair.dates else "",
        "n_observations": len(pair.dates),
        "pearson_correlation": correlation_value(
            pair.left_values,
            pair.right_values,
            "pearson",
        ),
        "spearman_correlation": correlation_value(
            pair.left_values,
            pair.right_values,
            "spearman",
        ),
        "covariance": covariance,
        "left_variance": left_variance,
        "right_variance": right_variance,
        "left_beta_to_right": _ratio(covariance, right_variance),
        "right_beta_to_left": _ratio(covariance, left_variance),
    }


def read_legacy_bivariate_pair(
    paths: LakePaths, left: tuple[str, str, str], right: tuple[str, str, str]
) -> JsonRow | None:
    """Read a single pair row from the pre-C03 one-file-per-pair layout.

    Kept only for the documented migration window while historical
    ``gold/bivariate_statistics/{exchange}/{isin}/{code}/...`` files still
    exist. New writes always use :func:`write_bivariate_statistics`, which
    persists deterministic version/bucket Parquet files instead.
    """
    rows = read_rows(
        paths.gold_bivariate_statistics_pair(
            left[1],
            left[0],
            left[2],
            right[1],
            right[0],
            right[2],
        )
    )
    return rows[0] if len(rows) == 1 else None


def _listing_key(listing: tuple[str, str, str]) -> str:
    isin, exchange, code = listing
    return f"{exchange}__{isin}__{code}"


def _pair_key(left: tuple[str, str, str], right: tuple[str, str, str]) -> str:
    return f"{_listing_key(left)}___{_listing_key(right)}"


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


__all__ = [
    "build_bivariate_statistics",
    "read_legacy_bivariate_pair",
    "resolve_worker_count",
    "write_bivariate_statistics",
]
