"""Update CLI adapter.

This module owns argument parsing and presentation for the future standalone
`founder-update` entry point and the equivalent `founder update` namespace.
It must delegate all business decisions to `founder.update.service` and must
not implement work-planning or metric-computation logic itself. Command
registration and handlers are added by the Update CLI PR that builds on this
skeleton; this module currently only exposes the parser hook so the
dispatcher boundary is established without changing any existing command
behavior.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Protocol

from founder.update.contracts import UpdateRequest
from founder.update.service import UpdateService


class ParserRegistry(Protocol):
    def add_parser(self, name: str, **kwargs: object) -> argparse.ArgumentParser: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder Update module.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Build a deterministic Update request shell.")
    plan.add_argument("--selection", required=True)
    plan.add_argument("--run-id", default="update-run")
    plan.add_argument("--concurrency", type=int, default=2)
    plan.add_argument("--dry-run", action="store_true")
    subparsers.add_parser("status", help="Show in-memory current Update status.")
    subparsers.add_parser("version", help="Show Update contract version.")
    return parser


def register_parser(subparsers: ParserRegistry) -> None:
    """Register the Update subparser through this module-owned adapter.

    The top-level dispatcher may choose when to attach this parser; command
    semantics are owned here so standalone and umbrella routing can share the
    same argument contract.
    """
    parser = subparsers.add_parser("update", help="Run the canonical Update module.")
    parser.set_defaults(domain_cli="update")


def contract_version() -> str:
    return UpdateService.contract_version()


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    service = UpdateService()
    if args.command == "version":
        payload: dict[str, object] = {"contract_version": service.contract_version()}
    elif args.command == "status":
        pointer = service.current_pointer()
        payload = {"state": "none"} if pointer is None else {"run_id": pointer.run_id}
    else:
        request = UpdateRequest(
            selection_id=args.selection,
            run_id=args.run_id,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
        )
        payload = {
            "concurrency": request.concurrency,
            "dry_run": request.dry_run,
            "run_id": request.run_id,
            "selection_id": request.selection_id,
        }
    print(json.dumps(payload, sort_keys=True))


__all__ = ["build_parser", "contract_version", "main", "register_parser"]
