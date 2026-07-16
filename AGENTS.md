# Agent Workflow And Generated Risks

Last reviewed: 2026-07-14

## Table Of Contents

- [Project Workflow Rules](#project-workflow-rules)
- [Generated Risk Context](#generated-risk-context)
- [R001. Exchange API reliability can silently reduce historical completeness](#r001-exchange-api-reliability-can-silently-reduce-historical-completeness)
- [R002. Dataset naming drift can break Bronze, Silver, and Gold joins](#r002-dataset-naming-drift-can-break-bronze-silver-and-gold-joins)
- [R003. Large refactors can blur architecture boundaries](#r003-large-refactors-can-blur-architecture-boundaries)
- [R004. Coverage and strict typing can drift after broad edits](#r004-coverage-and-strict-typing-can-drift-after-broad-edits)
- [R005. Documentation snapshots can become stale relative to the lake](#r005-documentation-snapshots-can-become-stale-relative-to-the-lake)

This file is the workflow reference for coding agents and maintainers. It should be read after [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md), and the task-specific docs for the area being changed.

## Project Workflow Rules

- Every non-merged PR-sized item recorded in `BACKLOG.md` must include a branch path, Git status, and PR link. Historical merged entries do not require branch-path backfills.
- Use branch paths in the form `<type>/<scope>-<short-description>` with lowercase ASCII letters, numbers, and hyphens only after the slash.
- Allowed branch path types are `feat`, `fix`, `refactor`, `docs`, and `chore`.
- Use `feat/` for new behavior, `fix/` for defect correction, `refactor/` for behavior-preserving structural or performance work, `docs/` for documentation-only changes, and `chore/` for build, CI, test-only, style, dependency, or repository-maintenance work.
- The branch path type must reflect the primary PR purpose. The PR title and final squash subject must use the most precise compatible Conventional Commit type.
- Every open PR series in `BACKLOG.md` must end with an explicit `Series Completion Gate` that lists the final branch, squash-subject rule, and required `merge-gate` checks.
- Use `Branch: <type>/<scope>-<short-description>` until a planned branch is created, then keep the exact published branch path in the backlog entry.
- Use `Git status: not started` and `PR: TBD` until work begins.
- Replace `PR: TBD` with the pull request URL once the PR exists.
- Update the Git status as work moves through planned, in progress, pushed, merged, or blocked.
- A PR that has run and passed `merge-gate` counts as approved for merge.
- `pr-quality` is the fast branch and PR feedback gate. It runs `uv run founder-quality pr`, which performs Ruff lint and format checks, Pyright strict type checking, and the normal Pytest suite without coverage.
- `merge-gate` is the required protected-main merge gate. It runs `uv run founder-quality merge` and must pass Ruff lint and format checks, architecture/import-boundary checks, Pyright strict type checking, Pytest with at least 95% coverage, and dataset schema-registry validation.
- PR titles must follow `type(optional-scope): subject` because the title becomes the squash-merge commit subject.
- Squash merges must set the final commit subject to the validated PR title; changing the title requires `merge-gate` to pass again.
- GitHub branch protection should require `merge-gate` and should not require a separate approving review when `merge-gate` has passed.
- Same-repository PRs with a passing `merge-gate` workflow may be squash-merged automatically and have their branch deleted.

## Generated Risk Context

This section is generated from recurring themes in first-parent `git log`.

Update command:

```bash
uv run python scripts/update_project_history_docs.py
```

Risk review rules:

- Update risks when commits introduce or retire operational, data correctness, or architecture risks.
- Prefer concrete mitigations that map to tests, logs, contracts, or docs.
- Keep stale risks only if the mitigation still needs active attention.

## R001. Exchange API reliability can silently reduce historical completeness

Status: Active

Signal: Deribit route errors, retry behavior, and long-running trade backfills appear repeatedly in the history.

Mitigation: Keep debug logs, checkpoint keys, deterministic windows, and completeness reports aligned before changing bronze execution.

Evidence:

- 2026-07-10 `ccb6962` Merge pull request #72 from SergejSchweizer/codex/pr15-recent-trade-snapshot-silver
- 2026-07-04 `ca0e922` Rename option trades dataset to options_trades
- 2026-07-04 `11da15c` Rename options trades and perps OHLCV datasets
- 2026-07-03 `4393c40` Rename perpetual trades dataset
- 2026-07-01 `f55d766` [codex] Extract OHLCV symbol bronze planning (#46)
- 2026-06-29 `7232cc4` Extract bronze head gap planning (#42)

## R002. Dataset naming drift can break Bronze, Silver, and Gold joins

Status: Active

Signal: Dataset names have changed over time, including volatility cleanup and explicit OHLCV dataset naming.

Mitigation: Rename work must update registry specs, lake paths, contracts, CLI choices, manifests, tests, and docs in one change.

Evidence:

- 2026-07-10 `8902f6b` Merge pull request #77 from SergejSchweizer/codex/pr18-gold-regime-feature-contract
- 2026-07-09 `c43e3e3` Merge pull request #58 from SergejSchweizer/codex/pr01-silver-contract-registry-baseline
- 2026-07-04 `ca0e922` Rename option trades dataset to options_trades
- 2026-07-04 `ab5543d` Rename open_interest dataset to open interest
- 2026-07-04 `11da15c` Rename options trades and perps OHLCV datasets
- 2026-07-03 `c9d39e1` Rename spot_ohlcv OHLCV dataset

## R003. Large refactors can blur architecture boundaries

Status: Active

Signal: The log contains many extraction commits across loader, lake, Silver, and Gold services.

Mitigation: Keep dependency direction and side effects explicit; verify with architecture/import checks and focused regression tests.

Evidence:

- 2026-07-04 `ba93394` Add architecture documentation
- 2026-07-01 `4e203fb` [codex] Complete Bronze refactor stack (#51)
- 2026-07-01 `f55d766` [codex] Extract OHLCV symbol bronze planning (#46)
- 2026-07-01 `a2287a1` Align architecture and coverage refactor gates
- 2026-07-01 `a674417` Consolidate refactor boundary work
- 2026-06-29 `febd87e` Extract silver volatility transformation (#45)

## R004. Coverage and strict typing can drift after broad edits

Status: Active

Signal: Quality-gate commits show that type coverage and test coverage are active project risks.

Mitigation: Run focused tests first, then full pytest, Ruff, and type checks before merging behavior or boundary changes.

Evidence:

- 2026-07-10 `850150b` Add GitHub quality gate script
- 2026-07-10 `c0fca84` Sync stacked PR validation policy
- 2026-07-09 `2a57684` Extend volatility medallion coverage
- 2026-07-01 `225a01e` Update README coverage statistics
- 2026-07-01 `a2287a1` Align architecture and coverage refactor gates
- 2026-06-27 `931263d` Align validation gates (#17)

## R005. Documentation snapshots can become stale relative to the lake

Status: Active

Signal: README coverage statistics and missing-day details have been refreshed several times.

Mitigation: Regenerate or explicitly date coverage snapshots when lake content, dataset names, or coverage reporting changes.

Evidence:

- 2026-07-01 `225a01e` Update README coverage statistics
- 2026-06-29 `60fcfcb` Remove README missing-day detail label
- 2026-06-29 `0d1ce23` Fix README table of contents
- 2026-06-28 `660f9f2` Deduplicate README table of contents
- 2026-06-26 `40cc90e` Merge branch 'codex/docs-update-missing-values'
- 2026-05-25 `b8b5b82` Refine raw dataset docs and Deribit endpoint sections (#7)
