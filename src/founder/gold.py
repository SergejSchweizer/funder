"""Gold-layer return, correlation, and covariance inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from math import log, sqrt
from typing import Any

from founder.paths import LakePaths
from founder.table_io import JsonRow, read_rows, write_rows

ListingKey = tuple[str, str, str]
ReturnsByListing = dict[ListingKey, dict[str, float]]
QuotesByListing = dict[ListingKey, list[JsonRow]]

_WORKER_LISTINGS: tuple[ListingKey, ...] = ()
_WORKER_RETURNS_BY_LISTING: ReturnsByListing = {}
_WORKER_QUOTES_BY_LISTING: QuotesByListing = {}
_WORKER_VARIANCE_BY_LISTING: dict[ListingKey, float] = {}


@dataclass(frozen=True)
class GoldListingResult:
    returns: list[JsonRow]
    correlations: list[JsonRow]
    covariances: list[JsonRow]
    features: list[JsonRow]
    manifest: JsonRow


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
    left_mean = sum(left_values) / len(left_values)
    right_mean = sum(right_values) / len(right_values)
    return sum(
        (left - left_mean) * (right - right_mean)
        for left, right in zip(left_values, right_values, strict=True)
    ) / (len(left_values) - 1)


def build_correlation_and_covariance(
    return_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[JsonRow], list[JsonRow]]:
    returns_by_listing = _index_returns(return_rows)
    listings = tuple(sorted(returns_by_listing))
    variances = {
        listing: covariance(list(values.values()), list(values.values()))
        for listing, values in returns_by_listing.items()
    }
    correlations: list[JsonRow] = []
    covariances: list[JsonRow] = []
    for left_index, left in enumerate(listings):
        for right in listings[left_index:]:
            left_values, right_values = _paired_indexed_values(returns_by_listing, left, right)
            cov = covariance(left_values, right_values)
            left_var = variances[left]
            right_var = variances[right]
            corr = 0.0 if left_var == 0 or right_var == 0 else cov / sqrt(left_var * right_var)
            correlations.extend(_symmetric_pair_rows(left, right, "correlation", corr))
            covariances.extend(_symmetric_pair_rows(left, right, "covariance", cov))
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
    listings = tuple(sorted(returns_by_listing))
    listing_ids = {listing: index for index, listing in enumerate(listings)}
    rows: list[JsonRow] = []
    for left_index, left in enumerate(listings):
        for right in listings[left_index + 1 :]:
            dates = sorted(set(returns_by_listing[left]) & set(returns_by_listing[right]))
            left_values = [returns_by_listing[left][item] for item in dates]
            right_values = [returns_by_listing[right][item] for item in dates]
            corr = _correlation_value(left_values, right_values, metric)
            if min_abs_correlation is not None and abs(corr) < min_abs_correlation:
                continue
            rows.append(
                {
                    "version": version,
                    "metric": metric,
                    "left_id": listing_ids[left],
                    "right_id": listing_ids[right],
                    "left_isin": left[0],
                    "left_exchange": left[1],
                    "left_code": left[2],
                    "right_isin": right[0],
                    "right_exchange": right[1],
                    "right_code": right[2],
                    "date_start": dates[0] if dates else "",
                    "date_end": dates[-1] if dates else "",
                    "n_observations": len(dates),
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
        left_values = _midranks(left_values)
        right_values = _midranks(right_values)
    left_var = covariance(left_values, left_values)
    right_var = covariance(right_values, right_values)
    cov = covariance(left_values, right_values)
    return 0.0 if left_var == 0 or right_var == 0 else cov / sqrt(left_var * right_var)


def _midranks(values: Sequence[float]) -> list[float]:
    ranks = [0.0] * len(values)
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = ((index + 1) + end) / 2
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks


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
    variance_by_listing: dict[ListingKey, float],
) -> None:
    global _WORKER_LISTINGS, _WORKER_RETURNS_BY_LISTING, _WORKER_QUOTES_BY_LISTING
    global _WORKER_VARIANCE_BY_LISTING
    _WORKER_LISTINGS = listings
    _WORKER_RETURNS_BY_LISTING = returns_by_listing
    _WORKER_QUOTES_BY_LISTING = quotes_by_listing
    _WORKER_VARIANCE_BY_LISTING = variance_by_listing


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
    left_index = _WORKER_LISTINGS.index(left)
    for right in _WORKER_LISTINGS[left_index:]:
        left_values, right_values = _paired_indexed_values(_WORKER_RETURNS_BY_LISTING, left, right)
        cov = covariance(left_values, right_values)
        left_var = _WORKER_VARIANCE_BY_LISTING.get(left, 0.0)
        right_var = _WORKER_VARIANCE_BY_LISTING.get(right, 0.0)
        corr = 0.0 if left_var == 0 or right_var == 0 else cov / sqrt(left_var * right_var)
        correlations.extend(_symmetric_pair_rows(left, right, "correlation", corr))
        covariances.extend(_symmetric_pair_rows(left, right, "covariance", cov))

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
    variance_by_listing = {
        listing: covariance(list(values.values()), list(values.values()))
        for listing, values in returns_by_listing.items()
    }
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
    _init_gold_worker(listings, returns_by_listing, quotes_by_listing, variance_by_listing)
    if workers == 1 or len(pending) <= 1:
        processed = [
            _gold_listing_worker((paths, listing, completed_at, input_snapshot_date, len(listings)))
            for listing in pending
        ]
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_gold_worker,
            initargs=(listings, returns_by_listing, quotes_by_listing, variance_by_listing),
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
    return (
        [row for result in results for row in result.returns],
        _sort_pair_rows([row for result in results for row in result.correlations]),
        _sort_pair_rows([row for result in results for row in result.covariances]),
        [row for result in results for row in result.features],
    )
