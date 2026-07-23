"""Rebuild the local Compose Web service when UI-relevant files change."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WATCH_PATHS = (
    "apps/web",
    "apps/api",
    "src",
    "compose.yaml",
    ".dockerignore",
    "pyproject.toml",
    "uv.lock",
)
DEFAULT_COMMAND = (
    "docker",
    "compose",
    "--env-file",
    ".env.local",
    "up",
    "--build",
    "-d",
    "web",
)


@dataclass(frozen=True)
class WatchSnapshot:
    """Stable content snapshot for local Compose rebuild decisions."""

    digest: str
    file_count: int


def build_parser() -> argparse.ArgumentParser:
    """Build the local Compose Web watcher parser."""

    parser = argparse.ArgumentParser(
        description="Watch UI/runtime files and reinstall the Web service in local Docker Compose."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Repository root. Defaults to this checkout.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds.",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        default=None,
        help="Relative path to watch. Can be passed multiple times.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one rebuild immediately, then exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rebuild command instead of running Docker Compose.",
    )
    return parser


def snapshot_paths(root: Path, relative_paths: tuple[str, ...]) -> WatchSnapshot:
    """Return a deterministic snapshot for watched files.

    Args:
        root: Repository root.
        relative_paths: Files or directories relative to `root`.

    Returns:
        Content digest and number of files included.
    """

    digest = hashlib.sha256()
    files = list(_iter_files(root, relative_paths))
    for path in files:
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        digest.update(relative.encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(path.read_bytes())
    return WatchSnapshot(digest=digest.hexdigest(), file_count=len(files))


def rebuild_web(root: Path, *, dry_run: bool) -> int:
    """Run or print the local Compose Web rebuild command."""

    command = list(DEFAULT_COMMAND)
    if dry_run:
        print(" ".join(command))
        return 0
    return subprocess.run(command, cwd=root, check=False).returncode


def watch_and_rebuild(
    *,
    root: Path,
    relative_paths: tuple[str, ...],
    interval_seconds: float,
    dry_run: bool,
    once: bool,
) -> int:
    """Watch files and rebuild Web when their content changes."""

    root = root.resolve()
    if once:
        return rebuild_web(root, dry_run=dry_run)

    current = snapshot_paths(root, relative_paths)
    print(
        f"Watching {current.file_count} files; rebuilding Web when UI/runtime files change.",
        flush=True,
    )
    while True:
        time.sleep(interval_seconds)
        next_snapshot = snapshot_paths(root, relative_paths)
        if next_snapshot.digest == current.digest:
            continue
        current = next_snapshot
        print("Change detected; rebuilding local Compose Web service.", flush=True)
        result = rebuild_web(root, dry_run=dry_run)
        if result != 0:
            print(f"Compose rebuild failed with exit code {result}.", file=sys.stderr, flush=True)


def _iter_files(root: Path, relative_paths: tuple[str, ...]) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative in relative_paths:
        path = root / relative
        if not path.exists():
            continue
        if path.is_file():
            files.append(path)
            continue
        files.extend(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and not _ignored(candidate)
        )
    return tuple(sorted(files))


def _ignored(path: Path) -> bool:
    ignored_parts = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
    }
    return any(part in ignored_parts for part in path.parts)


def main() -> int:
    """Run the local Compose Web watcher CLI."""

    args = build_parser().parse_args()
    paths = tuple(args.paths) if args.paths is not None else DEFAULT_WATCH_PATHS
    return watch_and_rebuild(
        root=args.root,
        relative_paths=paths,
        interval_seconds=args.interval,
        dry_run=args.dry_run,
        once=args.once,
    )


if __name__ == "__main__":
    raise SystemExit(main())
