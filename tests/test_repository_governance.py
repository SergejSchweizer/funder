from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TYPED_BRANCH_PATTERN = re.compile(r"^(feat|fix|refactor|docs|chore)/[a-z0-9]+(?:-[a-z0-9]+)*$")
OPEN_PR_TITLES = (
    "Hosted Architecture Decision, Threat Model, And Active-Backlog Reset",
    "PostgreSQL Application Catalog, Migrations, Roles, And Row-Level Security",
    "Google-Only OpenID Connect And Server-Side Session Security",
    "Encrypted EODHD Credential Vault With External Key Management",
    "Shared Content-Addressed Market Observation Store",
    "User Data Entitlements, Download Provenance, And Immutable Snapshots",
    "User-Key-Backed EODHD Ingestion And Refresh Planner",
    "Scoped Analytical Input Boundary And Local Adapter Compatibility",
    "Content-Addressed Univariate And Return Artifact Cache",
    "Content-Addressed Bivariate Cache And Exact Alignment Identity",
    "Content-Addressed Multivariate, Portfolio, Backtest, And Report Artifacts",
    "Docker Compose PostgreSQL, API, Web, And Shared Runtime Storage",
    "FastAPI User, Credential, Download, Dataset, Project, And Analysis API",
    "Google-Authenticated Web UI And User-Scoped Research Funnel",
    "Public-Repository CI, Supply-Chain, Secret-Scanning, And Deployment Hardening",
    "Licensing, Privacy, Retention, Backup, Restore, And Key-Rotation Gate",
    "End-To-End Multi-User Isolation, Reproducibility, And Hosted Cutover",
)
OPEN_PR_DEPENDENCIES = {
    84: "current `main`",
    85: "PR84",
    86: "PR85",
    87: "PR86",
    88: "PR85",
    89: "PR87 and PR88",
    90: "PR89",
    91: "PR90",
    92: "PR91",
    93: "PR92",
    94: "PR93",
    95: "PR87 and PR91",
    96: "PR94 and PR95",
    97: "PR96",
    98: "PR95 and PR96",
    99: "PR98",
    100: "PR97 and PR99",
}

HOSTED_REQUIREMENTS_BY_PR = {
    84: "Architecture decision, threat model, and prohibited designs",
    85: "PostgreSQL catalog, roles, migrations, and RLS",
    86: "Google-only OIDC and server-side sessions",
    87: "Encrypted EODHD credential vault and KEK rotation",
    88: "Shared content-addressed market observation store",
    89: "User grants, provenance, and immutable snapshots",
    90: "User-key-backed ingestion and refresh planning",
    91: "Scoped analytical input boundary and local adapter compatibility",
    92: "Content-addressed univariate and return artifact cache",
    93: "Content-addressed bivariate cache and exact alignment",
    94: "Content-addressed portfolio, backtest, and report artifacts",
    95: "Docker Compose hosted development runtime",
    96: "FastAPI user, credential, download, project, and analysis API",
    97: "Google-authenticated Web UI and research funnel",
    98: "Public-repository CI, supply-chain, and deployment hardening",
    99: "Licensing, privacy, retention, backup, restore, and key-rotation readiness",
    100: "End-to-end hosted cutover and multi-user proof",
}


def test_open_backlog_stack_uses_typed_branch_paths() -> None:
    backlog = (REPOSITORY_ROOT / "BACKLOG.md").read_text(encoding="utf-8")

    for pr_number in range(84, 101):
        start = backlog.index(f"### PR{pr_number}.")
        end_markers = [
            marker
            for marker in (
                backlog.find("\n### PR", start + 1),
                backlog.find("\n## Series", start + 1),
            )
            if marker != -1
        ]
        section = backlog[start : len(backlog) if not end_markers else min(end_markers)]
        branch_match = re.search(r"^Branch: `([^`]+)`\.$", section, flags=re.MULTILINE)

        assert branch_match is not None, f"PR{pr_number} has no Branch entry"
        assert TYPED_BRANCH_PATTERN.fullmatch(branch_match.group(1))


def test_open_backlog_stack_follows_dependency_and_importance_order() -> None:
    backlog = (REPOSITORY_ROOT / "BACKLOG.md").read_text(encoding="utf-8")
    positions: list[int] = []

    for offset, title in enumerate(OPEN_PR_TITLES):
        pr_number = 84 + offset
        heading = f"### PR{pr_number}. {title}"
        start = backlog.index(heading)
        end = backlog.find("\n### ", start + 1)
        section = backlog[start : len(backlog) if end == -1 else end]
        dependency = OPEN_PR_DEPENDENCIES[pr_number]

        positions.append(start)
        assert f"Depends on: {dependency}." in section

    assert positions == sorted(positions)


def test_backlog_series_completion_gate_lists_required_main_checks() -> None:
    backlog = (REPOSITORY_ROOT / "BACKLOG.md").read_text(encoding="utf-8")
    gate = backlog.split("## Series Completion Gate", maxsplit=1)[1]

    for required_text in (
        "Final branch: `feat/hosted-multitenant-cutover`.",
        "type(optional-scope): subject",
        "Ruff lint and format",
        "Pyright strict",
        "Pytest",
        "at least 95% coverage",
        "import-boundary checks",
        "dataset-schema validation",
        "API/Web contract tests",
        "hosted-readiness validation",
    ):
        assert required_text in gate


def test_hosted_security_architecture_maps_goals_to_active_prs() -> None:
    architecture = (REPOSITORY_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    decisions = (REPOSITORY_ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    risks = (REPOSITORY_ROOT / "RISKS.md").read_text(encoding="utf-8")
    goals = (REPOSITORY_ROOT / "GOALS.md").read_text(encoding="utf-8")
    hosted = (REPOSITORY_ROOT / "docs/hosted_security_architecture.md").read_text(encoding="utf-8")

    assert "docs/hosted_security_architecture.md" in architecture
    assert "D016. Use PostgreSQL-First User-Key-Backed Hosted Architecture" in decisions
    assert "R010. Hosted Multi-Tenant Access Can Leak Provider Data Or Credentials" in risks
    assert "multi-tenant but user-key-backed" in goals

    for boundary in (
        "Browser",
        "Web app",
        "API service",
        "PostgreSQL",
        "External key-encryption key",
        "Shared immutable store",
        "EODHD",
    ):
        assert boundary in hosted

    for forbidden in (
        "Plaintext EODHD keys",
        "global current-selection pointers",
        "Public-hosted mode",
    ):
        assert forbidden in hosted

    for pr_number, requirement in HOSTED_REQUIREMENTS_BY_PR.items():
        assert f"| {requirement} | PR{pr_number} |" in hosted


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
