"""Gold-layer return, correlation, and covariance inputs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from math import log, sqrt
from typing import Any

from founder.paths import LakePaths
from founder.run_state import build_job_manifest, write_job_manifest
from founder.table_io import JsonRow, read_rows, write_rows

ListingKey = tuple[str, str, str]
ReturnsByListing = dict[ListingKey, dict[str, float]]
QuotesByListing = dict[ListingKey, list[JsonRow]]

_WORKER_LISTINGS: tuple[ListingKey, ...] = ()
_WORKER_RETURNS_BY_LISTING: ReturnsByListing = {}
_WORKER_QUOTES_BY_LISTING: QuotesByListing = {}


@dataclass(frozen=True)
class GoldListingResult:
    returns: list[JsonRow]
    correlations: list[JsonRow]
    covariances: list[JsonRow]
    features: list[JsonRow]
    manifest: JsonRow


@dataclass(frozen=True)
class PairObservation:
    left: ListingKey
    right: ListingKey
    left_id: int
    right_id: int
    dates: tuple[str, ...]
    left_values: tuple[float, ...]
    right_values: tuple[float, ...]


def build_returns(quote_rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    by_listing: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        by_listing.setdefault(key, []).append(row)

    returns: list[JsonRow] = []
    for (isin, exchange, code), rows in sorted(by_listing.items()):
        ordered = sorted(rows, key=lambda row: str(row["date"]))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            previous_close = float(previous["adjusted_close"])
            current_close = float(current["adjusted_close"])
            returns.append(
                {
                    "isin": isin,
                    "exchange": exchange,
                    "code": code,
                    "date": str(current["date"]),
                    "return": 0.0
                    if previous_close <= 0 or current_close <= 0
                    else log(current_close / previous_close),
                }
            )
    return returns


def _paired_values(
    rows: Sequence[Mapping[str, Any]], left: tuple[str, str, str], right: tuple[str, str, str]
) -> tuple[list[float], list[float]]:
    by_key = {
        (str(row["isin"]), str(row["exchange"]), str(row["code"]), str(row["date"])): float(
            row["return"]
        )
        for row in rows
    }
    dates = sorted(
        {date for isin, exchange, code, date in by_key if (isin, exchange, code) == left}
        & {date for isin, exchange, code, date in by_key if (isin, exchange, code) == right}
    )
    return [by_key[(*left, item)] for item in dates], [by_key[(*right, item)] for item in dates]


def covariance(left_values: Sequence[float], right_values: Sequence[float]) -> float:
    if len(left_values) < 2 or len(left_values) != len(right_values):
        return 0.0
    state = _OnlineCorrelation()
    for left, right in zip(left_values, right_values, strict=True):
        state.update(left, right)
    return state.sample_covariance()


def build_correlation_and_covariance(
    return_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[JsonRow], list[JsonRow]]:
    returns_by_listing = _index_returns(return_rows)
    correlations: list[JsonRow] = []
    covariances: list[JsonRow] = []
    for pair in _iter_pair_observations(returns_by_listing, include_self=True):
        cov = covariance(pair.left_values, pair.right_values)
        corr = _incremental_pearson(pair.left_values, pair.right_values)
        correlations.extend(_symmetric_pair_rows(pair.left, pair.right, "correlation", corr))
        covariances.extend(_symmetric_pair_rows(pair.left, pair.right, "covariance", cov))
    return _sort_pair_rows(correlations), _sort_pair_rows(covariances)


def build_correlation_edges(
    return_rows: Sequence[Mapping[str, Any]],
    *,
    version: str,
    metric: str = "pearson",
    min_abs_correlation: float | None = None,
    top_k_per_left: int | None = None,
) -> list[JsonRow]:
    if metric not in {"pearson", "spearman"}:
        raise ValueError(f"unsupported correlation edge metric: {metric}")
    if min_abs_correlation is not None and not 0 <= min_abs_correlation <= 1:
        raise ValueError("min_abs_correlation must be in [0, 1]")
    if top_k_per_left is not None and top_k_per_left < 1:
        raise ValueError("top_k_per_left must be positive")

    returns_by_listing = _index_returns(return_rows)
    rows: list[JsonRow] = []
    for pair in _iter_pair_observations(
        returns_by_listing,
        include_self=False,
        skip_same_isin=True,
    ):
        corr = _correlation_value(pair.left_values, pair.right_values, metric)
        if min_abs_correlation is not None and abs(corr) < min_abs_correlation:
            continue
        rows.append(
            {
                "version": version,
                "metric": metric,
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
                "value": corr,
            }
        )
    rows = _limit_top_correlation_edges(rows, top_k_per_left)
    return sorted(
        rows,
        key=lambda row: (
            int(row["left_id"]),
            -abs(float(row["value"])),
            int(row["right_id"]),
        ),
    )


def _correlation_value(
    left_values: Sequence[float], right_values: Sequence[float], metric: str
) -> float:
    if metric == "spearman":
        return _approximate_online_spearman(left_values, right_values)
    return _incremental_pearson(left_values, right_values)


def _incremental_pearson(left_values: Sequence[float], right_values: Sequence[float]) -> float:
    if len(left_values) < 2 or len(left_values) != len(right_values):
        return 0.0
    state = _OnlineCorrelation()
    for left, right in zip(left_values, right_values, strict=True):
        state.update(left, right)
    return state.value()


def _approximate_online_spearman(
    left_values: Sequence[float], right_values: Sequence[float]
) -> float:
    if len(left_values) < 2 or len(left_values) != len(right_values):
        return 0.0
    left_state = _OnlineMoments()
    right_state = _OnlineMoments()
    correlation = _OnlineCorrelation()
    for left, right in zip(left_values, right_values, strict=True):
        correlation.update(left_state.score(left), right_state.score(right))
        left_state.update(left)
        right_state.update(right)
    return correlation.value()


@dataclass
class _OnlineMoments:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def score(self, value: float) -> float:
        if self.count < 2 or self.m2 == 0:
            return 0.0
        variance = self.m2 / (self.count - 1)
        return 0.0 if variance <= 0 else (value - self.mean) / sqrt(variance)

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)


@dataclass
class _OnlineCorrelation:
    count: int = 0
    left_mean: float = 0.0
    right_mean: float = 0.0
    left_m2: float = 0.0
    right_m2: float = 0.0
    comoment: float = 0.0

    def update(self, left: float, right: float) -> None:
        self.count += 1
        left_delta = left - self.left_mean
        right_delta = right - self.right_mean
        self.left_mean += left_delta / self.count
        self.right_mean += right_delta / self.count
        self.comoment += left_delta * (right - self.right_mean)
        self.left_m2 += left_delta * (left - self.left_mean)
        self.right_m2 += right_delta * (right - self.right_mean)

    def value(self) -> float:
        if self.count < 2:
            return 0.0
        denominator = sqrt(self.left_m2 * self.right_m2)
        return 0.0 if denominator == 0 else self.comoment / denominator

    def sample_covariance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.comoment / (self.count - 1)


def _limit_top_correlation_edges(
    rows: Sequence[JsonRow], top_k_per_left: int | None
) -> list[JsonRow]:
    if top_k_per_left is None:
        return list(rows)
    by_left: dict[int, list[JsonRow]] = {}
    for row in rows:
        by_left.setdefault(int(row["left_id"]), []).append(row)
    limited: list[JsonRow] = []
    for left_id in sorted(by_left):
        limited.extend(
            sorted(
                by_left[left_id],
                key=lambda row: (-abs(float(row["value"])), int(row["right_id"])),
            )[:top_k_per_left]
        )
    return limited


def write_correlation_edges(
    paths: LakePaths,
    return_rows: Sequence[Mapping[str, Any]],
    *,
    version: str,
    metric: str = "pearson",
    min_abs_correlation: float | None = None,
    top_k_per_left: int | None = None,
    bucket_count: int = 128,
) -> list[JsonRow]:
    if bucket_count < 1:
        raise ValueError("bucket_count must be positive")
    rows = build_correlation_edges(
        return_rows,
        version=version,
        metric=metric,
        min_abs_correlation=min_abs_correlation,
        top_k_per_left=top_k_per_left,
    )
    base = paths.gold / "correlation_edges" / f"version={version}" / f"metric={metric}"
    if base.exists():
        for stale_path in base.glob("bucket=*.parquet"):
            stale_path.unlink()
    by_bucket: dict[int, list[JsonRow]] = {}
    for row in rows:
        bucket = int(row["left_id"]) % bucket_count
        row_with_bucket = dict(row)
        row_with_bucket["bucket"] = bucket
        by_bucket.setdefault(bucket, []).append(row_with_bucket)
    for bucket, bucket_rows in sorted(by_bucket.items()):
        write_rows(paths.gold_correlation_edges(version, metric, bucket), bucket_rows)
    return [row for bucket in sorted(by_bucket) for row in by_bucket[bucket]]


def _index_returns(return_rows: Sequence[Mapping[str, Any]]) -> ReturnsByListing:
    indexed: ReturnsByListing = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        indexed.setdefault(key, {})[str(row["date"])] = float(row["return"])
    return indexed


def _index_quotes(quote_rows: Sequence[Mapping[str, Any]]) -> QuotesByListing:
    indexed: QuotesByListing = {}
    for row in quote_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        indexed.setdefault(key, []).append(dict(row))
    return indexed


def _iter_pair_observations(
    returns_by_listing: ReturnsByListing,
    *,
    include_self: bool,
    skip_same_isin: bool = False,
) -> Iterator[PairObservation]:
    listings = tuple(sorted(returns_by_listing))
    for left_id, left in enumerate(listings):
        right_start = left_id if include_self else left_id + 1
        for right_id, right in enumerate(listings[right_start:], start=right_start):
            if skip_same_isin and left[0] == right[0]:
                continue
            left_rows = returns_by_listing[left]
            right_rows = returns_by_listing[right]
            dates = tuple(sorted(set(left_rows) & set(right_rows)))
            yield PairObservation(
                left=left,
                right=right,
                left_id=left_id,
                right_id=right_id,
                dates=dates,
                left_values=tuple(left_rows[item] for item in dates),
                right_values=tuple(right_rows[item] for item in dates),
            )


def _paired_indexed_values(
    returns_by_listing: ReturnsByListing, left: ListingKey, right: ListingKey
) -> tuple[list[float], list[float]]:
    left_rows = returns_by_listing.get(left, {})
    right_rows = returns_by_listing.get(right, {})
    dates = sorted(set(left_rows) & set(right_rows))
    return [left_rows[item] for item in dates], [right_rows[item] for item in dates]


def _symmetric_pair_rows(
    left: ListingKey, right: ListingKey, value_field: str, value: float
) -> list[JsonRow]:
    rows = [_pair_row(left, right, value_field, value)]
    if left != right:
        rows.append(_pair_row(right, left, value_field, value))
    return rows


def _pair_row(left: ListingKey, right: ListingKey, value_field: str, value: float) -> JsonRow:
    return {
        "left_isin": left[0],
        "left_exchange": left[1],
        "left_code": left[2],
        "right_isin": right[0],
        "right_exchange": right[1],
        "right_code": right[2],
        value_field: value,
    }


def _sort_pair_rows(rows: Sequence[JsonRow]) -> list[JsonRow]:
    return sorted(
        rows,
        key=lambda row: (
            str(row["left_isin"]),
            str(row["left_exchange"]),
            str(row["left_code"]),
            str(row["right_isin"]),
            str(row["right_exchange"]),
            str(row["right_code"]),
        ),
    )


def _max_drawdown(ordered_quotes: Sequence[Mapping[str, Any]]) -> float:
    peak: float | None = None
    max_drawdown = 0.0
    for row in ordered_quotes:
        close = float(row["adjusted_close"])
        peak = close if peak is None else max(peak, close)
        if peak == 0:
            continue
        max_drawdown = min(max_drawdown, (close / peak) - 1.0)
    return max_drawdown


def build_asset_features(
    quote_rows: Sequence[Mapping[str, Any]], return_rows: Sequence[Mapping[str, Any]]
) -> list[JsonRow]:
    quotes_by_listing: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        quotes_by_listing.setdefault(key, []).append(row)

    returns_by_listing: dict[tuple[str, str, str], list[float]] = {}
    for row in return_rows:
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        returns_by_listing.setdefault(key, []).append(float(row["return"]))

    features: list[JsonRow] = []
    for (isin, exchange, code), quotes in sorted(quotes_by_listing.items()):
        ordered_quotes = sorted(quotes, key=lambda row: str(row["date"]))
        returns = returns_by_listing.get((isin, exchange, code), [])
        mean_return = sum(returns) / len(returns) if returns else 0.0
        volatility = sqrt(covariance(returns, returns)) if len(returns) >= 2 else 0.0
        first_close = float(ordered_quotes[0]["adjusted_close"])
        last_close = float(ordered_quotes[-1]["adjusted_close"])
        features.append(
            {
                "isin": isin,
                "exchange": exchange,
                "code": code,
                "first_quote_date": str(ordered_quotes[0]["date"]),
                "last_quote_date": str(ordered_quotes[-1]["date"]),
                "quote_observation_count": len(ordered_quotes),
                "return_observation_count": len(returns),
                "total_return": 0.0 if first_close == 0 else (last_close / first_close) - 1.0,
                "mean_return": mean_return,
                "volatility": volatility,
                "max_drawdown": _max_drawdown(ordered_quotes),
            }
        )
    return features


def _init_gold_worker(
    listings: tuple[ListingKey, ...],
    returns_by_listing: ReturnsByListing,
    quotes_by_listing: QuotesByListing,
) -> None:
    global _WORKER_LISTINGS, _WORKER_RETURNS_BY_LISTING, _WORKER_QUOTES_BY_LISTING
    _WORKER_LISTINGS = listings
    _WORKER_RETURNS_BY_LISTING = returns_by_listing
    _WORKER_QUOTES_BY_LISTING = quotes_by_listing


def _listing_last_quote_date(quotes: Sequence[Mapping[str, Any]]) -> str:
    return max((str(row["date"]) for row in quotes), default="")


def _gold_listing_worker(args: tuple[LakePaths, ListingKey, str, str, int]) -> GoldListingResult:
    paths, left, completed_at, input_snapshot_date, input_listing_count = args
    return_rows = [
        {
            "isin": left[0],
            "exchange": left[1],
            "code": left[2],
            "date": date,
            "return": value,
        }
        for date, value in sorted(_WORKER_RETURNS_BY_LISTING.get(left, {}).items())
    ]
    feature_rows = build_asset_features(
        _WORKER_QUOTES_BY_LISTING.get(left, []),
        return_rows,
    )
    correlations: list[JsonRow] = []
    covariances: list[JsonRow] = []
    for pair in _iter_pair_observations(_WORKER_RETURNS_BY_LISTING, include_self=True):
        if pair.left != left:
            continue
        cov = covariance(pair.left_values, pair.right_values)
        corr = _incremental_pearson(pair.left_values, pair.right_values)
        correlations.extend(_symmetric_pair_rows(pair.left, pair.right, "correlation", corr))
        covariances.extend(_symmetric_pair_rows(pair.left, pair.right, "covariance", cov))

    write_rows(paths.gold_returns(left[1], left[0]), return_rows)
    if feature_rows:
        write_rows(paths.gold_asset_features(left[1], left[0]), feature_rows)
    return GoldListingResult(
        returns=return_rows,
        correlations=_sort_pair_rows(correlations),
        covariances=_sort_pair_rows(covariances),
        features=feature_rows,
        manifest={
            "status": "completed",
            "isin": left[0],
            "exchange": left[1],
            "code": left[2],
            "input_last_quote_date": _listing_last_quote_date(
                _WORKER_QUOTES_BY_LISTING.get(left, [])
            ),
            "input_snapshot_date": input_snapshot_date,
            "input_listing_count": input_listing_count,
            "completed_at": completed_at,
        },
    )


def _completed_gold_manifest(paths: LakePaths) -> dict[ListingKey, JsonRow]:
    completed: dict[ListingKey, JsonRow] = {}
    for row in read_rows(paths.gold_runs()):
        if row.get("status") != "completed":
            continue
        key = (str(row["isin"]), str(row["exchange"]), str(row["code"]))
        completed[key] = row
    return completed


def _listing_outputs_exist(paths: LakePaths, listing: ListingKey) -> bool:
    return (
        paths.gold_returns(listing[1], listing[0]).exists()
        and paths.gold_correlation(listing[1], listing[0]).exists()
        and paths.gold_covariance(listing[1], listing[0]).exists()
        and paths.gold_asset_features(listing[1], listing[0]).exists()
    )


def _is_listing_completed(
    paths: LakePaths,
    listing: ListingKey,
    last_quote_date: str,
    input_snapshot_date: str,
    input_listing_count: int,
) -> bool:
    row = _completed_gold_manifest(paths).get(listing)
    return (
        row is not None
        and str(row.get("input_last_quote_date", "")) == last_quote_date
        and str(row.get("input_snapshot_date", "")) == input_snapshot_date
        and int(row.get("input_listing_count", 0)) == input_listing_count
        and _listing_outputs_exist(paths, listing)
    )


def _read_listing_outputs(paths: LakePaths, listing: ListingKey) -> GoldListingResult:
    return GoldListingResult(
        returns=read_rows(paths.gold_returns(listing[1], listing[0])),
        correlations=read_rows(paths.gold_correlation(listing[1], listing[0])),
        covariances=read_rows(paths.gold_covariance(listing[1], listing[0])),
        features=read_rows(paths.gold_asset_features(listing[1], listing[0])),
        manifest=_completed_gold_manifest(paths).get(listing, {}),
    )


def write_gold_inputs(
    paths: LakePaths, quote_rows: Sequence[Mapping[str, Any]], *, concurrency: int = 2
) -> tuple[list[JsonRow], list[JsonRow], list[JsonRow], list[JsonRow]]:
    returns = build_returns(quote_rows)
    returns_by_listing = _index_returns(returns)
    quotes_by_listing = _index_quotes(quote_rows)
    listings = tuple(sorted(quotes_by_listing))
    completed_at = datetime.now(UTC).isoformat()
    workers = max(1, concurrency)
    input_snapshot_date = max(
        (_listing_last_quote_date(quotes_by_listing.get(listing, [])) for listing in listings),
        default="",
    )
    pending = [
        listing
        for listing in listings
        if not _is_listing_completed(
            paths,
            listing,
            _listing_last_quote_date(quotes_by_listing.get(listing, [])),
            input_snapshot_date,
            len(listings),
        )
    ]
    _init_gold_worker(listings, returns_by_listing, quotes_by_listing)
    if workers == 1 or len(pending) <= 1:
        processed = [
            _gold_listing_worker((paths, listing, completed_at, input_snapshot_date, len(listings)))
            for listing in pending
        ]
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_gold_worker,
            initargs=(listings, returns_by_listing, quotes_by_listing),
        ) as executor:
            processed = list(
                executor.map(
                    _gold_listing_worker,
                    [
                        (paths, listing, completed_at, input_snapshot_date, len(listings))
                        for listing in pending
                    ],
                )
            )

    processed_by_listing = {
        (
            str(result.manifest["isin"]),
            str(result.manifest["exchange"]),
            str(result.manifest["code"]),
        ): result
        for result in processed
    }
    processed_correlations = _sort_pair_rows(
        [row for result in processed for row in result.correlations]
    )
    processed_covariances = _sort_pair_rows(
        [row for result in processed for row in result.covariances]
    )
    for listing in pending:
        write_rows(
            paths.gold_correlation(listing[1], listing[0]),
            [row for row in processed_correlations if str(row["left_isin"]) == listing[0]],
        )
        write_rows(
            paths.gold_covariance(listing[1], listing[0]),
            [row for row in processed_covariances if str(row["left_isin"]) == listing[0]],
        )
    results: list[GoldListingResult] = []
    for listing in listings:
        results.append(processed_by_listing.get(listing) or _read_listing_outputs(paths, listing))
    manifest_rows = [result.manifest for result in results if result.manifest]
    if manifest_rows:
        write_rows(paths.gold_runs(), manifest_rows)
    write_job_manifest(
        paths,
        build_job_manifest(
            job_type="gold",
            run_id=f"gold-{input_snapshot_date or 'empty'}",
            status="completed",
            started_at=completed_at,
            finished_at=completed_at,
            input_paths=[paths.silver / "quotes"],
            output_paths=[paths.gold_runs(), paths.gold / "returns", paths.gold / "correlation"],
            row_counts={
                "returns": sum(len(result.returns) for result in results),
                "correlations": sum(len(result.correlations) for result in results),
                "covariances": sum(len(result.covariances) for result in results),
                "features": sum(len(result.features) for result in results),
            },
            concurrency=workers,
            resume_marker=input_snapshot_date,
        ),
    )
    return (
        [row for result in results for row in result.returns],
        _sort_pair_rows([row for result in results for row in result.correlations]),
        _sort_pair_rows([row for result in results for row in result.covariances]),
        [row for result in results for row in result.features],
    )
