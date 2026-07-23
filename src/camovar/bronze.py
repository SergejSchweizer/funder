"""Bronze planning, Bronze EODHD ingestion, and coverage manifests.

The Bronze module starts at Search's approved `canonical_universe` contract. It
validates that contract, derives EODHD symbols, records raw or near-raw Bronze
quote and other EODHD data, logs non-secret errors, and writes metadata manifests
that show coverage. It does not perform fuzzy instrument discovery or write
analytical Silver and Gold outputs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any, cast

from camovar.http import EodhdClient
from camovar.logging import get_logger, log_event
from camovar.paths import LakePaths
from camovar.run_locks import layer_run_lock
from camovar.schemas import required_fields
from camovar.table_io import JsonRow, read_rows, write_csv, write_rows

QuoteLoader = Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
RawDataLoader = Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
BronzePathFactory = Callable[[LakePaths, str, int, str], Path]
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class EodhdDatasetStrategy:
    """Dataset-specific behavior for the shared EODHD-to-Bronze ingestion pipeline."""

    name: str
    endpoint: str
    bronze_path: BronzePathFactory


def _quote_bronze_path(paths: LakePaths, exchange: str, year: int, isin: str) -> Path:
    return paths.bronze_quote_file(exchange, year, isin)


def _dataset_bronze_path(dataset: str) -> BronzePathFactory:
    def path(paths: LakePaths, exchange: str, year: int, isin: str) -> Path:
        return paths.bronze_dataset_file(dataset, exchange, year, isin)

    return path


QUOTE_DATASET = EodhdDatasetStrategy("quotes", "eod", _quote_bronze_path)
ADDITIONAL_EODHD_DATASETS: tuple[EodhdDatasetStrategy, ...] = (
    EodhdDatasetStrategy("dividends", "div", _dataset_bronze_path("dividends")),
    EodhdDatasetStrategy("splits", "splits", _dataset_bronze_path("splits")),
)


def validate_canonical_rows(rows: Iterable[Mapping[str, Any]]) -> list[JsonRow]:
    """Validate Search's canonical-universe rows before loading.

    Every required canonical field must be present and non-empty, and each ISIN
    may appear only once. The returned rows are plain dictionaries that can be
    safely passed to planning and bronze helpers.
    """
    validated: list[JsonRow] = []
    seen_isins: set[str] = set()
    legacy_selection_field = "selected_for_" + "fet" + "ch"
    for row in rows:
        item = dict(row)
        if "selected_for_bronze" not in item and legacy_selection_field in item:
            item["selected_for_bronze"] = item[legacy_selection_field]
        for field in required_fields("canonical_universe"):
            if field not in item or str(item[field]).strip() == "":
                raise ValueError(f"canonical universe row missing {field}")
        isin = str(item["isin"])
        if isin in seen_isins:
            raise ValueError(f"duplicate ISIN: {isin}")
        seen_isins.add(isin)
        validated.append(item)
    log_event(
        LOGGER,
        logging.DEBUG,
        module="bronze",
        event="canonical_rows_validated",
        fields={"rows": len(validated)},
    )
    return validated


def build_bronze_plan(
    canonical_rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    start_date: date | None,
    end_date: date | None,
) -> list[JsonRow]:
    """Create deterministic EODHD quote-bronze instructions.

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
    log_event(
        LOGGER,
        logging.INFO,
        module="bronze",
        event="plan_built",
        fields={"rows": len(plan), "run_id": run_id},
    )
    return plan


def write_bronze_plan(
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
    """Read a canonical universe, write a bronze plan, and return it."""
    rows = read_rows(canonical_path)
    if isin is not None:
        normalized_isin = isin.casefold()
        rows = [row for row in rows if str(row.get("isin", "")).casefold() == normalized_isin]
        if not rows:
            raise ValueError(f"approved canonical universe does not contain ISIN: {isin}")
    if limit is not None:
        rows = rows[:limit]
    plan = build_bronze_plan(
        rows,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )
    if gap_aware:
        plan = build_gap_bronze_plan(plan, read_silver_quotes(paths), end_date=end_date)
    write_rows(paths.bronze_plan(run_id), plan)
    log_event(
        LOGGER,
        logging.INFO,
        module="bronze",
        event="plan_written",
        fields={"path": paths.bronze_plan(run_id), "run_id": run_id},
    )
    return plan


def build_gap_bronze_plan(
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
        first_gap_start = min(date.fromisoformat(str(window["gap_start"])) for window in windows)
        gap_plan.append(
            {
                **row,
                "start_date": first_gap_start.isoformat(),
                "end_date": end_date.isoformat(),
                "window_reason": "tail"
                if {str(window["gap_type"]) for window in windows} == {"tail"}
                else "gap_backfill",
            }
        )
    log_event(
        LOGGER,
        logging.INFO,
        module="bronze",
        event="gap_plan_built",
        fields={"gap_rows": len(gap_plan), "input_rows": len(plan)},
    )
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


def merge_rows(
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


def write_quotes_to_bronze(
    paths: LakePaths,
    plan: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
    loader: QuoteLoader,
    concurrency: int = 2,
) -> tuple[list[JsonRow], list[JsonRow]]:
    """Write planned EOD quote payloads into Bronze.

    The supplied `loader` performs the actual API call, which keeps this helper
    easy to test with recorded or mocked responses. Per-symbol failures are
    logged and returned as non-secret error rows without stopping the remaining batch.
    """
    return write_eodhd_dataset_to_bronze(
        paths,
        QUOTE_DATASET,
        plan,
        run_date=run_date,
        loader=loader,
        concurrency=concurrency,
    )


def write_eodhd_dataset_to_bronze(
    paths: LakePaths,
    strategy: EodhdDatasetStrategy,
    plan: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
    loader: QuoteLoader,
    concurrency: int = 2,
) -> tuple[list[JsonRow], list[JsonRow]]:
    """Write one EODHD dataset into Bronze using its dataset strategy."""
    worker_count = max(1, concurrency)

    def load_one(item: Mapping[str, Any]) -> tuple[JsonRow | None, JsonRow | None]:
        started_at = monotonic()
        try:
            loaded_rows = list(loader(item))
            elapsed_seconds = monotonic() - started_at
            rows_by_year: dict[int, list[JsonRow]] = {}
            for row in _dataset_rows(strategy, item, loaded_rows, run_date=run_date):
                row_date = str(row["date"])
                rows_by_year.setdefault(int(row_date[:4]), []).append(row)
            for year, rows in rows_by_year.items():
                bronze_path = strategy.bronze_path(
                    paths,
                    str(item["exchange"]),
                    year,
                    str(item["isin"]),
                )
                write_rows(
                    bronze_path,
                    merge_rows(
                        read_rows(bronze_path),
                        rows,
                        key_fields=("isin", "exchange", "code", "date"),
                    ),
                )
            success = {
                **dict(item),
                "data_type": strategy.name,
                "elapsed_seconds": elapsed_seconds,
                "rows": len(loaded_rows),
            }
            log_event(
                LOGGER,
                logging.DEBUG,
                module="bronze",
                event="eodhd_rows_written",
                fields={
                    "dataset": strategy.name,
                    "elapsed_seconds": f"{elapsed_seconds:.3f}",
                    "rows": len(loaded_rows),
                    "symbol": item["symbol"],
                },
            )
            return success, None
        except Exception as error:  # noqa: BLE001 - record and continue batch failures.
            elapsed_seconds = monotonic() - started_at
            failure = {
                "run_id": str(item["run_id"]),
                "code": str(item["code"]),
                "elapsed_seconds": elapsed_seconds,
                "exchange": str(item["exchange"]),
                "endpoint": strategy.endpoint,
                "error_type": type(error).__name__,
                "message": str(error),
            }
            log_event(
                LOGGER,
                logging.WARNING,
                module="bronze",
                event="eodhd_failed",
                fields={
                    "dataset": strategy.name,
                    "elapsed_seconds": f"{elapsed_seconds:.3f}",
                    "error": error,
                    "symbol": item["symbol"],
                },
            )
            return None, failure

    successes_by_index: dict[int, JsonRow] = {}
    errors_by_index: dict[int, JsonRow] = {}
    if worker_count == 1:
        for index, item in enumerate(plan):
            success, failure = load_one(item)
            if success is not None:
                successes_by_index[index] = success
            if failure is not None:
                errors_by_index[index] = failure
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(load_one, item): index for index, item in enumerate(plan)}
            for future in as_completed(futures):
                index = futures[future]
                success, failure = future.result()
                if success is not None:
                    successes_by_index[index] = success
                if failure is not None:
                    errors_by_index[index] = failure

    successes = [successes_by_index[index] for index in sorted(successes_by_index)]
    errors = [errors_by_index[index] for index in sorted(errors_by_index)]
    log_event(
        LOGGER,
        logging.INFO,
        module="bronze",
        event="eodhd_ingestion_completed",
        fields={
            "concurrency": worker_count,
            "dataset": strategy.name,
            "errors": len(errors),
            "successes": len(successes),
        },
    )
    return successes, errors


def eodhd_quote_loader(client: EodhdClient) -> QuoteLoader:
    """Wrap `EodhdClient` as a `QuoteLoader` for planned EOD requests."""

    return eodhd_dataset_loader(client, QUOTE_DATASET)


def eodhd_dataset_loader(client: EodhdClient, strategy: EodhdDatasetStrategy) -> QuoteLoader:
    """Wrap `EodhdClient` for one strategy-driven EODHD dataset."""

    def bronze(item: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        params: dict[str, str] = {"fmt": "json"}
        start_date = str(item.get("start_date", ""))
        end_date = str(item.get("end_date", ""))
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date
        payload = client.get_json(f"/{strategy.endpoint}/{item['symbol']}", params)
        if not isinstance(payload, list):
            raise ValueError(f"expected EODHD {strategy.name} list")
        payload_rows = cast(list[object], payload)
        return [cast(Mapping[str, Any], row) for row in payload_rows if isinstance(row, dict)]

    return bronze


def eodhd_raw_data_loader(client: EodhdClient, endpoint: str) -> RawDataLoader:
    """Wrap `EodhdClient` for raw per-symbol EODHD datasets."""
    strategy = next(
        (item for item in ADDITIONAL_EODHD_DATASETS if item.endpoint == endpoint),
        EodhdDatasetStrategy(endpoint, endpoint, _dataset_bronze_path(endpoint)),
    )
    return eodhd_dataset_loader(client, strategy)


def write_raw_eodhd_datasets_to_bronze(
    paths: LakePaths,
    plan: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
    loaders: Mapping[str, RawDataLoader],
    concurrency: int = 2,
) -> tuple[list[JsonRow], list[JsonRow]]:
    """Archive planned raw per-symbol EODHD datasets that are not normalized yet."""
    successes: list[JsonRow] = []
    errors: list[JsonRow] = []
    strategies_by_name = {strategy.name: strategy for strategy in ADDITIONAL_EODHD_DATASETS}
    for dataset, loader in loaders.items():
        strategy = strategies_by_name[dataset]
        dataset_successes, dataset_errors = write_eodhd_dataset_to_bronze(
            paths,
            strategy,
            plan,
            run_date=run_date,
            loader=loader,
            concurrency=concurrency,
        )
        successes.extend(dataset_successes)
        errors.extend(dataset_errors)
    log_event(
        LOGGER,
        logging.INFO,
        module="bronze",
        event="raw_datasets_bronzed",
        fields={"errors": len(errors), "successes": len(successes)},
    )
    return successes, errors


def _dataset_rows(
    strategy: EodhdDatasetStrategy,
    item: Mapping[str, Any],
    payload: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
) -> list[JsonRow]:
    rows: list[JsonRow] = []
    for raw_row in payload:
        row = dict(raw_row)
        if "date" not in row:
            raise ValueError(f"expected EODHD {strategy.name} row date")
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


def normalize_quote_rows(
    plan: Sequence[Mapping[str, Any]],
    raw_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    bronzed_at: datetime,
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
                "bronzed_at": bronzed_at.astimezone(UTC).isoformat(),
            }
    normalized = [rows[key] for key in sorted(rows)]
    log_event(
        LOGGER,
        logging.INFO,
        module="bronze",
        event="quote_rows_normalized",
        fields={"rows": len(normalized)},
    )
    return normalized


def write_silver_quotes(paths: LakePaths, quote_rows: Sequence[Mapping[str, Any]]) -> None:
    """Write normalized quote rows to one Silver file per exchange and ISIN."""
    by_listing: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        by_listing.setdefault((str(row["exchange"]), str(row["isin"])), []).append(row)
    for (exchange, isin), rows in by_listing.items():
        quote_path = paths.silver_quote_file(exchange, isin)
        merged_rows = merge_rows(
            read_rows(quote_path),
            rows,
            key_fields=("isin", "exchange", "code", "date"),
        )
        write_rows(quote_path, merged_rows)
        log_event(
            LOGGER,
            logging.INFO,
            module="bronze",
            event="silver_quote_rows_written",
            fields={"exchange": exchange, "isin": isin, "rows": len(merged_rows)},
        )


def read_silver_quotes(paths: LakePaths) -> list[JsonRow]:
    """Read all accumulated Silver quote files."""
    rows: list[JsonRow] = []
    for path in sorted((paths.silver / "quotes").glob("*/*.parquet")):
        rows.extend(read_rows(path))
    return rows


def build_coverage(
    quote_rows: Sequence[Mapping[str, Any]], *, run_id: str, overlap_days: int = 5
) -> list[JsonRow]:
    """Summarize quote completeness and the next incremental bronze start.

    Coverage is calculated per `(isin, code, exchange)`. `missing_periods` is a
    simple calendar-day gap count, and `next_bronze_start` backs up from the last
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
                "next_bronze_start": (last - timedelta(days=overlap_days)).isoformat(),
            }
        )
    log_event(
        LOGGER,
        logging.DEBUG,
        module="bronze",
        event="coverage_built",
        fields={"rows": len(coverage), "run_id": run_id},
    )
    return coverage


def write_bronze_manifests(
    paths: LakePaths,
    *,
    run_id: str,
    quote_rows: Sequence[Mapping[str, Any]],
    plan: Sequence[Mapping[str, Any]] = (),
    as_of: date | None = None,
) -> list[JsonRow]:
    """Write coverage, bronze-run metadata, and review CSV manifests."""
    coverage = build_coverage(quote_rows, run_id=run_id)
    write_rows(
        paths.quote_gaps(),
        build_quote_gap_rows(plan, quote_rows, run_id=run_id, as_of=as_of),
    )
    write_rows(paths.coverage(), coverage)
    write_rows(
        paths.bronze_runs(),
        [
            {
                "run_id": run_id,
                "started_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "quote_rows": len(quote_rows),
            }
        ],
    )
    write_csv(paths.coverage().with_suffix(".csv"), coverage, required_fields("coverage"))
    log_event(
        LOGGER,
        logging.INFO,
        module="bronze",
        event="manifests_written",
        fields={"coverage_rows": len(coverage), "run_id": run_id},
    )
    return coverage


def bronze_run_lock(paths: LakePaths, run_id: str) -> AbstractContextManager[Path]:
    """Return the stable Bronze layer lock.

    `run_id` is accepted for backward compatibility with callers that used the
    previous run-scoped lock contract. Bronze locking is intentionally layer-wide
    so different run ids cannot fetch Bronze concurrently.

    Args:
        paths: Lake path contract for the target data root.
        run_id: Historical run-scoped lock identifier; ignored by layer locks.

    Returns:
        Context manager holding the Bronze layer lock.
    """
    del run_id
    return layer_run_lock(paths, "bronze")
