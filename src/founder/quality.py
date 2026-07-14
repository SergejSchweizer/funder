"""Two-layer local quality gates for Founder."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Sequence

Command = tuple[str, ...]
Runner = Callable[..., subprocess.CompletedProcess[str]]

CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(\([a-z0-9][a-z0-9-]*\))?(!)?: .+"
)

PR_GATE_COMMANDS: tuple[Command, ...] = (
    ("ruff", "check", "."),
    ("ruff", "format", "--check", "."),
    ("python", "-m", "founder.architecture_checks"),
    ("pyright",),
    ("pytest",),
)

MAIN_COVERAGE_COMMAND: Command = (
    "pytest",
    "--cov=founder",
    "--cov-report=term-missing",
    "--cov-fail-under=95",
)

CONVENTIONAL_COMMIT_TYPES = "build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test"

MAIN_GATE_COMMANDS: tuple[Command, ...] = (
    *PR_GATE_COMMANDS[:-1],
    ("lint-imports", "--config", "pyproject.toml", "--no-cache"),
    ("python", "-m", "founder.schema_validation"),
    MAIN_COVERAGE_COMMAND,
    ("git", "diff", "--quiet"),
    ("git", "diff", "--cached", "--quiet"),
    ("git", "status", "--short", "--untracked-files=all"),
)


def commands_for_layer(layer: str) -> tuple[Command, ...]:
    """Return commands for the requested quality gate layer."""
    if layer == "pr":
        return PR_GATE_COMMANDS
    if layer == "main":
        return MAIN_GATE_COMMANDS
    raise ValueError(f"unknown quality gate layer: {layer}")


def run_commands(commands: Sequence[Command], *, runner: Runner = subprocess.run) -> int:
    """Run commands in order and stop at the first failure or dirty status output."""
    for command in commands:
        result = runner(command, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode != 0:
            return result.returncode
        if command == ("git", "status", "--short", "--untracked-files=all") and result.stdout:
            print("main quality gate requires a clean working tree", file=sys.stderr)
            return 1
    return 0


def is_conventional_commit_subject(subject: str) -> bool:
    """Return whether a commit subject follows Conventional Commits."""
    return bool(CONVENTIONAL_COMMIT_PATTERN.fullmatch(subject.strip()))


def commit_range(*, runner: Runner = subprocess.run) -> str:
    """Return the branch commit range to validate against the default main remote."""
    merge_base = runner(
        ("git", "merge-base", "HEAD", "origin/main"),
        text=True,
        capture_output=True,
    )
    if merge_base.returncode != 0:
        return "HEAD~1..HEAD"
    return f"{merge_base.stdout.strip()}..HEAD"


def commit_subjects(revision_range: str, *, runner: Runner = subprocess.run) -> list[str]:
    """Return commit subjects in a revision range."""
    result = runner(
        ("git", "log", "--format=%s", revision_range),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise RuntimeError(f"failed to read commits for {revision_range}")
    return [line for line in result.stdout.splitlines() if line]


def validate_conventional_commits(*, runner: Runner = subprocess.run) -> int:
    """Validate that branch commit subjects use Conventional Commits."""
    subjects = commit_subjects(commit_range(runner=runner), runner=runner)
    invalid = [subject for subject in subjects if not is_conventional_commit_subject(subject)]
    if not invalid:
        return 0

    print("Conventional Commit validation failed.", file=sys.stderr)
    print(
        f"Expected: type(optional-scope): subject, with type one of {CONVENTIONAL_COMMIT_TYPES}.",
        file=sys.stderr,
    )
    for subject in invalid:
        print(f"Invalid commit subject: {subject}", file=sys.stderr)
    return 1


def validate_commit_message_file(path: str) -> int:
    """Validate one commit message file using Conventional Commits."""
    with open(path, encoding="utf-8") as message_file:
        subject = message_file.readline().strip()
    if is_conventional_commit_subject(subject):
        return 0
    print("Conventional Commit validation failed.", file=sys.stderr)
    print(
        f"Expected: type(optional-scope): subject, with type one of {CONVENTIONAL_COMMIT_TYPES}.",
        file=sys.stderr,
    )
    print(f"Invalid commit subject: {subject}", file=sys.stderr)
    return 1


def validate_squash_subject(subject: str) -> int:
    """Validate the PR title used as the squash-merge commit subject."""
    if is_conventional_commit_subject(subject):
        return 0
    print("Squash merge subject validation failed.", file=sys.stderr)
    print(
        f"Expected: type(optional-scope): subject, with type one of {CONVENTIONAL_COMMIT_TYPES}.",
        file=sys.stderr,
    )
    print(f"Invalid squash subject: {subject}", file=sys.stderr)
    return 1


def run_quality_gate(layer: str, *, runner: Runner = subprocess.run) -> int:
    """Run the requested quality layer, including Conventional Commit validation."""
    command_result = run_commands(commands_for_layer(layer), runner=runner)
    if command_result != 0:
        return command_result
    return validate_conventional_commits(runner=runner)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Founder quality gates.")
    parser.add_argument(
        "layer",
        choices=("pr", "main"),
        nargs="?",
        help="Quality gate layer to run: 'pr' for PR/push checks, 'main' before merge.",
    )
    parser.add_argument(
        "--commit-msg-file",
        help="Validate a single commit message file for the commit-msg hook.",
    )
    parser.add_argument(
        "--squash-subject",
        help="Validate the PR title that will become the squash-merge commit subject.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.commit_msg_file:
        return validate_commit_message_file(args.commit_msg_file)
    if args.squash_subject:
        return validate_squash_subject(args.squash_subject)
    if not args.layer:
        build_parser().error(
            "layer is required unless --commit-msg-file or --squash-subject is provided"
        )
    return run_quality_gate(args.layer)


if __name__ == "__main__":
    raise SystemExit(main())
