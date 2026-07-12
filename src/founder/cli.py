"""Command-line entry point for Founder."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from founder.pipeline import run_dry_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder portfolio data tooling.")
    subparsers = parser.add_subparsers(dest="command")
    dry_run = subparsers.add_parser("dry-run", help="Run the deterministic mocked pipeline.")
    dry_run.add_argument(
        "--root", default="data/dry-run", help="Lake root for generated artifacts."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Founder command-line interface."""
    args = build_parser().parse_args(argv)
    if args.command == "dry-run":
        summary = run_dry_run(Path(args.root))
        print(json.dumps(summary, sort_keys=True))
        return
    print("founder")
