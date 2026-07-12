"""Fetch planning, quote normalization, fundamentals, and coverage manifests."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from founder.http import EodhdClient
from founder.paths import LakePaths
from founder.schemas import required_fields
from founder.table_io import JsonRow, read_rows, write_csv, write_json, write_rows

QuoteFetcher = Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
FundamentalsFetcher = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def validate_canonical_rows(rows: Iterable[Mapping[str, Any]]) -> list[JsonRow]:
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
    return validated


def build_fetch_plan(
    canonical_rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    start_date: date,
    end_date: date,
) -> list[JsonRow]:
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
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
        )
    return plan


def write_fetch_plan(
    paths: LakePaths,
    canonical_path: Path,
    *,
    run_id: str,
    start_date: date,
    end_date: date,
) -> list[JsonRow]:
    plan = build_fetch_plan(
        read_rows(canonical_path),
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )
    write_rows(paths.fetch_plan(run_id), plan)
    return plan


def fetch_quotes_to_bronze(
    paths: LakePaths,
    plan: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
    fetcher: QuoteFetcher,
) -> tuple[list[JsonRow], list[JsonRow]]:
    successes: list[JsonRow] = []
    errors: list[JsonRow] = []
    for item in plan:
        try:
            quotes = list(fetcher(item))
            payload = {"plan": dict(item), "quotes": quotes}
            write_json(
                paths.bronze_quotes_run(run_date.isoformat()) / f"{item['symbol']}.json", payload
            )
            successes.append({**dict(item), "rows": len(quotes)})
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
    write_rows(paths.errors(), errors)
    return successes, errors


def eodhd_quote_fetcher(client: EodhdClient) -> QuoteFetcher:
    def fetch(item: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        payload = client.get_json(
            f"/eod/{item['symbol']}",
            {"from": str(item["start_date"]), "to": str(item["end_date"]), "fmt": "json"},
        )
        if not isinstance(payload, list):
            raise ValueError("expected EODHD quote list")
        return [row for row in payload if isinstance(row, dict)]

    return fetch


def normalize_quote_rows(
    plan: Sequence[Mapping[str, Any]],
    raw_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    fetched_at: datetime,
    currency_by_isin: Mapping[str, str] | None = None,
) -> list[JsonRow]:
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
    return [rows[key] for key in sorted(rows)]


def write_silver_quotes(paths: LakePaths, quote_rows: Sequence[Mapping[str, Any]]) -> None:
    by_year: dict[int, list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        by_year.setdefault(int(str(row["date"])[:4]), []).append(row)
    for year, rows in by_year.items():
        write_rows(paths.silver_quotes_year(year), rows)


def fetch_fundamentals_to_silver(
    paths: LakePaths,
    plan: Sequence[Mapping[str, Any]],
    *,
    run_date: date,
    fetcher: FundamentalsFetcher,
) -> list[JsonRow]:
    profiles: list[JsonRow] = []
    for item in plan:
        payload = dict(fetcher(item))
        write_json(
            paths.bronze_fundamentals_run(run_date.isoformat()) / f"{item['symbol']}.json", payload
        )
        general = payload.get("General", {})
        if not isinstance(general, dict):
            general = {}
        profiles.append(
            {
                "run_id": str(item["run_id"]),
                "isin": str(item["isin"]),
                "code": str(item["code"]),
                "exchange": str(item["exchange"]),
                "name": str(general.get("Name", "")),
                "currency": str(general.get("CurrencyCode", "")),
            }
        )
    write_rows(paths.silver_fundamentals_profile(), profiles)
    return profiles


def build_coverage(
    quote_rows: Sequence[Mapping[str, Any]], *, run_id: str, overlap_days: int = 5
) -> list[JsonRow]:
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
    return coverage


def write_fetch_manifests(
    paths: LakePaths, *, run_id: str, quote_rows: Sequence[Mapping[str, Any]]
) -> list[JsonRow]:
    coverage = build_coverage(quote_rows, run_id=run_id)
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
    return coverage
