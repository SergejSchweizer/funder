# Quality Gates

Last reviewed: 2026-07-19

## Purpose

`GATES.md` is the canonical documentation for Founder quality gates, GitHub branch protection, auto-merge, and local validation commands. Other repository documents should link here instead of repeating the full gate contract.

## Current Shape

Founder uses two CI layers:

- `pr-quality`: fast pre-merge feedback and the required protected-branch check.
- `merge-gate`: full post-merge validation for the exact commit that lands on `main`.

The shard count is intentionally kept at `4` for Unit and Integration tests. Current CI runtime is dominated more by runner setup, checkout, dependency installation, and artifact handling than by individual test execution, so further splitting is not expected to improve wall-clock time yet.

Required check families:

- Ruff lint and format.
- Hosted public-repository security gates.
- Pyright strict typing.
- Pytest Unit and Integration shards.
- Coverage threshold enforcement on `main`.
- Architecture checks.
- Dataset schema validation.
- Conventional Commit validation.

## GitHub Flow

```text
feature branch push / pull_request
        |
        v
+-------------------------------+
| pr-quality                    |
| required before merge         |
+-------------------------------+
| pr-lint-quality               |
| pr-type-quality               |
| pr-unit-tests-1..4            |
| pr-integration-tests-1..4     |
+-------------------------------+
        |
        v
+-------------------------------+
| pr-quality aggregate          |
| stable required check name    |
+-------------------------------+
        |
        v
+-------------------------------+
| auto-merge                    |
| same-repo non-draft PR only   |
| squash subject = PR title     |
+-------------------------------+
        |
        v
main
        |
        v
+-------------------------------+
| merge-gate                    |
| full post-merge validation    |
+-------------------------------+
```

## `pr-quality`

Trigger:

- `pull_request`
- `push` to non-`main` branches

Purpose:

- Give fast feedback during development.
- Provide one stable required check name for branch protection.
- Validate the PR title because the title becomes the final squash commit subject.
- Drive same-repository auto-merge.

Jobs:

```text
pr-quality
    |
    +-- pr-lint-quality
    |       ruff check .
    |       ruff format --check .
    |       python -m founder.security_gates
    |       founder-quality --commits-only
    |       founder-quality --squash-subject "$SQUASH_SUBJECT"
    |
    +-- pr-type-quality
    |       pyright
    |
    +-- pr-unit-tests-[1..4]
    |       scripts/pytest_shard.py --suite unit --shard-index N --shard-count 4 -- -q -n auto
    |
    +-- pr-integration-tests-[1..4]
    |       scripts/pytest_shard.py --suite integration --shard-index N --shard-count 4 -- -q -n auto
    |
    +-- pr-quality aggregate
            fails if any required PR job failed
```

Local equivalent:

```bash
uv run founder-quality pr
```

The local pre-commit hook runs this same PR gate before accepting commits.

## `merge-gate`

Trigger:

- `push` to `main`

Purpose:

- Validate the exact merged commit on `main`.
- Run the heavier coverage, schema, and architecture checks without duplicating the full suite on every PR update.
- Keep the post-merge signal visible even when auto-merge is used.

Jobs:

```text
main push
    |
    v
merge-gate
    |
    +-- merge-lint-quality
    |       ruff check .
    |       ruff format --check .
    |       python -m founder.architecture_checks
    |       python -m founder.schema_validation
    |       python -m founder.security_gates
    |       founder-quality --commits-only
    |       git diff --quiet
    |       git diff --cached --quiet
    |
    +-- merge-type-quality
    |       pyright
    |
    +-- merge-unit-tests-[1..4]
    |       scripts/pytest_shard.py --suite unit --shard-index N --shard-count 4 -- -q -n auto
    |       coverage shard upload
    |
    +-- merge-integration-tests-[1..4]
    |       scripts/pytest_shard.py --suite integration --shard-index N --shard-count 4 -- -q -n auto
    |       coverage shard upload
    |
    +-- merge-gate aggregate
            download coverage shards
            coverage combine coverage-shards
            coverage report --fail-under=95
```

Local equivalent:

```bash
uv run founder-quality merge
```

Compatibility alias:

```bash
uv run founder-quality main
```

Coverage equivalent:

```text
pytest -n auto --cov=founder --cov-report=term-missing --cov-fail-under=95
```

## Auto-Merge

Auto-merge is handled by `.github/workflows/auto-merge.yml`.

```text
pr-quality workflow_run success
        |
        v
same repository?
        |
        v
non-draft PR?
        |
        v
PR title matches Conventional Commits?
        |
        v
gh pr merge --squash --delete-branch --subject "$PR_TITLE"
```

Auto-merge intentionally waits for `pr-quality`, not `merge-gate`. The `merge-gate` workflow is read from the default branch after the squash merge and validates the resulting `main` commit.

## Branch Protection

Required protected-branch status check for `main`:

```text
pr-quality
```

Current policy:

- `pr-quality` must pass before merge.
- `merge-gate` must pass after merge on `main`.
- Same-repository non-draft PRs with a passing `pr-quality` workflow may be squash-merged automatically.
- The final squash commit subject must be the validated PR title.

## Conventional Commits

Required subject shape:

```text
type(optional-scope): subject
```

Allowed types:

```text
build chore ci docs feat fix perf refactor revert style test
```

The rule applies to:

- branch commit subjects;
- PR titles;
- final squash commit subjects.

## Sharding Policy

Current setting:

```text
PYTEST_SHARD_COUNT=4
pytest-xdist: pytest -n auto inside every test shard
```

Do not increase shard count by default. Reconsider only when at least one Unit or Integration shard regularly exceeds 5 minutes after setup caching is already healthy.

## Update Rules

Update `GATES.md` whenever any of these change:

- `.github/workflows/pr-quality.yml`
- `.github/workflows/merge-gate.yml`
- `.github/workflows/auto-merge.yml`
- `src/founder/quality.py`
- branch protection required check names
- local pre-commit gate behavior
- shard count, coverage threshold, or required quality tools
