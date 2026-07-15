"""Operational workflows behind the three Founder CLI modules."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from founder.bivariate_statistics import write_bivariate_statistics
from founder.logging import get_logger
from founder.paths import LakePaths
from founder.search import (
    approve_universe,
    normalize_name,
    write_canonical_universe,
    write_search_run,
)
from founder.silver import read_silver_quotes
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


def run_univariate_statistics_workflow(
    *,
    root: Path,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """Build reusable per-listing statistics from existing Silver quotes."""
    paths = LakePaths(root=root)
    LOGGER.info("running univariate statistics root=%s", root)
    quotes = read_silver_quotes(paths)
    rows = write_univariate_statistics(paths, quotes, confidence_level=confidence_level)
    LOGGER.info("univariate statistics complete root=%s rows=%s", root, len(rows))
    return {
        "quote_rows": len(quotes),
        "univariate_statistics_rows": len(rows),
    }


def run_bivariate_statistics_workflow(*, root: Path) -> dict[str, Any]:
    """Build reusable pairwise statistics from existing Silver quotes."""
    paths = LakePaths(root=root)
    LOGGER.info("running bivariate statistics root=%s", root)
    quotes = read_silver_quotes(paths)
    returns = build_quote_returns(quotes)
    rows = write_bivariate_statistics(paths, returns)
    LOGGER.info("bivariate statistics complete root=%s rows=%s", root, len(rows))
    return {
        "bivariate_statistics_rows": len(rows),
        "quote_rows": len(quotes),
        "return_rows": len(returns),
    }


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
