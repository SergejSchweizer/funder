"""Operational workflows behind the Founder CLI modules."""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from founder.bivariate_statistics import write_bivariate_statistics
from founder.bronze import (
    ADDITIONAL_EODHD_DATASETS,
    QUOTE_DATASET,
    build_gap_bronze_plan,
    eodhd_dataset_loader,
    write_bronze_manifests,
    write_quotes_to_bronze,
    write_raw_eodhd_datasets_to_bronze,
)
from founder.config import load_eodhd_config
from founder.fetch_all_isins import fetch_all_isins, write_all_isins
from founder.http import EodhdClient
from founder.logging import get_logger
from founder.metadata_filter import run_metadata_filter
from founder.paths import LakePaths
from founder.search import (
    approve_universe,
    normalize_name,
    write_canonical_universe,
    write_search_run,
)
from founder.selection_filters import parse_predicates
from founder.silver import build_silver_quotes, read_silver_quotes
from founder.table_io import read_json, read_rows, write_rows
from founder.univariate_filter import run_univariate_filter, selection_rows
from founder.univariate_statistics import (
    DEFAULT_CONFIDENCE_LEVEL,
    build_quote_returns,
    write_univariate_statistics,
)

LOGGER = get_logger(__name__)


def generated_run_id(prefix: str, value: str | None = None, run_date: date | None = None) -> str:
    """Build deterministic date-scoped run ids for user-facing module runs."""
    parts = [prefix]
    if value:
        parts.append(_slug(value))
    parts.append((run_date or date.today()).isoformat().replace("-", ""))
    return "-".join(parts)


def run_search_workflow(
    *,
    root: Path,
    input_path: Path,
    query: str,
    search_run_id: str | None = None,
    run_date: date | None = None,
    approve: bool = True,
) -> dict[str, Any]:
    """Run Search and optionally approve the canonical universe pointer."""
    paths = LakePaths(root=root)
    resolved_run_date = run_date or date.today()
    resolved_search_run_id = search_run_id or generated_run_id("search", query, resolved_run_date)
    raw_candidates = _filter_candidates(_read_candidate_payload(input_path), query)
    LOGGER.info(
        "running search query=%s search_run_id=%s input=%s candidates=%s",
        query,
        resolved_search_run_id,
        input_path,
        len(raw_candidates),
    )
    candidates = write_search_run(
        raw_candidates,
        paths=paths,
        search_run_id=resolved_search_run_id,
        query=query,
        run_date=resolved_run_date,
        found_at=datetime.combine(resolved_run_date, datetime.min.time(), tzinfo=UTC),
    )
    canonical = write_canonical_universe(paths, resolved_search_run_id)
    summary: dict[str, Any] = {
        "candidate_rows": len(candidates),
        "canonical_rows": len(canonical),
        "query": query,
        "search_run_id": resolved_search_run_id,
    }
    if approve:
        summary["approved_universe"] = approve_universe(paths, resolved_search_run_id)
    LOGGER.info(
        "search complete search_run_id=%s canonical_rows=%s",
        resolved_search_run_id,
        len(canonical),
    )
    return summary


def run_fetch_all_isins_workflow(
    *,
    root: Path,
    exchange_codes: Sequence[str] = (),
    include_delisted: bool = False,
) -> dict[str, Any]:
    """Fetch and persist the all-ISIN reference dataset."""
    paths = LakePaths(root=root)
    client = EodhdClient(load_eodhd_config())
    fetch_result = fetch_all_isins(
        client,
        exchange_codes=exchange_codes,
        include_delisted=include_delisted,
    )
    written = write_all_isins(paths, fetch_result.rows)
    return {
        "all_isins_rows": len(written),
        "exchange_count": len({str(row["source_exchange"]) for row in written}),
        "path": str(paths.all_isins()),
        "requested_exchange_count": len(fetch_result.requested_exchanges),
        "skipped_exchange_count": len(fetch_result.skipped_exchanges),
        "skipped_exchanges": list(fetch_result.skipped_exchanges),
    }


def run_fetch_all_quotes_workflow(
    *,
    root: Path,
    run_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
    isin: str | None = None,
    gap_aware: bool = True,
    include_raw_datasets: bool = True,
    concurrency: int = 2,
) -> dict[str, Any]:
    """Fetch Bronze quote inputs for the latest Metadata Filter selection."""
    paths = LakePaths(root=root)
    resolved_end_date = end_date or date.today()
    resolved_run_id = run_id or generated_run_id("fetch-all-quotes", run_date=resolved_end_date)
    selection_id = _latest_metadata_selection_id(paths)
    selection_rows = _metadata_selection_rows(paths, selection_id)
    if isin is not None:
        normalized_isin = isin.casefold()
        selection_rows = [
            row for row in selection_rows if str(row.get("isin", "")).casefold() == normalized_isin
        ]
        if not selection_rows:
            raise ValueError(f"metadata-filter selection does not contain ISIN: {isin}")
    if limit is not None:
        selection_rows = selection_rows[:limit]
    plan = _build_fetch_all_quotes_plan(
        selection_rows,
        run_id=resolved_run_id,
        start_date=start_date,
        end_date=resolved_end_date,
    )
    if gap_aware:
        plan = build_gap_bronze_plan(plan, read_silver_quotes(paths), end_date=resolved_end_date)
    write_rows(paths.bronze_plan(resolved_run_id), plan)
    client = EodhdClient(load_eodhd_config())
    quote_successes, quote_errors = write_quotes_to_bronze(
        paths,
        plan,
        run_date=resolved_end_date,
        loader=eodhd_dataset_loader(client, QUOTE_DATASET),
        concurrency=concurrency,
    )
    raw_successes: list[dict[str, Any]] = []
    raw_errors: list[dict[str, Any]] = []
    if include_raw_datasets:
        raw_successes, raw_errors = write_raw_eodhd_datasets_to_bronze(
            paths,
            plan,
            run_date=resolved_end_date,
            loaders={
                strategy.name: eodhd_dataset_loader(client, strategy)
                for strategy in ADDITIONAL_EODHD_DATASETS
            },
            concurrency=concurrency,
        )
    silver_rows = build_silver_quotes(paths, concurrency=concurrency)
    coverage = write_bronze_manifests(
        paths,
        run_id=resolved_run_id,
        quote_rows=silver_rows,
        plan=plan,
        as_of=resolved_end_date,
    )
    LOGGER.info(
        "fetch-all-quotes complete run_id=%s plan_rows=%s quote_successes=%s quote_errors=%s",
        resolved_run_id,
        len(plan),
        len(quote_successes),
        len(quote_errors),
    )
    return {
        "coverage_rows": len(coverage),
        "raw_dataset_errors": len(raw_errors),
        "raw_dataset_successes": len(raw_successes),
        "quote_errors": len(quote_errors),
        "quote_successes": len(quote_successes),
        "run_id": resolved_run_id,
        "selection_id": selection_id,
        "selected_listing_count": len(selection_rows),
        "silver_quote_rows": len(silver_rows),
    }


def _build_fetch_all_quotes_plan(
    rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    start_date: date | None,
    end_date: date | None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
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
    return plan


def run_metadata_filter_workflow(
    *,
    root: Path,
    predicates: Sequence[str],
    name_contains: Sequence[str] = (),
    selection_name: str | None = None,
) -> dict[str, Any]:
    """Run Metadata Filter over the reference all-ISIN dataset."""
    resolved_predicates = tuple(predicates) + tuple(
        f"name~{search_text}" for search_text in name_contains
    )
    if not resolved_predicates:
        raise ValueError("metadata-filter requires at least one --where or --name-contains")
    return run_metadata_filter(
        LakePaths(root=root),
        parse_predicates(resolved_predicates),
        name=selection_name,
    )


def run_univariate_statistics_workflow(
    *,
    root: Path,
    selection_id: str | None = None,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    concurrency: int | None = None,
) -> dict[str, Any]:
    """Build reusable per-listing statistics for one Metadata Filter selection."""
    paths = LakePaths(root=root)
    resolved_selection_id = selection_id or _current_metadata_selection_id(paths)
    LOGGER.info(
        "running univariate statistics root=%s selection_id=%s",
        root,
        resolved_selection_id,
    )
    selected_rows = _metadata_selection_rows(paths, resolved_selection_id)
    quotes = _filter_quotes_to_selection(read_silver_quotes(paths), selected_rows)
    dividends = _filter_quotes_to_selection(_read_bronze_dividends(paths), selected_rows)
    rows = write_univariate_statistics(
        paths,
        quotes,
        dividend_rows=dividends,
        confidence_level=confidence_level,
        concurrency=concurrency,
    )
    workers = _worker_count(concurrency)
    LOGGER.info("univariate statistics complete root=%s rows=%s", root, len(rows))
    return {
        "quote_rows": len(quotes),
        "dividend_rows": len(dividends),
        "concurrency": workers,
        "selected_listing_count": len(selected_rows),
        "selection_id": resolved_selection_id,
        "univariate_statistics_rows": len(rows),
    }


def run_univariate_filter_workflow(
    *,
    root: Path,
    predicates: Sequence[str],
    selection_name: str | None = None,
) -> dict[str, Any]:
    """Run Univariate Filter over persisted Gold univariate statistics."""
    return run_univariate_filter(
        LakePaths(root=root),
        parse_predicates(predicates),
        name=selection_name,
    )


def run_bivariate_statistics_workflow(
    *,
    root: Path,
    selection_id: str | None = None,
    concurrency: int | None = None,
) -> dict[str, Any]:
    """Build reusable pairwise statistics from existing Silver quotes."""
    paths = LakePaths(root=root)
    resolved_selection_id = selection_id or _current_univariate_filter_selection_id(paths)
    LOGGER.info(
        "running bivariate statistics root=%s selection_id=%s",
        root,
        resolved_selection_id,
    )
    quotes = read_silver_quotes(paths)
    quotes = _filter_quotes_to_selection(quotes, selection_rows(paths, resolved_selection_id))
    returns = build_quote_returns(quotes)
    rows = write_bivariate_statistics(paths, returns, concurrency=concurrency)
    workers = _worker_count(concurrency)
    LOGGER.info("bivariate statistics complete root=%s rows=%s", root, len(rows))
    return {
        "bivariate_statistics_rows": len(rows),
        "concurrency": workers,
        "quote_rows": len(quotes),
        "return_rows": len(returns),
        "selection_id": resolved_selection_id,
    }


def _filter_quotes_to_selection(
    quotes: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected = {(str(row["isin"]), str(row["exchange"]), str(row["code"])) for row in selected_rows}
    return [
        dict(row)
        for row in quotes
        if (str(row["isin"]), str(row["exchange"]), str(row["code"])) in selected
    ]


def _metadata_selection_rows(paths: LakePaths, selection_id: str) -> list[dict[str, Any]]:
    selection_path = paths.metadata_filter_isins(selection_id)
    if not selection_path.exists():
        raise FileNotFoundError(f"metadata-filter selection does not exist: {selection_id}")
    return read_rows(selection_path)


def _read_bronze_dividends(paths: LakePaths) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((paths.bronze / "dividends").glob("*/*/*.parquet")):
        rows.extend(read_rows(path))
    return rows


def _worker_count(concurrency: int | None) -> int:
    if concurrency is not None:
        return max(1, concurrency)
    return max(1, os.cpu_count() or 1)


def _current_metadata_selection_id(paths: LakePaths) -> str:
    pointer_path = paths.current_metadata_filter_selection()
    if pointer_path.exists():
        return str(read_json(pointer_path)["selection_id"])
    return _latest_metadata_selection_id(paths)


def _current_univariate_filter_selection_id(paths: LakePaths) -> str:
    pointer_path = paths.current_univariate_filter_selection()
    if pointer_path.exists():
        return str(read_json(pointer_path)["selection_id"])
    return _latest_univariate_filter_selection_id(paths)


def _latest_metadata_selection_id(paths: LakePaths) -> str:
    manifests = sorted((paths.silver / "metadata_filter").glob("selection_id=*/manifest.json"))
    latest: tuple[str, str] | None = None
    for manifest_path in manifests:
        manifest = read_json(manifest_path)
        selection_id = str(manifest["selection_id"])
        created_at = str(manifest.get("created_at", ""))
        candidate = (created_at, selection_id)
        if latest is None or candidate > latest:
            latest = candidate
    if latest is None:
        raise FileNotFoundError(
            "metadata-filter selection does not exist; run metadata-filter first"
        )
    return latest[1]


def _latest_univariate_filter_selection_id(paths: LakePaths) -> str:
    manifests = sorted((paths.silver / "univariate_filter").glob("selection_id=*/manifest.json"))
    latest: tuple[str, str] | None = None
    for manifest_path in manifests:
        manifest = read_json(manifest_path)
        selection_id = str(manifest["selection_id"])
        created_at = str(manifest.get("created_at", ""))
        candidate = (created_at, selection_id)
        if latest is None or candidate > latest:
            latest = candidate
    if latest is None:
        raise FileNotFoundError(
            "univariate-filter selection does not exist; run univariate-filter first"
        )
    return latest[1]


def _slug(value: str) -> str:
    slug = "-".join(normalize_name(value).replace("_", "-").split())
    return slug or "run"


def _read_candidate_payload(path: Path) -> list[dict[str, Any]]:
    if path.suffix.casefold() == ".csv":
        with path.open(encoding="utf-8", newline="") as csv_file:
            return [dict(row) for row in csv.DictReader(csv_file)]
    payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if isinstance(payload, dict):
        payload_by_name = cast(dict[str, object], payload)
        payload = payload_by_name.get("responses", payload_by_name.get("candidates"))
    if not isinstance(payload, list):
        raise ValueError("search input must be a JSON list or an object with responses/candidates")
    rows: list[dict[str, Any]] = []
    for item in cast(list[object], payload):
        if not isinstance(item, dict):
            raise ValueError("search input rows must be JSON objects")
        rows.append(cast(dict[str, Any], item))
    return rows


def _filter_candidates(rows: Sequence[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = normalize_name(query)
    return [
        row
        for row in rows
        if normalized_query in normalize_name(str(row.get("name", row.get("Name", ""))))
    ]
