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

from founder.selection.service import SelectionService


def register_parser(subparsers: argparse.ArgumentParser) -> None:
    """Register the future Selection subparser without wiring command behavior.

    Left unregistered by default so existing `founder` commands are
    unaffected; the Selection CLI PR calls this from the dispatcher once
    Selection command handlers exist.
    """
    del subparsers


def contract_version() -> str:
    return SelectionService.contract_version()


__all__ = ["contract_version", "register_parser"]
