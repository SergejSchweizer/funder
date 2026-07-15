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

from founder.update.service import UpdateService


def register_parser(subparsers: argparse.ArgumentParser) -> None:
    """Register the future Update subparser without wiring command behavior.

    Left unregistered by default so existing `founder` commands are
    unaffected; the Update CLI PR calls this from the dispatcher once Update
    command handlers exist.
    """
    del subparsers


def contract_version() -> str:
    return UpdateService.contract_version()


__all__ = ["contract_version", "register_parser"]
