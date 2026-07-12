"""Search normalization, canonical selection, and universe approval.

The Search module turns broad EODHD discovery payloads into a stable universe
contract for Fetch. It does not download quote history. Its
output is a versioned `canonical_universe` table with one selected listing per
non-empty ISIN, plus review artifacts that make missing identifiers visible.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from founder.logging import get_logger
from founder.paths import LakePaths
from founder.schemas import required_fields
from founder.table_io import JsonRow, read_json, read_rows, write_csv, write_json, write_rows

LOGGER = get_logger(__name__)


def normalize_name(value: str) -> str:
    """Return a case-folded, whitespace-normalized instrument name.

    Use this for deterministic comparisons only. Keep the original `name` field
    for display, review exports, and broker-facing output.
    """
    return " ".join(value.casefold().split())


def normalize_candidate(
    raw: Mapping[str, Any],
    *,
    search_run_id: str,
    query: str,
    source_endpoint: str,
    found_at: datetime,
) -> JsonRow:
    """Convert one raw EODHD candidate payload into the Search row contract.

    The function accepts either EODHD-style keys such as `Code` and `Isin` or
    already-normalized lowercase keys. Missing optional values become empty
    strings so downstream review can count them explicitly.
    """
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
    """Write raw discovery payloads and normalized Search candidates.

    `raw_candidates` should be the collected EODHD search or exchange-symbol-list
    rows for one discovery run. The function writes the raw batch to Bronze,
    writes normalized candidate rows to Silver, and returns the normalized rows.
    Reusing the same `search_run_id` replaces the same deterministic paths.
    """
    checked_date = run_date or date.today()
    checked_at = found_at or datetime.now(UTC)
    LOGGER.debug(
        "writing search run search_run_id=%s query=%s raw_candidates=%s",
        search_run_id,
        query,
        len(raw_candidates),
    )
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
    LOGGER.info("search candidates written search_run_id=%s rows=%s", search_run_id, len(rows))
    return rows


def select_canonical(candidates: Iterable[Mapping[str, Any]]) -> list[JsonRow]:
    """Select one fetchable listing per ISIN.

    Rows without an ISIN are excluded because Fetch requires stable identifiers.
    For duplicate listings, XETRA wins when present; otherwise sorting by
    exchange and code gives a deterministic fallback. Returned rows are sorted by
    ISIN and marked `selected_for_fetch=true`.
    """
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
    LOGGER.debug(
        "canonical selection complete rows=%s missing_isin=%s", len(selected), missing_isin
    )
    return selected


def write_canonical_universe(paths: LakePaths, search_run_id: str) -> list[JsonRow]:
    """Build and persist the canonical universe for a Search run.

    This reads normalized candidates, writes the canonical table, writes a small
    summary with missing-ISIN counts, and exports a CSV for human review before
    Fetch consumes the universe.
    """
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
    LOGGER.info(
        "canonical universe written search_run_id=%s rows=%s", search_run_id, len(canonical)
    )
    return canonical


def approve_universe(
    paths: LakePaths, search_run_id: str, *, approved_at: datetime | None = None
) -> JsonRow:
    """Mark a canonical universe as the active Fetch input.

    Approval writes `current_universe.json` in Silver metadata with the selected Search run
    id and canonical-universe path. Fetch can resolve this pointer without
    knowing how Search produced the universe.
    """
    pointer = {
        "search_run_id": search_run_id,
        "canonical_universe_path": str(paths.canonical_universe(search_run_id)),
        "approved_at": (approved_at or datetime.now(UTC)).replace(microsecond=0).isoformat(),
    }
    write_json(paths.current_universe(), pointer)
    LOGGER.info("universe approved search_run_id=%s", search_run_id)
    return pointer


def resolve_current_universe(paths: LakePaths) -> Path:
    """Return the approved canonical-universe path from Silver metadata."""
    payload = read_json(paths.current_universe())
    canonical_path = Path(str(payload["canonical_universe_path"]))
    if not canonical_path.exists():
        raise FileNotFoundError(f"approved canonical universe does not exist: {canonical_path}")
    return canonical_path
