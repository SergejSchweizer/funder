from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TYPED_BRANCH_PATTERN = re.compile(r"^(feat|fix|refactor|docs|chore)/[a-z0-9]+(?:-[a-z0-9]+)*$")
OPEN_PR_TITLES = (
    "Three-Module Boundaries And Public Contract Skeleton",
    "Refresh Catalog Contracts And Stable Instrument Identities",
    "Selection Predicate And Metric-Requirement Contracts",
    "Selection Identity, Candidate And Final Membership Contracts",
    "Update Contracts, Pinned Inputs, And Shared Work Planner",
    "Refresh Complete EODHD Catalog Synchronization",
    "Refresh All-ISIN Market Data And Versioned Inputs",
    "Refresh Service, Standalone CLI, And Atomic Publication",
    "Selection Service, Current Pointer, And Standalone CLI",
    "Update Incremental Per-ISIN Metric Cache",
    "Update Screening Classifications And Selection Finalization",
    "Update Selection Calendar And Comparable Metric Cache",
    "Update Incremental Pair Metric Cache",
    "Update Evaluation Profiles And Selection Analysis Manifests",
    "Update Service, Standalone CLI, And Atomic Publication",
    "Three-Module Cutover, Legacy Migration, And Documentation",
)


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


def test_open_backlog_stack_follows_dependency_and_importance_order() -> None:
    backlog = (REPOSITORY_ROOT / "BACKLOG.md").read_text(encoding="utf-8")
    positions: list[int] = []

    for offset, title in enumerate(OPEN_PR_TITLES):
        pr_number = 40 + offset
        heading = f"### PR{pr_number}. {title}"
        start = backlog.index(heading)
        end = backlog.find("\n### ", start + 1)
        section = backlog[start : len(backlog) if end == -1 else end]
        dependency = "PR39" if pr_number == 40 else f"PR{pr_number - 1}"

        positions.append(start)
        assert f"Depends on: {dependency}." in section

    assert positions == sorted(positions)


def test_backlog_series_completion_gate_lists_required_main_checks() -> None:
    backlog = (REPOSITORY_ROOT / "BACKLOG.md").read_text(encoding="utf-8")
    gate = backlog.split("### Series Completion Gate", maxsplit=1)[1]

    for required_text in (
        "Final branch: `refactor/three-module-cutover`.",
        "type(optional-scope): subject",
        "Ruff lint and format",
        "architecture/import-boundary checks",
        "Pyright strict",
        "Pytest",
        "coverage of at least 95%",
        "schema validation",
    ):
        assert required_text in gate


def test_github_merge_workflows_validate_and_use_squash_subject() -> None:
    merge_gate_workflow = (REPOSITORY_ROOT / ".github/workflows/merge-gate.yml").read_text(
        encoding="utf-8"
    )
    pr_workflow = (REPOSITORY_ROOT / ".github/workflows/pr-quality.yml").read_text(encoding="utf-8")
    merge_workflow = (REPOSITORY_ROOT / ".github/workflows/auto-merge.yml").read_text(
        encoding="utf-8"
    )

    assert "pr-lint-quality" in pr_workflow
    assert "pr-type-quality" in pr_workflow
    assert "pr-unit-tests-${{ matrix.shard }}" in pr_workflow
    assert "pr-integration-tests-${{ matrix.shard }}" in pr_workflow
    assert "merge-lint-quality" in merge_gate_workflow
    assert "merge-type-quality" in merge_gate_workflow
    assert "merge-unit-tests-${{ matrix.shard }}" in merge_gate_workflow
    assert "merge-integration-tests-${{ matrix.shard }}" in merge_gate_workflow
    assert "scripts/pytest_shard.py" in pr_workflow
    assert "scripts/pytest_shard.py" in merge_gate_workflow
    assert "--suite unit" in pr_workflow
    assert "--suite integration" in pr_workflow
    assert "-n auto" in pr_workflow
    assert "-n auto" in merge_gate_workflow
    assert "uv run founder-quality --commits-only" in pr_workflow
    assert "uv run founder-quality --commits-only" in merge_gate_workflow
    assert "uv run python -m founder.schema_validation" in merge_gate_workflow
    assert "uv run coverage combine coverage-shards" in merge_gate_workflow
    assert "uv run coverage report --fail-under=95" in merge_gate_workflow
    assert 'uv run founder-quality --squash-subject "$SQUASH_SUBJECT"' in merge_gate_workflow
    assert "workflows: [merge-gate]" in merge_workflow
    assert "is still a draft; skipping auto-merge" in merge_workflow
    assert "Invalid squash subject" in merge_workflow
    assert '--squash --delete-branch --subject "$PR_TITLE"' in merge_workflow
