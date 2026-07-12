"""Search normalization, canonical selection, and universe approval."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from founder.paths import LakePaths
from founder.schemas import required_fields
from founder.table_io import JsonRow, read_json, read_rows, write_csv, write_json, write_rows


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def normalize_candidate(
    raw: Mapping[str, Any],
    *,
    search_run_id: str,
    query: str,
    source_endpoint: str,
    found_at: datetime,
) -> JsonRow:
    code = str(raw.get("Code", raw.get("code", ""))).strip()
    exchange = str(raw.get("Exchange", raw.get("exchange", ""))).strip()
    name = str(raw.get("Name", raw.get("name", ""))).strip()
    return {
        "search_run_id": search_run_id,
        "query": query,
        "source_endpoint": source_endpoint,
        "code": code,
        "exchange": exchange,
        "instrument_type": str(raw.get("Type", raw.get("type", ""))).strip(),
        "country": str(raw.get("Country", raw.get("country", ""))).strip(),
        "currency": str(raw.get("Currency", raw.get("currency", ""))).strip(),
        "isin": str(raw.get("Isin", raw.get("isin", ""))).strip(),
        "name": name,
        "normalized_name": normalize_name(name),
        "found_at": found_at.astimezone(UTC).isoformat(),
    }


def write_search_run(
    raw_candidates: Sequence[Mapping[str, Any]],
    *,
    paths: LakePaths,
    search_run_id: str,
    query: str = "UCITS ETF",
    run_date: date | None = None,
    found_at: datetime | None = None,
) -> list[JsonRow]:
    checked_date = run_date or date.today()
    checked_at = found_at or datetime.now(UTC)
    bronze_path = paths.bronze_search_run(checked_date.isoformat()) / f"{search_run_id}.json"
    write_json(
        bronze_path,
        {"search_run_id": search_run_id, "query": query, "responses": list(raw_candidates)},
    )
    rows = [
        normalize_candidate(
            candidate,
            search_run_id=search_run_id,
            query=query,
            source_endpoint="exchange-symbol-list",
            found_at=checked_at,
        )
        for candidate in raw_candidates
    ]
    write_rows(paths.candidates(search_run_id), rows)
    return rows


def select_canonical(candidates: Iterable[Mapping[str, Any]]) -> list[JsonRow]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    missing_isin = 0
    for candidate in candidates:
        isin = str(candidate.get("isin", "")).strip()
        if not isin:
            missing_isin += 1
            continue
        grouped.setdefault(isin, []).append(candidate)

    selected: list[JsonRow] = []
    for isin in sorted(grouped):
        rows = grouped[isin]
        chosen = sorted(
            rows,
            key=lambda row: (
                0 if str(row.get("exchange", "")).upper() == "XETRA" else 1,
                str(row.get("exchange", "")),
                str(row.get("code", "")),
            ),
        )[0]
        reason = (
            "preferred_xetra"
            if str(chosen.get("exchange", "")).upper() == "XETRA"
            else "fallback_exchange"
        )
        selected.append(
            {
                "search_run_id": str(chosen.get("search_run_id", "")),
                "isin": isin,
                "code": str(chosen.get("code", "")),
                "exchange": str(chosen.get("exchange", "")),
                "instrument_type": str(chosen.get("instrument_type", "")),
                "country": str(chosen.get("country", "")),
                "currency": str(chosen.get("currency", "")),
                "name": str(chosen.get("name", "")),
                "normalized_name": str(chosen.get("normalized_name", "")),
                "selection_reason": reason,
                "selected_for_fetch": True,
            }
        )
    if missing_isin:
        selected.sort(key=lambda row: str(row["isin"]))
    return selected


def write_canonical_universe(paths: LakePaths, search_run_id: str) -> list[JsonRow]:
    candidates = read_rows(paths.candidates(search_run_id))
    canonical = select_canonical(candidates)
    write_rows(paths.canonical_universe(search_run_id), canonical)
    write_json(
        paths.search_summary(search_run_id),
        {
            "search_run_id": search_run_id,
            "candidate_rows": len(candidates),
            "canonical_rows": len(canonical),
            "missing_isin_rows": sum(
                1 for row in candidates if not str(row.get("isin", "")).strip()
            ),
        },
    )
    write_csv(paths.review_csv(search_run_id), canonical, required_fields("canonical_universe"))
    return canonical


def approve_universe(paths: LakePaths, search_run_id: str) -> JsonRow:
    pointer = {
        "search_run_id": search_run_id,
        "canonical_universe_path": str(paths.canonical_universe(search_run_id)),
        "approved_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    write_json(paths.current_universe(), pointer)
    return pointer


def resolve_current_universe(paths: LakePaths) -> Path:
    payload = read_json(paths.current_universe())
    return Path(str(payload["canonical_universe_path"]))
