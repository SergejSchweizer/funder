"""Command-line entry point for Founder."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from founder.logging import get_logger, setup_logging
from founder.univariate_statistics import DEFAULT_CONFIDENCE_LEVEL
from founder.workflows import (
    run_bivariate_statistics_workflow,
    run_fetch_all_isins_workflow,
    run_fetch_all_quotes_workflow,
    run_metadata_filter_workflow,
    run_search_workflow,
    run_univariate_filter_workflow,
    run_univariate_statistics_workflow,
)

DEFAULT_ROOT = Path("lake")
DEFAULT_SEARCH_INPUT = Path("docs/eodhd_ucits_etf_matches.csv")
LOGGER = get_logger(__name__)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


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
    fetch_all_isins = subparsers.add_parser(
        "fetch-all-isins",
        help="Fetch the full EODHD ISIN metadata universe.",
    )
    fetch_all_isins.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    fetch_all_isins.add_argument("--root", default=str(DEFAULT_ROOT), help="Lake root to write to.")
    fetch_all_isins.add_argument(
        "--exchange-code",
        action="append",
        default=[],
        help="Exchange code to fetch. May be repeated. Defaults to all EODHD exchanges.",
    )
    fetch_all_isins.add_argument(
        "--include-delisted",
        action="store_true",
        help="Include delisted symbols when EODHD provides them.",
    )
    fetch_all_quotes = subparsers.add_parser(
        "fetch-all-quotes",
        help="Fetch quote, dividend, and split data for the latest metadata-filter selection.",
    )
    fetch_all_quotes.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    fetch_all_quotes.add_argument(
        "--root", default=str(DEFAULT_ROOT), help="Lake root to write to."
    )
    fetch_all_quotes.add_argument(
        "--run-id",
        help="Optional stable run id. Defaults to fetch-all-quotes plus the end date.",
    )
    fetch_all_quotes.add_argument(
        "--start-date",
        type=_parse_date,
        help="Optional first quote date YYYY-MM-DD. Empty means full provider history.",
    )
    fetch_all_quotes.add_argument(
        "--end-date",
        type=_parse_date,
        help="Optional last quote date YYYY-MM-DD. Defaults to today.",
    )
    fetch_all_quotes.add_argument(
        "--limit",
        type=int,
        help="Optional maximum approved listings to fetch.",
    )
    fetch_all_quotes.add_argument(
        "--isin",
        help="Optional single ISIN from the latest metadata-filter selection to fetch.",
    )
    fetch_all_quotes.add_argument(
        "--no-gap-aware",
        action="store_true",
        help="Disable Silver-based gap planning and request the whole requested date window.",
    )
    fetch_all_quotes.add_argument(
        "--no-raw-datasets",
        action="store_true",
        help="Do not fetch companion raw dividends and splits datasets.",
    )
    fetch_all_quotes.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Worker thread count for EODHD requests and Silver writes. Defaults to 2.",
    )
    metadata_filter = subparsers.add_parser(
        "metadata-filter",
        help="Create a metadata-based ISIN selection.",
    )
    metadata_filter.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    metadata_filter.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Lake root to read from.",
    )
    metadata_filter.add_argument(
        "--where",
        action="append",
        default=[],
        help="Conjunctive predicate such as country=DE, name~UCITS, or volume>=1000.",
    )
    metadata_filter.add_argument(
        "--name-contains",
        action="append",
        default=[],
        help="Case-insensitive text search in the instrument name. May be repeated.",
    )
    metadata_filter.add_argument("--selection-name", help="Optional stable human-readable name.")
    univariate = subparsers.add_parser(
        "univariate-statistics",
        help="Build reusable per-listing statistics from Silver quotes.",
    )
    univariate.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    univariate.add_argument("--root", default=str(DEFAULT_ROOT), help="Lake root to build from.")
    univariate.add_argument(
        "--selection-id",
        help="Metadata-filter selection id. Defaults to the latest metadata-filter selection.",
    )
    univariate.add_argument(
        "--confidence-level",
        type=float,
        default=DEFAULT_CONFIDENCE_LEVEL,
        help="Tail-risk confidence level for VaR and expected shortfall.",
    )
    univariate.add_argument(
        "--concurrency",
        type=int,
        help="Worker process count. Defaults to all CPU cores visible to the system.",
    )
    univariate_filter = subparsers.add_parser(
        "univariate-filter",
        help="Create an ISIN selection from univariate statistics.",
    )
    univariate_filter.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    univariate_filter.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Lake root to read from.",
    )
    univariate_filter.add_argument(
        "--where",
        action="append",
        default=[],
        required=True,
        help="Conjunctive predicate such as max_drawdown>=-0.2 or sharpe_ratio>0.5.",
    )
    univariate_filter.add_argument("--selection-name", help="Optional stable human-readable name.")
    bivariate = subparsers.add_parser(
        "bivariate-statistics",
        help="Build reusable pairwise statistics from Silver quotes.",
    )
    bivariate.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    bivariate.add_argument("--root", default=str(DEFAULT_ROOT), help="Lake root to build from.")
    bivariate.add_argument(
        "--selection-id",
        help=(
            "Optional metadata-filter or univariate-filter selection id. "
            "Defaults to the latest univariate-filter selection."
        ),
    )
    bivariate.add_argument(
        "--concurrency",
        type=int,
        help="Worker process count. Defaults to all CPU cores visible to the system.",
    )
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
        summary = run_search_workflow(
            root=Path(args.root),
            input_path=Path(args.input),
            query=args.query,
            search_run_id=args.search_run_id,
            run_date=args.run_date,
            approve=not args.no_approve,
        )
    elif args.command == "fetch-all-isins":
        summary = run_fetch_all_isins_workflow(
            root=Path(args.root),
            exchange_codes=tuple(args.exchange_code),
            include_delisted=args.include_delisted,
        )
    elif args.command == "fetch-all-quotes":
        summary = run_fetch_all_quotes_workflow(
            root=Path(args.root),
            run_id=args.run_id,
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
            isin=args.isin,
            gap_aware=not args.no_gap_aware,
            include_raw_datasets=not args.no_raw_datasets,
            concurrency=args.concurrency,
        )
    elif args.command == "metadata-filter":
        summary = run_metadata_filter_workflow(
            root=Path(args.root),
            predicates=tuple(args.where),
            name_contains=tuple(args.name_contains),
            selection_name=args.selection_name,
        )
    elif args.command == "univariate-statistics":
        summary = run_univariate_statistics_workflow(
            root=Path(args.root),
            selection_id=args.selection_id,
            confidence_level=args.confidence_level,
            concurrency=args.concurrency,
        )
    elif args.command == "univariate-filter":
        summary = run_univariate_filter_workflow(
            root=Path(args.root),
            predicates=tuple(args.where),
            selection_name=args.selection_name,
        )
    elif args.command == "bivariate-statistics":
        summary = run_bivariate_statistics_workflow(
            root=Path(args.root),
            selection_id=args.selection_id,
            concurrency=args.concurrency,
        )
    else:
        print("founder")
        return
    print(json.dumps(summary, sort_keys=True))
