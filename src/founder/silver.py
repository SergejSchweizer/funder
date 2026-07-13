"""Silver-layer market data builds from Bronze artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from founder.bronze import _merge_rows
from founder.logging import get_logger
from founder.paths import LakePaths
from founder.table_io import JsonRow, read_rows, write_rows

LOGGER = get_logger(__name__)


def read_bronze_quote_rows(paths: LakePaths) -> list[JsonRow]:
    """Read all Bronze quote rows across exchange, year, and ISIN partitions."""
    rows: list[JsonRow] = []
    for path in sorted((paths.bronze / "quotes").glob("*/*/*.parquet")):
        rows.extend(read_rows(path))
    return rows


def build_silver_quote_rows(bronze_rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    """Build deterministic Silver quote rows from Bronze quote rows."""
    rows: dict[tuple[str, str, str, str], JsonRow] = {}
    for raw in bronze_rows:
        quote_date = str(raw["date"])
        isin = str(raw["isin"])
        exchange = str(raw["exchange"])
        code = str(raw["code"])
        run_date = str(raw.get("run_date", quote_date))
        bronzed_at = datetime.fromisoformat(run_date).replace(tzinfo=UTC).isoformat()
        key = (isin, exchange, code, quote_date)
        rows[key] = {
            "run_id": str(raw["run_id"]),
            "isin": isin,
            "code": code,
            "exchange": exchange,
            "date": quote_date,
            "open": float(raw.get("open", raw.get("close", 0.0))),
            "high": float(raw.get("high", raw.get("close", 0.0))),
            "low": float(raw.get("low", raw.get("close", 0.0))),
            "close": float(raw.get("close", 0.0)),
            "adjusted_close": float(raw.get("adjusted_close", raw.get("close", 0.0))),
            "volume": int(raw.get("volume", 0)),
            "currency": str(raw.get("currency", "")),
            "bronzed_at": bronzed_at,
        }
    silver_rows = [rows[key] for key in sorted(rows)]
    LOGGER.info("silver quote rows built rows=%s", len(silver_rows))
    return silver_rows


def write_silver_quotes(paths: LakePaths, quote_rows: Sequence[Mapping[str, Any]]) -> None:
    """Write Silver quote rows to one file per exchange and ISIN."""
    by_listing: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in quote_rows:
        by_listing.setdefault((str(row["exchange"]), str(row["isin"])), []).append(row)
    for (exchange, isin), rows in by_listing.items():
        quote_path = paths.silver_quote_file(exchange, isin)
        merged_rows = _merge_rows(
            read_rows(quote_path),
            rows,
            key_fields=("isin", "exchange", "code", "date"),
        )
        write_rows(quote_path, merged_rows)
        LOGGER.info(
            "silver quote rows written exchange=%s isin=%s rows=%s",
            exchange,
            isin,
            len(merged_rows),
        )


def read_silver_quotes(paths: LakePaths) -> list[JsonRow]:
    """Read all accumulated Silver quote files."""
    rows: list[JsonRow] = []
    for path in sorted((paths.silver / "quotes").glob("*/*.parquet")):
        rows.extend(read_rows(path))
    return rows


def build_silver_quotes(paths: LakePaths) -> list[JsonRow]:
    """Build Silver quotes from all available Bronze quote rows."""
    quote_rows = build_silver_quote_rows(read_bronze_quote_rows(paths))
    write_silver_quotes(paths, quote_rows)
    return read_silver_quotes(paths)
