"""Fetch the full EODHD ISIN metadata universe into one reference artifact."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from camovar.http import EodhdHttpError
from camovar.paths import LakePaths
from camovar.schemas import validate_rows
from camovar.table_io import JsonRow, write_json, write_rows


class EodhdJsonClient(Protocol):
    """Protocol for EODHD JSON clients used by this module."""

    def get_json(
        self,
        path: str,
        params: Mapping[str, str | int | float] | None = None,
    ) -> object: ...


@dataclass(frozen=True)
class AllIsinsFetchResult:
    """Result of a full EODHD ISIN metadata refresh."""

    rows: tuple[JsonRow, ...]
    requested_exchanges: tuple[str, ...]
    skipped_exchanges: tuple[str, ...]


def fetch_all_isins(
    client: EodhdJsonClient,
    *,
    exchange_codes: Sequence[str] = (),
    include_delisted: bool = False,
) -> AllIsinsFetchResult:
    """Fetch and normalize all available ISIN-bearing EODHD listings."""
    explicit_exchanges = bool(exchange_codes)
    resolved_exchanges = tuple(exchange_codes) or _fetch_exchange_codes(client)
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    rows: list[JsonRow] = []
    skipped_exchanges: list[str] = []
    for exchange in resolved_exchanges:
        try:
            payload = client.get_json(
                f"/exchange-symbol-list/{exchange}",
                {"fmt": "json", "delisted": 1 if include_delisted else 0},
            )
        except EodhdHttpError as error:
            if explicit_exchanges or error.status_code not in {403, 404}:
                raise
            skipped_exchanges.append(exchange)
            continue
        rows.extend(
            _normalize_listing(row, source_exchange=exchange, fetched_at=fetched_at)
            for row in _payload_rows(payload)
            if str(row.get("Isin", row.get("isin", ""))).strip()
        )
    return AllIsinsFetchResult(
        rows=tuple(
            sorted(rows, key=lambda row: (str(row["isin"]), str(row["exchange"]), str(row["code"])))
        ),
        requested_exchanges=resolved_exchanges,
        skipped_exchanges=tuple(skipped_exchanges),
    )


def write_all_isins(paths: LakePaths, rows: Sequence[Mapping[str, Any]]) -> list[JsonRow]:
    """Write the reference all-ISIN dataset and manifest."""
    normalized = [dict(row) for row in rows]
    validate_rows("all_isins", normalized)
    write_rows(paths.all_isins(), normalized)
    write_json(
        paths.all_isins_manifest(),
        {
            "dataset": "all_isins",
            "path": str(paths.all_isins()),
            "row_count": len(normalized),
            "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        },
    )
    return normalized


def _fetch_exchange_codes(client: EodhdJsonClient) -> tuple[str, ...]:
    payload = client.get_json("/exchanges-list/", {"fmt": "json"})
    codes: list[str] = []
    for row in _payload_rows(payload):
        code = str(row.get("Code", row.get("code", ""))).strip()
        if code:
            codes.append(code)
    return tuple(sorted(set(codes)))


def _payload_rows(payload: object) -> list[Mapping[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("EODHD payload must be a JSON list")
    rows: list[Mapping[str, Any]] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise ValueError("EODHD payload rows must be objects")
        rows.append(cast(Mapping[str, Any], item))
    return rows


def _normalize_listing(
    raw: Mapping[str, Any],
    *,
    source_exchange: str,
    fetched_at: str,
) -> JsonRow:
    exchange = (
        str(raw.get("Exchange", raw.get("exchange", source_exchange))).strip() or source_exchange
    )
    name = str(raw.get("Name", raw.get("name", ""))).strip()
    return {
        "isin": str(raw.get("Isin", raw.get("isin", ""))).strip(),
        "exchange": exchange,
        "code": str(raw.get("Code", raw.get("code", ""))).strip(),
        "name": name,
        "instrument_type": str(raw.get("Type", raw.get("type", ""))).strip(),
        "country": str(raw.get("Country", raw.get("country", ""))).strip(),
        "currency": str(raw.get("Currency", raw.get("currency", ""))).strip(),
        "source_exchange": source_exchange,
        "fetched_at": fetched_at,
    }
