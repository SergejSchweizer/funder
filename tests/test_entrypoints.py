"""Installed console-script entry-point consistency and smoke gate (C01).

These tests read the actually-installed `console_scripts` entry points rather
than parsing `pyproject.toml` directly, so they fail the same way a real
editable or wheel installation would fail: if a script is declared but its
target module or attribute does not exist, or if a declared script cannot
answer `--help` cleanly.
"""

from __future__ import annotations

import importlib
import sys
from importlib import metadata

import pytest

FOUNDER_ENTRY_POINTS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (entry_point.name, entry_point.value)
        for entry_point in metadata.entry_points(group="console_scripts")
        if entry_point.name == "founder" or entry_point.name.startswith("founder-")
    )
)


def test_founder_console_scripts_are_registered() -> None:
    names = {name for name, _value in FOUNDER_ENTRY_POINTS}
    assert names == {
        "founder",
        "founder-compose-web-watch",
        "founder-docs-refresh",
        "founder-fetch-all-quotes",
        "founder-quality",
    }


@pytest.mark.parametrize("name,value", FOUNDER_ENTRY_POINTS)
def test_console_script_target_imports_and_is_callable(name: str, value: str) -> None:
    module_path, _, attribute = value.partition(":")
    module = importlib.import_module(module_path)
    target = getattr(module, attribute)
    assert callable(target), f"{name} -> {value} is not callable"


@pytest.mark.parametrize("name,value", FOUNDER_ENTRY_POINTS)
def test_console_script_help_exits_cleanly_without_side_effects(
    name: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every declared script must answer `--help` without reading secrets or
    touching the lake, regardless of whether its `main` accepts an explicit
    `argv` sequence or reads `sys.argv` directly."""
    monkeypatch.setattr(sys, "argv", [name, "--help"])
    module_path, _, attribute = value.partition(":")
    module = importlib.import_module(module_path)
    target = getattr(module, attribute)

    with pytest.raises(SystemExit) as excinfo:
        target()

    assert excinfo.value.code == 0


def test_umbrella_cli_help_lists_every_subcommand() -> None:
    from founder.cli import build_parser

    parser = build_parser()
    subparsers_actions = [
        action
        for action in parser._actions  # noqa: SLF001 - argparse has no public introspection API
        if action.choices is not None
    ]
    assert subparsers_actions, "expected the umbrella CLI to register subcommands"
    subcommands = set(subparsers_actions[0].choices)
    assert subcommands == {
        "search",
        "fetch-all-isins",
        "fetch-all-quotes",
        "metadata-filter",
        "univariate-statistics",
        "univariate-filter",
        "bivariate-statistics",
        "multivariate-statistics",
    }


@pytest.mark.parametrize(
    "subcommand",
    [
        "search",
        "fetch-all-isins",
        "fetch-all-quotes",
        "metadata-filter",
        "univariate-statistics",
        "univariate-filter",
        "bivariate-statistics",
        "multivariate-statistics",
    ],
)
def test_umbrella_cli_subcommand_help_exits_cleanly(subcommand: str) -> None:
    from founder.cli import main

    with pytest.raises(SystemExit) as excinfo:
        main([subcommand, "--help"])

    assert excinfo.value.code == 0
