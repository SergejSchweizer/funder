"""Hosted container runtime entry points."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence


def health() -> int:
    """Return a process health status for container health checks."""

    print(json.dumps({"status": "ok"}, sort_keys=True))
    return 0


def run_api_placeholder() -> int:
    """Start the hosted FastAPI application."""

    import uvicorn

    uvicorn.run("camovar.hosted_api:app", host="0.0.0.0", port=8000, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the hosted runtime parser."""

    parser = argparse.ArgumentParser(description="Camovar hosted container runtime.")
    parser.add_argument("command", choices=("api", "health"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a hosted container entry point."""

    args = build_parser().parse_args(argv)
    if args.command == "health":
        return health()
    return run_api_placeholder()


if __name__ == "__main__":
    raise SystemExit(main())
