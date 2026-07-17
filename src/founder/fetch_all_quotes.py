"""Standalone CLI for fetching all approved quote inputs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from founder.logging import get_logger, setup_logging
from founder.workflows import run_fetch_all_quotes_workflow

DEFAULT_ROOT = Path("lake")
LOGGER = get_logger(__name__)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone fetch-all-quotes argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Fetch quote, dividend, and split data for the latest metadata-filter selection."
        )
    )
    parser.add_argument("--debug", action="store_true", help="Write verbose DEBUG logs.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Lake root to write to.")
    parser.add_argument(
        "--run-id",
        help="Optional stable run id. Defaults to fetch-all-quotes plus the end date.",
    )
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        help="Optional first quote date YYYY-MM-DD. Empty means full provider history.",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        help="Optional last quote date YYYY-MM-DD. Defaults to today.",
    )
    parser.add_argument("--limit", type=int, help="Optional maximum approved listings to fetch.")
    parser.add_argument(
        "--isin", help="Optional single ISIN from the latest metadata-filter selection to fetch."
    )
    parser.add_argument(
        "--no-gap-aware",
        action="store_true",
        help="Disable Silver-based gap planning and request the whole requested date window.",
    )
    parser.add_argument(
        "--no-raw-datasets",
        action="store_true",
        help="Do not fetch companion raw dividends and splits datasets.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Worker thread count for EODHD requests and Silver writes. Defaults to 2.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the standalone fetch-all-quotes command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(debug=args.debug)
    LOGGER.debug("parsed fetch-all-quotes args")
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
    print(json.dumps(summary, sort_keys=True))
