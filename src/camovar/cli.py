"""Command-line entry point for Camovar."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from camovar.logging import get_logger, log_event, setup_logging
from camovar.univariate_statistics import DEFAULT_CONFIDENCE_LEVEL
from camovar.workflows import (
    run_bivariate_statistics_workflow,
    run_fetch_all_isins_workflow,
    run_fetch_all_quotes_workflow,
    run_metadata_filter_workflow,
    run_multivariate_statistics_workflow,
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
    parser = argparse.ArgumentParser(description="Camovar portfolio data tooling.")
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
    multivariate = subparsers.add_parser(
        "multivariate-statistics",
        help="Build portfolio statistics from the latest univariate-filter selection.",
    )
    multivariate.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write verbose DEBUG logs.",
    )
    multivariate.add_argument("--root", default=str(DEFAULT_ROOT), help="Lake root to build from.")
    multivariate.add_argument(
        "--selection-id",
        help="Univariate-filter selection id. Defaults to the latest univariate-filter selection.",
    )
    multivariate.add_argument(
        "--use-selection-statistics-cache",
        action="store_true",
        help=(
            "Use PR74 selection statistics views and generic Gold caches before "
            "running portfolio-level calculations."
        ),
    )
    multivariate.add_argument(
        "--evaluation-id",
        default="multivariate-latest",
        help="Stable evaluation id for generated portfolio artifacts.",
    )
    multivariate.add_argument(
        "--portfolio-id-prefix",
        default="multivariate",
        help="Prefix for generated portfolio ids.",
    )
    multivariate.add_argument(
        "--confidence-level",
        type=float,
        default=0.95,
        help="Tail-risk confidence level for asset and portfolio metrics.",
    )
    multivariate.add_argument(
        "--grid-step",
        type=float,
        default=0.1,
        help="Deterministic optimizer grid step. Defaults to 0.1.",
    )
    multivariate.add_argument(
        "--train-window",
        type=int,
        default=2,
        help="Walk-forward training window in common return rows.",
    )
    multivariate.add_argument(
        "--test-window",
        type=int,
        default=1,
        help="Walk-forward test window in common return rows.",
    )
    multivariate.add_argument(
        "--walk-forward-profile",
        choices=("development", "production"),
        default="development",
        help=(
            "Walk-forward policy: 'development' allows tiny fixture windows but is never "
            "production eligible; 'production' enforces minimum history, test window, "
            "completed-split, and concentration requirements."
        ),
    )
    multivariate.add_argument(
        "--rebalance-schedule",
        choices=("monthly", "quarterly", "annual", "threshold"),
        default="monthly",
        help="Rebalance simulation schedule.",
    )
    multivariate.add_argument(
        "--transaction-cost-rate",
        type=float,
        default=0.0,
        help="Transaction cost rate used in rebalance simulation.",
    )
    multivariate.add_argument(
        "--drift-threshold",
        type=float,
        help="Optional drift threshold for threshold rebalancing.",
    )
    multivariate.add_argument(
        "--min-weight",
        type=float,
        default=0.0,
        help="Minimum instrument weight for generated portfolios.",
    )
    multivariate.add_argument(
        "--max-weight",
        type=float,
        default=1.0,
        help="Maximum instrument weight for generated portfolios.",
    )
    multivariate.add_argument(
        "--concurrency",
        type=int,
        help=(
            "Worker process count for Gold input generation. "
            "Defaults to all CPU cores visible to the system."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Camovar command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        print("camovar")
        return
    setup_logging(debug=getattr(args, "debug", False))
    log_event(
        LOGGER,
        logging.DEBUG,
        module="cli",
        event="args_parsed",
        fields={"command": args.command},
    )
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
    elif args.command == "multivariate-statistics":
        summary = run_multivariate_statistics_workflow(
            root=Path(args.root),
            selection_id=args.selection_id,
            evaluation_id=args.evaluation_id,
            portfolio_id_prefix=args.portfolio_id_prefix,
            confidence_level=args.confidence_level,
            grid_step=args.grid_step,
            train_window=args.train_window,
            test_window=args.test_window,
            walk_forward_profile=args.walk_forward_profile,
            rebalance_schedule=args.rebalance_schedule,
            transaction_cost_rate=args.transaction_cost_rate,
            drift_threshold=args.drift_threshold,
            min_weight=args.min_weight,
            max_weight=args.max_weight,
            concurrency=args.concurrency,
            use_selection_statistics_cache=args.use_selection_statistics_cache,
        )
    else:
        print("camovar")
        return
    print(json.dumps(summary, sort_keys=True))
