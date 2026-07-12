"""Fetch planning, quote normalization, raw EODHD data, and coverage manifests.

The Fetch module starts at Search's approved `canonical_universe` contract. It
validates that contract, derives EODHD symbols, records raw or near-raw Bronze
quote and other EODHD data, normalizes quote rows for Silver, and
logs non-secret errors, and writes Silver metadata manifests that show coverage. It
does not perform fuzzy instrument discovery.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from founder.http import EodhdClient
from founder.logging import get_logger
from founder.paths import LakePaths
from founder.schemas import required_fields
from founder.table_io import JsonRow, read_rows, write_csv, write_rows

QuoteFetcher = Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
RawDataFetcher = Callable[[Mapping[str, Any]], Any]
LOGGER = get_logger(__name__)

ADDITIONAL_EODHD_DATASETS: tuple[tuple[str, str], ...] = (
    ("dividends", "div"),
    ("splits", "splits"),
)


def validate_canonical_rows(rows: Iterable[Mapping[str, Any]]) -> list[JsonRow]:
    """Validate Search's canonical-universe rows before fetching.

    Every required canonical field must be present and non-empty, and each ISIN
    may appear only once. The returned rows are plain dictionaries that can be
    safely passed to planning and fetch helpers.
    """
    validated: list[JsonRow] = []
    seen_isins: set[str] = set()
    for row in rows:
        item = dict(row)
        for field in required_fields("canonical_universe"):
            if field not in item or str(item[field]).strip() == "":
                raise ValueError(f"canonical universe row missing {field}")
        isin = str(item["isin"])
        if isin in seen_isins:
            raise ValueError(f"duplicate ISIN: {isin}")
        seen_isins.add(isin)
        validated.append(item)
    LOGGER.debug("canonical rows validated rows=%s", len(validated))
    return validated


def build_fetch_plan(
    canonical_rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    start_date: date | None,
    end_date: date | None,
) -> list[JsonRow]:
    """Create deterministic EODHD quote-fetch instructions.

    Each plan row contains the canonical identifiers plus the EODHD symbol in
    `CODE.EXCHANGE` form and the requested date window. Planning is pure: it
    validates input rows and returns plan rows without calling EODHD or writing
    data.
    """
    rows = validate_canonical_rows(canonical_rows)
    plan: list[JsonRow] = []
    for row in rows:
        code = str(row["code"])
        exchange = str(row["exchange"])
        plan.append(
            {
                "run_id": run_id,
                "isin": str(row["isin"]),
                "code": code,
                "exchange": exchange,
                "symbol": f"{code}.{exchange}",
                "start_date": start_date.isoformat() if start_date is not None else "",
                "end_date": end_date.isoformat() if end_date is not None else "",
            }
        )
    LOGGER.info("fetch plan built run_id=%s rows=%s", run_id, len(plan))
    return plan


def write_fetch_plan(
    paths: LakePaths,
    canonical_path: Path,
    *,
    run_id: str,
    start_date: date | None,
    end_date: date | None,
    limit: int | None = None,
    isin: str | None = None,
    gap_aware: bool = False,
) -> list[JsonRow]:
    """Read a canonical universe, write a fetch plan, and return it."""
    rows = read_rows(canonical_path)
    if isin is not None:
        normalized_isin = isin.casefold()
        rows = [row for row in rows if str(row.get("isin", "")).casefold() == normalized_isin]
        if not rows:
            raise ValueError(f"approved canonical universe does not contain ISIN: {isin}")
    if limit is not None:
        rows = rows[:limit]
    plan = build_fetch_plan(
        rows,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )
    if gap_aware:
        plan = build_gap_fetch_plan(plan, read_silver_quotes(paths), end_date=end_date)
    write_rows(paths.fetch_plan(run_id), plan)
    LOGGER.info("fetch plan written run_id=%s path=%s", run_id, paths.fetch_plan(run_id))
    return plan


def build_gap_fetch_plan(
    plan: Sequence[Mapping[str, Any]],
    quote_rows: Sequence[Mapping[str, Any]],
    *,
    end_date: date | None,
) -> list[JsonRow]:
    """Expand one plan row per listing into missing quote windows."""
    if end_date is None:
        return [dict(item) for item in plan]
    gaps = build_quote_gap_rows(
        plan,
        quote_rows,
        run_id=str(plan[0]["run_id"]) if plan else "",
        as_of=end_date,
    )
    gap_windows_by_listing: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for gap in gaps:
        key = (str(gap["isin"]), str(gap["code"]), str(gap["exchange"]))
        gap_windows_by_listing.setdefault(key, []).append(gap)

    gap_plan: list[JsonRow] = []
    for item in plan:
        row = dict(item)
        key = (str(row["isin"]), str(row["code"]), str(row["exchange"]))
        windows = [
            gap
            for gap in gap_windows_by_listing.get(key, [])
            if date.fromisoformat(str(gap["gap_start"])) <= end_date
        ]
        if not windows:
            known_dates = _quote_dates_for_listing(quote_rows, row)
            if known_dates:
                continue
            row["end_date"] = end_date.isoformat()
            row["window_reason"] = "full_history"
            gap_plan.append(row)
            continue
        for window in windows:
            window_end = min(date.fromisoformat(str(window["gap_end"])), end_date)
            gap_plan.append(
                {
                    **row,
                    "start_date": str(window["gap_start"]),
                    "end_date": window_end.isoformat(),
                    "window_reason": str(window["gap_type"]),
                }
            )
    LOGGER.info("gap fetch plan built input_rows=%s gap_rows=%s", len(plan), len(gap_plan))
    return gap_plan


def build_quote_gap_rows(
    plan: Sequence[Mapping[str, Any]],
    quote_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    as_of: date | None = None,
) -> list[JsonRow]:
    """Find missing trading-day ranges for planned quote listings."""
    gaps: list[JsonRow] = []
    for item in plan:
        known_dates = sorted(_quote_dates_for_listing(quote_rows, item))
        if not known_dates:
            continue
        first = known_dates[0]
        last = known_dates[-1]
        end = as_of or last
        if end < first:
            continue
        expected_dates = _expected_quote_dates(str(item["exchange"]), first, end)
        missing_dates = [
            quote_date for quote_date in expected_dates if quote_date not in known_dates
        ]
        historical_missing = [quote_date for quote_date in missing_dates if quote_date <= last]
        for gap_start, gap_end, missing_count in _quote_date_ranges(
            str(item["exchange"]), historical_missing
        ):
            gaps.append(
                _quote_gap_row(item, run_id, "historical_gap", gap_start, gap_end, missing_count)
            )
        tail_dates = [quote_date for quote_date in expected_dates if quote_date > last]
        for gap_start, gap_end, missing_count in _quote_date_ranges(
            str(item["exchange"]), tail_dates
        ):
            gaps.append(_quote_gap_row(item, run_id, "tail", gap_start, gap_end, missing_count))
    return sorted(gaps, key=lambda row: (str(row["isin"]), str(row["gap_start"])))


def _quote_gap_row(
    item: Mapping[str, Any],
    run_id: str,
    gap_type: str,
    gap_start: date,
    gap_end: date,
    missing_count: int,
) -> JsonRow:
    return {
        "run_id": run_id,
        "isin": str(item["isin"]),
        "code": str(item["code"]),
        "exchange": str(item["exchange"]),
        "symbol": str(item["symbol"]),
        "data_type": "quotes",
        "gap_type": gap_type,
        "gap_start": gap_start.isoformat(),
        "gap_end": gap_end.isoformat(),
        "missing_dates": missing_count,
    }


def _quote_dates_for_listing(
    quote_rows: Sequence[Mapping[str, Any]], item: Mapping[str, Any]
) -> set[date]:
    key = (str(item["isin"]), str(item["code"]), str(item["exchange"]))
    return {
        date.fromisoformat(str(row["date"]))
        for row in quote_rows
        if (str(row["isin"]), str(row["code"]), str(row["exchange"])) == key
    }


def _expected_quote_dates(exchange: str, start: date, end: date) -> list[date]:
    quote_dates: list[date] = []
    current = start
    while current <= end:
        if _is_trading_day(exchange, current):
            quote_dates.append(current)
        current += timedelta(days=1)
    return quote_dates


def _quote_date_ranges(exchange: str, dates: Sequence[date]) -> list[tuple[date, date, int]]:
    if not dates:
        return []
    ordered = sorted(dates)
    ranges: list[tuple[date, date, int]] = []
    start = previous = ordered[0]
    count = 1
    for quote_date in ordered[1:]:
        expected = _next_trading_day(exchange, previous)
        if quote_date == expected:
            previous = quote_date
            count += 1
            continue
        ranges.append((start, previous, count))
        start = previous = quote_date
        count = 1
    ranges.append((start, previous, count))
    return ranges


def _next_trading_day(exchange: str, value: date) -> date:
    current = value + timedelta(days=1)
    while not _is_trading_day(exchange, current):
        current += timedelta(days=1)
    return current


def _is_trading_day(exchange: str, value: date) -> bool:
    if value.weekday() >= 5:
        return False
    if exchange.upper() == "XETRA":
        return value not in _xetra_holidays(value.year)
    return True


def _xetra_holidays(year: int) -> set[date]:
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        easter + timedelta(days=50),
        date(year, 5, 1),
        date(year, 10, 3),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 26),
        date(year, 12, 31),
    }


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * offset) // 451
    month = (h + offset - 7 * m + 114) // 31
    day = ((h + offset - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _merge_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
    *,
    key_fields: Sequence[str],
) -> list[JsonRow]:
    merged: dict[tuple[str, ...], JsonRow] = {}
    for row in [*existing_rows, *new_rows]:
        item = dict(row)
        key = tuple(str(item[field]) for field in key_fields)
        merged[key] = item
    return [merged[key] for key in sorted(merged)]


def fetch_quotes_to_bronze(
    paths: LakePaths,
    plan: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
    fetcher: QuoteFetcher,
) -> tuple[list[JsonRow], list[JsonRow]]:
    """Fetch planned EOD quote payloads into Bronze.

    The supplied `fetcher` performs the actual API call, which keeps this helper
    easy to test with recorded or mocked responses. Per-symbol failures are
    logged and returned as non-secret error rows without stopping the remaining batch.
    """
    successes: list[JsonRow] = []
    errors: list[JsonRow] = []
    for item in plan:
        try:
            quotes = list(fetcher(item))
            rows_by_year: dict[int, list[JsonRow]] = {}
            for quote in quotes:
                quote_date = str(quote["date"])
                rows_by_year.setdefault(int(quote_date[:4]), []).append(
                    {
                        **dict(quote),
                        "run_id": str(item["run_id"]),
                        "isin": str(item["isin"]),
                        "code": str(item["code"]),
                        "exchange": str(item["exchange"]),
                        "symbol": str(item["symbol"]),
                        "run_date": run_date.isoformat(),
                    }
                )
            for year, rows in rows_by_year.items():
                quote_path = paths.bronze_quote_file(str(item["exchange"]), year, str(item["isin"]))
                write_rows(
                    quote_path,
                    _merge_rows(
                        read_rows(quote_path),
                        rows,
                        key_fields=("isin", "exchange", "code", "date"),
                    ),
                )
            successes.append({**dict(item), "rows": len(quotes)})
            LOGGER.debug("quote payload written symbol=%s rows=%s", item["symbol"], len(quotes))
        except Exception as error:  # noqa: BLE001 - record and continue batch failures.
            errors.append(
                {
                    "run_id": str(item["run_id"]),
                    "code": str(item["code"]),
                    "exchange": str(item["exchange"]),
                    "endpoint": "eod",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
            LOGGER.warning("quote fetch failed symbol=%s error=%s", item["symbol"], error)
    LOGGER.info("bronze quote fetch complete successes=%s errors=%s", len(successes), len(errors))
    return successes, errors


def eodhd_quote_fetcher(client: EodhdClient) -> QuoteFetcher:
    """Wrap `EodhdClient` as a `QuoteFetcher` for planned EOD requests."""

    def fetch(item: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        params: dict[str, str] = {"fmt": "json"}
        start_date = str(item.get("start_date", ""))
        end_date = str(item.get("end_date", ""))
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date
        payload = client.get_json(f"/eod/{item['symbol']}", params)
        if not isinstance(payload, list):
            raise ValueError("expected EODHD quote list")
        return [row for row in payload if isinstance(row, dict)]

    return fetch


def eodhd_raw_data_fetcher(client: EodhdClient, endpoint: str) -> RawDataFetcher:
    """Wrap `EodhdClient` for raw per-symbol EODHD datasets."""

    def fetch(item: Mapping[str, Any]) -> Any:
        params: dict[str, str] = {"fmt": "json"}
        start_date = str(item.get("start_date", ""))
        end_date = str(item.get("end_date", ""))
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date
        return client.get_json(f"/{endpoint}/{item['symbol']}", params)

    return fetch


def fetch_raw_eodhd_datasets_to_bronze(
    paths: LakePaths,
    plan: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
    fetchers: Mapping[str, RawDataFetcher],
) -> tuple[list[JsonRow], list[JsonRow]]:
    """Archive raw per-symbol EODHD datasets that are not normalized yet."""
    successes: list[JsonRow] = []
    errors: list[JsonRow] = []
    for item in _unique_plan_listings(plan):
        raw_item = {**dict(item), "start_date": "", "end_date": run_date.isoformat()}
        for dataset, fetcher in fetchers.items():
            try:
                payload = fetcher(raw_item)
                rows = _raw_dataset_rows(dataset, raw_item, payload, run_date=run_date)
                rows_by_year: dict[int, list[JsonRow]] = {}
                for row in rows:
                    rows_by_year.setdefault(int(str(row["date"])[:4]), []).append(row)
                if not rows_by_year:
                    rows_by_year[run_date.year] = []
                for year, year_rows in rows_by_year.items():
                    dataset_path = paths.bronze_dataset_file(
                        dataset,
                        str(raw_item["exchange"]),
                        year,
                        str(raw_item["isin"]),
                    )
                    write_rows(
                        dataset_path,
                        _merge_rows(
                            read_rows(dataset_path),
                            year_rows,
                            key_fields=("isin", "exchange", "code", "date"),
                        ),
                    )
                successes.append({**dict(raw_item), "data_type": dataset, "rows": len(rows)})
                LOGGER.debug(
                    "raw EODHD rows written symbol=%s dataset=%s rows=%s",
                    item["symbol"],
                    dataset,
                    len(rows),
                )
            except Exception as error:  # noqa: BLE001 - record and continue batch failures.
                errors.append(
                    {
                        "run_id": str(item["run_id"]),
                        "code": str(item["code"]),
                        "exchange": str(item["exchange"]),
                        "endpoint": dataset,
                        "error_type": type(error).__name__,
                        "message": str(error),
                    }
                )
                LOGGER.warning(
                    "raw EODHD fetch failed symbol=%s dataset=%s error=%s",
                    item["symbol"],
                    dataset,
                    error,
                )
    LOGGER.info(
        "raw EODHD datasets fetched successes=%s errors=%s",
        len(successes),
        len(errors),
    )
    return successes, errors


def _raw_dataset_rows(
    dataset: str,
    item: Mapping[str, Any],
    payload: Any,
    *,
    run_date: date,
) -> list[JsonRow]:
    if not isinstance(payload, list):
        raise ValueError(f"expected EODHD {dataset} list")
    rows: list[JsonRow] = []
    for raw_row in payload:
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"expected EODHD {dataset} row object")
        row = dict(raw_row)
        if "date" not in row:
            raise ValueError(f"expected EODHD {dataset} row date")
        rows.append(
            {
                **row,
                "run_id": str(item["run_id"]),
                "isin": str(item["isin"]),
                "code": str(item["code"]),
                "exchange": str(item["exchange"]),
                "symbol": str(item["symbol"]),
                "run_date": run_date.isoformat(),
            }
        )
    return rows


def _unique_plan_listings(plan: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    listings: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in plan:
        key = (
            str(item["isin"]),
            str(item["code"]),
            str(item["exchange"]),
            str(item["symbol"]),
        )
        if key not in seen:
            seen.add(key)
            listings.append(item)
    return listings


def normalize_quote_rows(
    plan: Sequence[Mapping[str, Any]],
    raw_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    fetched_at: datetime,
    currency_by_isin: Mapping[str, str] | None = None,
) -> list[JsonRow]:
    """Normalize raw EOD quote payloads into Silver quote rows.

    Rows are keyed by `(isin, exchange, code, date)`, so duplicate raw quotes for
    the same listing and day are replaced deterministically. Missing OHLC values
    fall back to close, volume defaults to zero, and timestamps are normalized to
    UTC ISO strings.
    """
    currencies = currency_by_isin or {}
    rows: dict[tuple[str, str, str, str], JsonRow] = {}
    for item in plan:
        symbol = str(item["symbol"])
        isin = str(item["isin"])
        for raw in raw_by_symbol.get(symbol, ()):  # one row per isin/exchange/code/date
            quote_date = str(raw["date"])
            key = (isin, str(item["exchange"]), str(item["code"]), quote_date)
            rows[key] = {
                "run_id": str(item["run_id"]),
                "isin": isin,
                "code": str(item["code"]),
                "exchange": str(item["exchange"]),
                "date": quote_date,
                "open": float(raw.get("open", raw.get("close", 0.0))),
                "high": float(raw.get("high", raw.get("close", 0.0))),
                "low": float(raw.get("low", raw.get("close", 0.0))),
                "close": float(raw.get("close", 0.0)),
                "adjusted_close": float(
                    raw.get("adjusted_close", raw.get("adjusted_close", raw.get("close", 0.0)))
                ),
                "volume": int(raw.get("volume", 0)),
                "currency": currencies.get(isin, ""),
                "fetched_at": fetched_at.astimezone(UTC).isoformat(),
            }
    normalized = [rows[key] for key in sorted(rows)]
    LOGGER.info("quote rows normalized rows=%s", len(normalized))
    return normalized


def write_silver_quotes(paths: LakePaths, quote_rows: Sequence[Mapping[str, Any]]) -> None:
    """Write normalized quote rows partitioned by quote year."""
    by_year: dict[int, list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        by_year.setdefault(int(str(row["date"])[:4]), []).append(row)
    for year, rows in by_year.items():
        quote_path = paths.silver_quotes_year(year)
        merged_rows = _merge_rows(
            read_rows(quote_path),
            rows,
            key_fields=("isin", "exchange", "code", "date"),
        )
        write_rows(quote_path, merged_rows)
        LOGGER.info("silver quote rows written year=%s rows=%s", year, len(merged_rows))


def read_silver_quotes(paths: LakePaths) -> list[JsonRow]:
    """Read all accumulated Silver quote partitions."""
    rows: list[JsonRow] = []
    for path in sorted((paths.silver / "quotes").glob("year=*/quotes.parquet")):
        rows.extend(read_rows(path))
    return rows


def build_coverage(
    quote_rows: Sequence[Mapping[str, Any]], *, run_id: str, overlap_days: int = 5
) -> list[JsonRow]:
    """Summarize quote completeness and the next incremental fetch start.

    Coverage is calculated per `(isin, code, exchange)`. `missing_periods` is a
    simple calendar-day gap count, and `next_fetch_start` backs up from the last
    quote date by `overlap_days` so later runs can safely deduplicate overlap.
    """
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for row in quote_rows:
        key = (str(row["isin"]), str(row["code"]), str(row["exchange"]))
        grouped.setdefault(key, []).append(str(row["date"]))

    coverage: list[JsonRow] = []
    for key in sorted(grouped):
        dates = sorted(set(grouped[key]))
        first = date.fromisoformat(dates[0])
        last = date.fromisoformat(dates[-1])
        expected_days = (last - first).days + 1
        missing = max(0, expected_days - len(dates))
        coverage.append(
            {
                "run_id": run_id,
                "isin": key[0],
                "code": key[1],
                "exchange": key[2],
                "first_quote_date": dates[0],
                "last_quote_date": dates[-1],
                "observed_rows": len(dates),
                "missing_periods": missing,
                "next_fetch_start": (last - timedelta(days=overlap_days)).isoformat(),
            }
        )
    LOGGER.debug("coverage built run_id=%s rows=%s", run_id, len(coverage))
    return coverage


def write_fetch_manifests(
    paths: LakePaths,
    *,
    run_id: str,
    quote_rows: Sequence[Mapping[str, Any]],
    plan: Sequence[Mapping[str, Any]] = (),
    as_of: date | None = None,
) -> list[JsonRow]:
    """Write coverage, fetch-run metadata, and review CSV manifests."""
    coverage = build_coverage(quote_rows, run_id=run_id)
    write_rows(
        paths.quote_gaps(),
        build_quote_gap_rows(plan, quote_rows, run_id=run_id, as_of=as_of),
    )
    write_rows(paths.coverage(), coverage)
    write_rows(
        paths.fetch_runs(),
        [
            {
                "run_id": run_id,
                "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "quote_rows": len(quote_rows),
            }
        ],
    )
    write_csv(paths.coverage().with_suffix(".csv"), coverage, required_fields("coverage"))
    LOGGER.info("fetch manifests written run_id=%s coverage_rows=%s", run_id, len(coverage))
    return coverage
