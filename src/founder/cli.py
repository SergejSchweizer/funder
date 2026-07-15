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
    run_search_workflow,
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
        "--confidence-level",
        type=float,
        default=DEFAULT_CONFIDENCE_LEVEL,
        help="Tail-risk confidence level for VaR and expected shortfall.",
    )
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
    elif args.command == "univariate-statistics":
        summary = run_univariate_statistics_workflow(
            root=Path(args.root),
            confidence_level=args.confidence_level,
        )
    elif args.command == "bivariate-statistics":
        summary = run_bivariate_statistics_workflow(root=Path(args.root))
    else:
        print("founder")
        return
    print(json.dumps(summary, sort_keys=True))
