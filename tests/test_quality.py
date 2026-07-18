from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from founder.quality import (
    build_parser,
    commands_for_layer,
    is_conventional_commit_subject,
    main,
    run_commands,
    run_quality_gate,
    validate_commit_message_file,
    validate_conventional_commits,
    validate_squash_subject,
)


def test_pr_gate_has_simple_checks() -> None:
    assert commands_for_layer("pr") == (
        ("ruff", "check", "."),
        ("ruff", "format", "--check", "."),
        ("pyright",),
        ("pytest", "-q", "-n", "auto"),
    )


def test_merge_gate_extends_pr_gate_with_protected_checks() -> None:
    commands = commands_for_layer("merge")

    assert commands[:4] == (
        ("ruff", "check", "."),
        ("ruff", "format", "--check", "."),
        ("python", "-m", "founder.architecture_checks"),
        ("python", "-m", "founder.schema_validation"),
    )
    assert commands[4] == ("pyright",)
    assert commands[5] == (
        "pytest",
        "-n",
        "auto",
        "--cov=founder",
        "--cov-report=term-missing",
        "--cov-fail-under=95",
    )
    assert commands[-3:] == (
        ("git", "diff", "--quiet"),
        ("git", "diff", "--cached", "--quiet"),
        ("git", "status", "--short", "--untracked-files=all"),
    )
    assert commands_for_layer("main") == commands


def test_run_commands_stops_at_first_failure() -> None:
    calls: list[Sequence[str]] = []

    def runner(command: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="failed")

    assert run_commands((("ruff", "check", "."), ("pytest",)), runner=runner) == 2
    assert calls == [("ruff", "check", ".")]


def test_merge_gate_fails_on_dirty_status_output() -> None:
    def runner(command: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        stdout = " M README.md\n" if command[0:2] == ("git", "status") else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    assert run_commands((commands_for_layer("merge")[-1],), runner=runner) == 1


def test_conventional_commit_subject_validation() -> None:
    assert is_conventional_commit_subject("feat: add search contracts")
    assert is_conventional_commit_subject("fix(http): redact token")
    assert is_conventional_commit_subject("refactor!: change bronze contract")
    assert not is_conventional_commit_subject("Add search contracts")
    assert not is_conventional_commit_subject("feat add search contracts")


def test_validate_conventional_commits_rejects_invalid_branch_subjects() -> None:
    def runner(command: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[0:2] == ("git", "merge-base"):
            return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")
        if command[0:2] == ("git", "log"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="feat: add config\nAdd bad commit\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    assert validate_conventional_commits(runner=runner) == 1


def test_quality_gate_runs_commands_before_commit_validation() -> None:
    calls: list[Sequence[str]] = []

    def runner(command: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[0:2] == ("git", "merge-base"):
            return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")
        if command[0:2] == ("git", "log"):
            return subprocess.CompletedProcess(command, 0, stdout="feat: add config\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    assert run_quality_gate("pr", runner=runner) == 0
    pr_commands = list(commands_for_layer("pr"))
    assert calls[: len(pr_commands)] == pr_commands
    assert calls[-2:] == [
        ("git", "merge-base", "HEAD", "origin/main"),
        ("git", "log", "--format=%s", "abc123..HEAD"),
    ]


def test_validate_commit_message_file(tmp_path: Path) -> None:
    message_file = tmp_path / "COMMIT_EDITMSG"

    message_file.write_text("feat: add config\n\nbody\n", encoding="utf-8")
    assert validate_commit_message_file(str(message_file)) == 0

    message_file.write_text("Add config\n", encoding="utf-8")
    assert validate_commit_message_file(str(message_file)) == 1


def test_validate_squash_subject() -> None:
    assert validate_squash_subject("feat(cli): add command") == 0
    assert validate_squash_subject("Add command") == 1


def test_build_parser_describes_founder_quality_gates() -> None:
    parser = build_parser()

    assert parser.description is not None
    assert "Founder quality gates" in parser.description


def test_main_validates_commit_message_file(tmp_path: Path) -> None:
    message_file = tmp_path / "COMMIT_EDITMSG"
    message_file.write_text("feat: add config\n", encoding="utf-8")

    assert main(["--commit-msg-file", str(message_file)]) == 0


def test_main_validates_squash_subject() -> None:
    assert main(["--squash-subject", "feat(cli): add command"]) == 0


def test_main_validates_only_branch_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("founder.quality.validate_conventional_commits", lambda: 0)

    assert main(["--commits-only"]) == 0


def test_main_requires_layer_without_commit_message_file() -> None:
    with pytest.raises(SystemExit):
        main([])
