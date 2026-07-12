"""Deterministic end-to-end dry-run pipeline."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from founder.fetch import (
    build_fetch_plan,
    normalize_quote_rows,
    write_fetch_manifests,
    write_silver_quotes,
)
from founder.gold import write_gold_inputs
from founder.paths import LakePaths
from founder.search import approve_universe, write_canonical_universe, write_search_run
from founder.table_io import JsonRow, write_json, write_rows

SAMPLE_CANDIDATES: tuple[dict[str, str], ...] = (
    {
        "Code": "CSPX",
        "Exchange": "XETRA",
        "Type": "ETF",
        "Country": "Germany",
        "Currency": "EUR",
        "Isin": "IE00B5BMR087",
        "Name": "iShares Core S&P 500 UCITS ETF",
    },
    {
        "Code": "CSP1",
        "Exchange": "LSE",
        "Type": "ETF",
        "Country": "UK",
        "Currency": "GBX",
        "Isin": "IE00B5BMR087",
        "Name": "iShares Core S&P 500 UCITS ETF",
    },
    {
        "Code": "EQQQ",
        "Exchange": "XETRA",
        "Type": "ETF",
        "Country": "Germany",
        "Currency": "EUR",
        "Isin": "IE0032077012",
        "Name": "Invesco EQQQ NASDAQ-100 UCITS ETF",
    },
)


def _sample_quotes(symbol: str) -> list[dict[str, Any]]:
    base = 100.0 if symbol.startswith("CSPX") else 50.0
    return [
        {
            "date": "2026-07-10",
            "open": base,
            "high": base + 1,
            "low": base - 1,
            "close": base,
            "adjusted_close": base,
            "volume": 1000,
        },
        {
            "date": "2026-07-11",
            "open": base + 1,
            "high": base + 2,
            "low": base,
            "close": base + 1,
            "adjusted_close": base + 1,
            "volume": 1100,
        },
        {
            "date": "2026-07-12",
            "open": base + 2,
            "high": base + 3,
            "low": base + 1,
            "close": base + 3,
            "adjusted_close": base + 3,
            "volume": 1200,
        },
    ]


def run_dry_run(root: Path) -> JsonRow:
    paths = LakePaths(root=root)
    run_id = "dry-run-2026-07-12"
    search_run_id = "search-2026-07-12"
    now = datetime(2026, 7, 12, tzinfo=UTC)

    write_search_run(
        SAMPLE_CANDIDATES,
        paths=paths,
        search_run_id=search_run_id,
        run_date=date(2026, 7, 12),
        found_at=now,
    )
    canonical = write_canonical_universe(paths, search_run_id)
    pointer = approve_universe(paths, search_run_id, approved_at=now)
    plan = build_fetch_plan(
        canonical,
        run_id=run_id,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 12),
    )
    write_rows(paths.fetch_plan(run_id), plan)

    raw_by_symbol = {str(item["symbol"]): _sample_quotes(str(item["symbol"])) for item in plan}
    currencies = {str(row["isin"]): str(row["currency"]) for row in canonical}
    quotes = normalize_quote_rows(plan, raw_by_symbol, fetched_at=now, currency_by_isin=currencies)
    write_silver_quotes(paths, quotes)
    coverage = write_fetch_manifests(paths, run_id=run_id, quote_rows=quotes)
    returns, correlations, covariances = write_gold_inputs(paths, quotes, as_of="2026-07-12")
    summary: JsonRow = {
        "search_run_id": search_run_id,
        "fetch_run_id": run_id,
        "current_universe": pointer,
        "canonical_rows": len(canonical),
        "plan_rows": len(plan),
        "quote_rows": len(quotes),
        "coverage_rows": len(coverage),
        "return_rows": len(returns),
        "correlation_rows": len(correlations),
        "covariance_rows": len(covariances),
    }
    write_json(paths.dry_run_summary(), summary)
    return summary
