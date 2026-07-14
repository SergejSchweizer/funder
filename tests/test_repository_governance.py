from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TYPED_BRANCH_PATTERN = re.compile(r"^(feat|fix|refactor|docs|chore)/[a-z0-9]+(?:-[a-z0-9]+)*$")


def test_open_backlog_stack_uses_typed_branch_paths() -> None:
    backlog = (REPOSITORY_ROOT / "BACKLOG.md").read_text(encoding="utf-8")

    for pr_number in range(40, 56):
        start = backlog.index(f"### PR{pr_number}.")
        end_markers = [
            marker
            for marker in (
                backlog.find("\n### PR", start + 1),
                backlog.find("\n### Series", start + 1),
            )
            if marker != -1
        ]
        section = backlog[start : min(end_markers)]
        branch_match = re.search(r"^Branch: `([^`]+)`\.$", section, flags=re.MULTILINE)

        assert branch_match is not None, f"PR{pr_number} has no Branch entry"
        assert TYPED_BRANCH_PATTERN.fullmatch(branch_match.group(1))


def test_backlog_series_completion_gate_lists_required_main_checks() -> None:
    backlog = (REPOSITORY_ROOT / "BACKLOG.md").read_text(encoding="utf-8")
    gate = backlog.split("### Series Completion Gate", maxsplit=1)[1]

    for required_text in (
        "Final branch: `refactor/three-module-cutover`.",
        "type(optional-scope): subject",
        "Ruff lint and format",
        "Pyright strict",
        "Pytest",
        "coverage of at least 95%",
        "Import Linter",
        "schema validation",
    ):
        assert required_text in gate


def test_github_merge_workflows_validate_and_use_squash_subject() -> None:
    main_workflow = (REPOSITORY_ROOT / ".github/workflows/main-quality.yml").read_text(
        encoding="utf-8"
    )
    merge_workflow = (REPOSITORY_ROOT / ".github/workflows/auto-merge.yml").read_text(
        encoding="utf-8"
    )

    assert "uv run founder-quality main" in main_workflow
    assert 'uv run founder-quality --squash-subject "$SQUASH_SUBJECT"' in main_workflow
    assert "is still a draft; skipping auto-merge" in merge_workflow
    assert "Invalid squash subject" in merge_workflow
    assert '--squash --delete-branch --subject "$PR_TITLE"' in merge_workflow
