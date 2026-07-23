"""Run a deterministic shard of the Camovar pytest suite."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

INTEGRATION_TEST_NAME_PARTS = (
    "backlog",
    "cli",
    "config",
    "entrypoints",
    "fetch",
    "http",
    "logging",
    "open_backlog",
    "paths",
    "schema_validation",
    "table_io",
)


def discover_test_files(root: Path) -> list[Path]:
    """Return repository test files in deterministic order."""
    return sorted(path for path in (root / "tests").glob("test_*.py") if path.is_file())


def classify_test_suite(path: Path) -> str:
    """Classify a test file as unit or integration by stable filename convention."""
    name = path.stem.removeprefix("test_")
    if any(part in name for part in INTEGRATION_TEST_NAME_PARTS):
        return "integration"
    return "unit"


def filter_suite(files: list[Path], *, suite: str) -> list[Path]:
    """Return test files for one suite or all tests."""
    if suite == "all":
        return files
    if suite not in {"unit", "integration"}:
        raise ValueError(f"unknown test suite: {suite}")
    return [path for path in files if classify_test_suite(path) == suite]


def select_shard(files: list[Path], *, shard_index: int, shard_count: int) -> list[Path]:
    """Select one 1-based deterministic shard from ``files``."""
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    if shard_index < 1 or shard_index > shard_count:
        raise ValueError("shard_index must be between 1 and shard_count")
    return [path for index, path in enumerate(files) if index % shard_count == shard_index - 1]


def build_parser() -> argparse.ArgumentParser:
    """Build the pytest shard command parser."""
    parser = argparse.ArgumentParser(description="Run one deterministic pytest shard.")
    parser.add_argument("--shard-index", type=int, required=True, help="1-based shard index to run")
    parser.add_argument("--shard-count", type=int, required=True, help="Total number of shards")
    parser.add_argument(
        "--suite",
        choices=("all", "unit", "integration"),
        default="all",
        help="Test suite subset to run before sharding",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to pytest after '--'",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run pytest for the selected test-file shard."""
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    files = filter_suite(discover_test_files(root), suite=args.suite)
    selected = select_shard(files, shard_index=args.shard_index, shard_count=args.shard_count)
    if not selected:
        print(f"No {args.suite} tests selected for shard {args.shard_index}/{args.shard_count}")
        return 0

    pytest_args = args.pytest_args
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]

    display_files = [str(path.relative_to(root)) for path in selected]
    print(
        f"Running pytest {args.suite} shard "
        f"{args.shard_index}/{args.shard_count}: {len(selected)} files"
    )
    return subprocess.call([sys.executable, "-m", "pytest", *pytest_args, *display_files], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
