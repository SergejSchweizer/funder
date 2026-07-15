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

from founder.refresh.service import RefreshService


def register_parser(subparsers: argparse.ArgumentParser) -> None:
    """Register the future Refresh subparser without wiring command behavior.

    Left unregistered by default so existing `founder` commands are
    unaffected; the Refresh CLI PR calls this from the dispatcher once
    Refresh command handlers exist.
    """
    del subparsers


def contract_version() -> str:
    return RefreshService.contract_version()


__all__ = ["contract_version", "register_parser"]
