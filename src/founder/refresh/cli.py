"""Refresh CLI adapter.

This module owns argument parsing and presentation for the future standalone
`founder-refresh` entry point and the equivalent `founder refresh` namespace.
It must delegate all business decisions to `founder.refresh.service` and must
not implement catalog or market-data logic itself. Command registration and
handlers are added by the Refresh CLI PR that builds on this skeleton; this
module currently only exposes the parser hook so the dispatcher boundary is
established without changing any existing command behavior.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Protocol

from founder.refresh.contracts import RefreshRequest
from founder.refresh.service import RefreshService


class ParserRegistry(Protocol):
    def add_parser(self, name: str, **kwargs: object) -> argparse.ArgumentParser: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder Refresh module.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Build a deterministic Refresh request plan.")
    plan.add_argument("--run-id", default="refresh-run")
    plan.add_argument("--exchange", action="append", default=[])
    plan.add_argument("--concurrency", type=int, default=2)
    plan.add_argument("--resume", default="")
    plan.add_argument("--dry-run", action="store_true")
    subparsers.add_parser("status", help="Show in-memory Refresh pointer status.")
    subparsers.add_parser("version", help="Show Refresh contract version.")
    return parser


def register_parser(subparsers: ParserRegistry) -> None:
    """Register the Refresh subparser through this module-owned adapter.

    The top-level dispatcher may choose when to attach this parser; command
    semantics are owned here so standalone and umbrella routing can share the
    same argument contract.
    """
    parser = subparsers.add_parser("refresh", help="Run the canonical Refresh module.")
    parser.set_defaults(domain_cli="refresh")


def contract_version() -> str:
    return RefreshService.contract_version()


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    service = RefreshService()
    if args.command == "version":
        payload: dict[str, object] = {"contract_version": service.contract_version()}
    elif args.command == "status":
        pointer = service.current_pointer()
        payload = {"state": "none"} if pointer is None else {"run_id": pointer.run_id}
    else:
        exchanges = tuple(args.exchange or ("XETRA",))
        request = RefreshRequest(
            run_id=args.run_id,
            exchanges=exchanges,
            publish=not args.dry_run,
            resume_from=args.resume,
        )
        payload = {
            "concurrency": args.concurrency,
            "dry_run": args.dry_run,
            "exchanges": list(request.exchanges),
            "resume": request.resume_from,
            "run_id": request.run_id,
        }
    print(json.dumps(payload, sort_keys=True))


__all__ = ["build_parser", "contract_version", "main", "register_parser"]
