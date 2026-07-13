"""Command-line entry point for Founder."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from founder.config import load_eodhd_config
from founder.fetch import (
    ADDITIONAL_EODHD_DATASETS,
    build_gap_fetch_plan,
    eodhd_quote_loader,
    eodhd_raw_data_loader,
    fetch_run_lock,
    write_fetch_manifests,
    write_fetch_plan,
    write_quotes_to_bronze,
    write_raw_eodhd_datasets_to_bronze,
)
from founder.gold import write_gold_inputs
from founder.http import EodhdClient
from founder.logging import get_logger, setup_logging
from founder.paths import LakePaths
from founder.pipeline import run_dry_run
from founder.search import (
    approve_universe,
    normalize_name,
    resolve_current_universe,
    write_canonical_universe,
    write_search_run,
)
from founder.silver import (
    build_silver_quote_rows,
    build_silver_quotes,
    read_bronze_quote_rows,
    read_silver_quotes,
)
from founder.table_io import write_rows

DEFAULT_ROOT = Path("lake")
DEFAULT_SEARCH_INPUT = Path("docs/eodhd_ucits_etf_matches.csv")
LOGGER = get_logger(__name__)


def _slug(value: str) -> str:
    slug = "-".join(normalize_name(value).replace("_", "-").split())
    return slug or "run"


def _generated_run_id(prefix: str, value: str | None = None, run_date: date | None = None) -> str:
    parts = [prefix]
    if value:
        parts.append(_slug(value))
    parts.append((run_date or date.today()).isoformat().replace("-", ""))
    return "-".join(parts)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _read_candidate_payload(path: Path) -> list[dict[str, Any]]:
    if path.suffix.casefold() == ".csv":
        with path.open(encoding="utf-8", newline="") as csv_file:
            return [dict(row) for row in csv.DictReader(csv_file)]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("responses", payload.get("candidates"))
    if not isinstance(payload, list):
        raise ValueError("search input must be a JSON list or an object with responses/candidates")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("search input rows must be JSON objects")
        rows.append(item)
    return rows


def _filter_candidates(rows: Sequence[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = normalize_name(query)
    return [
        row
        for row in rows
        if normalized_query in normalize_name(str(row.get("name", row.get("Name", ""))))
    ]


def _mock_quote_rows(
    item: dict[str, Any], start_date: date, end_date: date
) -> list[dict[str, Any]]:
    start_close = 100.0
    end_close = 101.0 if end_date != start_date else start_close
    return [
        {"date": start_date.isoformat(), "close": start_close, "adjusted_close": start_close},
        {"date": end_date.isoformat(), "close": end_close, "adjusted_close": end_close},
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder portfolio data tooling.")
    parser.add_argument("--debug", action="store_true", help="Write verbose DEBUG logs.")
    subparsers = parser.add_subparsers(dest="command")
    search = subparsers.add_parser("search", help="Run Search for a discovery query.")
    search.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    search.add_argument(
        "query", help="Search string to find in candidate names, for example UCITS ETF."
    )
    search.add_argument(
        "--root", default=str(DEFAULT_ROOT), help="Lake root for generated artifacts."
    )
    search.add_argument(
        "--input",
        default=str(DEFAULT_SEARCH_INPUT),
        help="CSV/JSON candidate source. Defaults to the checked-in UCITS ETF dataset.",
    )
    search.add_argument(
        "--search-run-id",
        help="Optional stable identifier. Generated from query and date by default.",
    )
    search.add_argument("--run-date", type=_parse_date, help="Optional search run date YYYY-MM-DD.")
    search.add_argument(
        "--no-approve", action="store_true", help="Do not approve the generated canonical universe."
    )
    fetch = subparsers.add_parser("fetch", help="Run Fetch planning for the approved universe.")
    fetch.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    fetch.add_argument(
        "--root", default=str(DEFAULT_ROOT), help="Lake root containing current_universe.json."
    )
    fetch.add_argument("--run-id", help="Optional stable identifier. Generated by date by default.")
    fetch.add_argument(
        "--start-date",
        type=_parse_date,
        help="Optional fetch start date YYYY-MM-DD. Omitted by default for full history.",
    )
    fetch.add_argument("--end-date", type=_parse_date, help="Optional fetch end date YYYY-MM-DD.")
    fetch.add_argument("--run-date", type=_parse_date, help="Archive run date YYYY-MM-DD.")
    fetch.add_argument(
        "--concurrency",
        type=_positive_int,
        default=2,
        help="Maximum parallel EODHD fetch workers. Defaults to 2 for cron-safe runs.",
    )
    fetch.add_argument(
        "--mock",
        action="store_true",
        help="Write mocked quote outputs after planning.",
    )
    fetch_selector = fetch.add_mutually_exclusive_group()
    fetch_selector.add_argument(
        "--limit",
        type=_positive_int,
        help="Limit Fetch to the first N approved canonical ISINs.",
    )
    fetch_selector.add_argument(
        "--isin",
        help="Limit Fetch to one approved canonical ISIN.",
    )
    silver = subparsers.add_parser("silver", help="Build Silver quote files from Fetch quotes.")
    silver.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    silver.add_argument("--root", default=str(DEFAULT_ROOT), help="Lake root to build from.")
    gold = subparsers.add_parser("gold", help="Build Gold risk inputs from Silver quotes.")
    gold.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    gold.add_argument("--root", default=str(DEFAULT_ROOT), help="Lake root to build from.")
    refresh = subparsers.add_parser("refresh", help="Run Fetch, Silver, and Gold in order.")
    refresh.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    refresh.add_argument(
        "--root", default=str(DEFAULT_ROOT), help="Lake root containing current_universe.json."
    )
    refresh.add_argument(
        "--run-id", help="Optional stable identifier. Generated by date by default."
    )
    refresh.add_argument(
        "--start-date",
        type=_parse_date,
        help="Optional fetch start date YYYY-MM-DD. Omitted by default for full history.",
    )
    refresh.add_argument("--end-date", type=_parse_date, help="Optional fetch end date YYYY-MM-DD.")
    refresh.add_argument("--run-date", type=_parse_date, help="Archive run date YYYY-MM-DD.")
    refresh.add_argument(
        "--mock",
        action="store_true",
        help="Write mocked quote outputs during Fetch.",
    )
    refresh.add_argument(
        "--concurrency",
        type=_positive_int,
        default=2,
        help="Maximum parallel EODHD fetch workers. Defaults to 2 for cron-safe runs.",
    )
    refresh_selector = refresh.add_mutually_exclusive_group()
    refresh_selector.add_argument(
        "--limit",
        type=_positive_int,
        help="Limit Fetch to the first N approved canonical ISINs.",
    )
    refresh_selector.add_argument(
        "--isin",
        help="Limit Fetch to one approved canonical ISIN.",
    )
    dry_run = subparsers.add_parser("dry-run", help="Run the deterministic mocked pipeline.")
    dry_run.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    dry_run.add_argument("--root", default="lake", help="Lake root for generated artifacts.")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Founder command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        print("founder")
        return
    setup_logging(debug=getattr(args, "debug", False))
    LOGGER.debug("parsed cli args command=%s", args.command)
    if args.command == "search":
        paths = LakePaths(root=Path(args.root))
        run_date = args.run_date or date.today()
        search_run_id = args.search_run_id or _generated_run_id("search", args.query, run_date)
        raw_candidates = _filter_candidates(_read_candidate_payload(Path(args.input)), args.query)
        LOGGER.info(
            "running search query=%s search_run_id=%s input=%s candidates=%s",
            args.query,
            search_run_id,
            args.input,
            len(raw_candidates),
        )
        candidates = write_search_run(
            raw_candidates,
            paths=paths,
            search_run_id=search_run_id,
            query=args.query,
            run_date=run_date,
            found_at=datetime.combine(run_date, datetime.min.time(), tzinfo=UTC),
        )
        canonical = write_canonical_universe(paths, search_run_id)
        summary: dict[str, Any] = {
            "candidate_rows": len(candidates),
            "canonical_rows": len(canonical),
            "query": args.query,
            "search_run_id": search_run_id,
        }
        if not args.no_approve:
            summary["approved_universe"] = approve_universe(paths, search_run_id)
        LOGGER.info(
            "search complete search_run_id=%s canonical_rows=%s", search_run_id, len(canonical)
        )
        print(json.dumps(summary, sort_keys=True))
        return
    if args.command == "fetch":
        summary = _run_fetch_command(args)
        print(json.dumps(summary, sort_keys=True))
        return
    if args.command == "silver":
        summary = _run_silver_command(Path(args.root))
        print(json.dumps(summary, sort_keys=True))
        return
    if args.command == "gold":
        summary = _run_gold_command(Path(args.root))
        print(json.dumps(summary, sort_keys=True))
        return
    if args.command == "refresh":
        fetch_summary = _run_fetch_command(args)
        silver_summary = _run_silver_command(Path(args.root))
        gold_summary = _run_gold_command(Path(args.root))
        print(
            json.dumps(
                {
                    "fetch": fetch_summary,
                    "gold": gold_summary,
                    "silver": silver_summary,
                },
                sort_keys=True,
            )
        )
        return
    if args.command == "dry-run":
        LOGGER.info("running dry-run root=%s", args.root)
        summary = run_dry_run(Path(args.root))
        LOGGER.info("dry-run complete root=%s", args.root)
        print(json.dumps(summary, sort_keys=True))
        return
    print("founder")


def _run_fetch_command(args: argparse.Namespace) -> dict[str, Any]:
    paths = LakePaths(root=Path(args.root))
    run_date = args.run_date or date.today()
    end_date = args.end_date
    start_date = args.start_date
    gap_aware = start_date is None and not args.mock
    if gap_aware:
        end_date = end_date or run_date
    if args.mock:
        end_date = end_date or run_date
        start_date = start_date or (end_date - timedelta(days=30))
    run_id = args.run_id or _generated_run_id("fetch", run_date=run_date)
    canonical_path = resolve_current_universe(paths)
    LOGGER.info("running fetch run_id=%s canonical_path=%s", run_id, canonical_path)
    with fetch_run_lock(paths, run_id):
        listing_plan = write_fetch_plan(
            paths,
            canonical_path,
            run_id=run_id,
            start_date=start_date,
            end_date=end_date,
            limit=args.limit,
            isin=args.isin,
            gap_aware=False,
        )
        quote_plan = listing_plan
        if gap_aware:
            quote_plan = build_gap_fetch_plan(
                listing_plan,
                read_silver_quotes(paths),
                end_date=end_date,
            )
            write_rows(paths.fetch_plan(run_id), quote_plan)
        summary: dict[str, Any] = {
            "concurrency": args.concurrency,
            "end_date": end_date.isoformat() if end_date is not None else None,
            "fetch_plan_rows": len(quote_plan),
            "gap_aware": gap_aware,
            "run_id": run_id,
            "start_date": start_date.isoformat() if start_date is not None else None,
        }
        if args.mock:
            if end_date is None:
                raise RuntimeError("mock fetch requires start and end dates")

            def mock_quotes_for_item(item: Mapping[str, Any]) -> list[dict[str, Any]]:
                item_start = (
                    _parse_date(str(item.get("start_date", "")))
                    if item.get("start_date")
                    else start_date
                )
                item_end = (
                    _parse_date(str(item.get("end_date", ""))) if item.get("end_date") else end_date
                )
                if item_start is None:
                    raise RuntimeError("mock fetch requires start and end dates")
                return _mock_quote_rows(dict(item), item_start, item_end)

            def mock_empty_dataset(_item: Mapping[str, Any]) -> list[dict[str, Any]]:
                return []

            _, quote_errors = write_quotes_to_bronze(
                paths,
                quote_plan,
                run_date=run_date,
                loader=mock_quotes_for_item,
                concurrency=args.concurrency,
            )
            raw_successes, raw_errors = write_raw_eodhd_datasets_to_bronze(
                paths,
                quote_plan,
                run_date=run_date,
                loaders={
                    strategy.name: mock_empty_dataset for strategy in ADDITIONAL_EODHD_DATASETS
                },
                concurrency=args.concurrency,
            )
        else:
            client = EodhdClient(load_eodhd_config())
            _, quote_errors = write_quotes_to_bronze(
                paths,
                quote_plan,
                run_date=run_date,
                loader=eodhd_quote_loader(client),
                concurrency=args.concurrency,
            )
            raw_successes, raw_errors = write_raw_eodhd_datasets_to_bronze(
                paths,
                quote_plan,
                run_date=run_date,
                loaders={
                    strategy.name: eodhd_raw_data_loader(client, strategy.endpoint)
                    for strategy in ADDITIONAL_EODHD_DATASETS
                },
                concurrency=args.concurrency,
            )
        bronze_quote_rows = read_bronze_quote_rows(paths)
        coverage_quote_rows = build_silver_quote_rows(bronze_quote_rows)
        coverage = write_fetch_manifests(
            paths,
            run_id=run_id,
            quote_rows=coverage_quote_rows,
            plan=listing_plan,
            as_of=end_date,
        )
        summary["bronze_quote_rows"] = len(bronze_quote_rows)
        summary["coverage_rows"] = len(coverage)
        summary["error_rows"] = len(quote_errors) + len(raw_errors)
        summary["raw_data_payloads"] = len(raw_successes)
    LOGGER.info("fetch complete run_id=%s plan_rows=%s", run_id, len(quote_plan))
    return summary


def _run_silver_command(root: Path) -> dict[str, Any]:
    paths = LakePaths(root=root)
    LOGGER.info("running silver build root=%s", root)
    quote_rows = build_silver_quotes(paths)
    LOGGER.info("silver build complete root=%s rows=%s", root, len(quote_rows))
    return {"quote_rows": len(quote_rows)}


def _run_gold_command(root: Path) -> dict[str, Any]:
    paths = LakePaths(root=root)
    LOGGER.info("running gold build root=%s", root)
    quotes = read_silver_quotes(paths)
    returns, correlations, covariances = write_gold_inputs(paths, quotes)
    LOGGER.info("gold build complete root=%s returns=%s", root, len(returns))
    return {
        "correlation_rows": len(correlations),
        "covariance_rows": len(covariances),
        "return_rows": len(returns),
    }
