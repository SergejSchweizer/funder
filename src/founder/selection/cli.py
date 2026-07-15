"""Selection CLI adapter.

This module owns argument parsing and presentation for the future standalone
`founder-selection` entry point and the equivalent `founder selection`
namespace. It must delegate all business decisions to
`founder.selection.service` and must not implement predicate or membership
logic itself. Command registration and handlers are added by the Selection
CLI PR that builds on this skeleton; this module currently only exposes the
parser hook so the dispatcher boundary is established without changing any
existing command behavior.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Protocol

from founder.selection.contracts import (
    Predicate,
    PredicateSet,
    SelectionDefinition,
    public_field_listing,
)
from founder.selection.service import SelectionService


class ParserRegistry(Protocol):
    def add_parser(self, name: str, **kwargs: object) -> argparse.ArgumentParser: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Founder Selection module.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("fields", help="List public Selection fields.")
    create = subparsers.add_parser("create", help="Create a deterministic Selection definition.")
    create.add_argument("--refresh-snapshot", required=True)
    create.add_argument("--policy", default="default")
    create.add_argument(
        "--filter", nargs=3, action="append", default=[], metavar=("FIELD", "OP", "VALUE")
    )
    subparsers.add_parser("status", help="Show in-memory current Selection status.")
    subparsers.add_parser("version", help="Show Selection contract version.")
    return parser


def register_parser(subparsers: ParserRegistry) -> None:
    """Register the Selection subparser through this module-owned adapter.

    The top-level dispatcher may choose when to attach this parser; command
    semantics are owned here so standalone and umbrella routing can share the
    same argument contract.
    """
    parser = subparsers.add_parser("selection", help="Run the canonical Selection module.")
    parser.set_defaults(domain_cli="selection")


def contract_version() -> str:
    return SelectionService.contract_version()


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    service = SelectionService()
    if args.command == "version":
        payload: dict[str, object] = {"contract_version": service.contract_version()}
    elif args.command == "fields":
        payload = {"fields": public_field_listing()}
    elif args.command == "status":
        payload = service.status()
    else:
        predicates = tuple(
            Predicate(field, operator, _parse_value(value))
            for field, operator, value in args.filter
        )
        definition = SelectionDefinition(
            predicates=PredicateSet(predicates),
            refresh_snapshot_id=args.refresh_snapshot,
            canonical_listing_policy_id=args.policy,
        )
        payload = {
            "metric_requirements": [
                item.metric_name for item in definition.predicates.metric_requirements
            ],
            "name": service.readable_name(definition),
            "refresh_snapshot_id": definition.refresh_snapshot_id,
            "selection_id": definition.selection_id,
        }
    print(json.dumps(payload, sort_keys=True))


def _parse_value(value: str) -> str | float:
    try:
        return float(value)
    except ValueError:
        return value


__all__ = ["build_parser", "contract_version", "main", "register_parser"]
