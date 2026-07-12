# Backlog

Last reviewed: 2026-07-12

This backlog captures known work that should stay visible across sessions. Keep entries short, actionable, and tied to risks or decisions where possible.

Every PR-sized backlog item must include `Git status` and `PR`. Use `Git status: not started` and `PR: TBD` until work begins.

## Now

- Scaffold the Python package layout for EODHD discovery, quote ingestion, validation, and portfolio optimization. Git status: not started. PR: TBD.
- Turn the manual `UCITS ETF` exchange enumeration and canonical ISIN selection into a repeatable command that writes token-free outputs. Git status: not started. PR: TBD.
- Define how EODHD EOD historical quotes will be fetched, stored, and validated without committing secrets. Git status: not started. PR: TBD.
- Add dependency and run instructions once the package structure is present. Git status: not started. PR: TBD.

## Next

- Add tests or smoke checks for EODHD discovery, canonical ISIN selection, and quote ingestion before relying on historical completeness. Git status: not started. PR: TBD.
- Define portfolio constraints for the first minimum-risk optimization run. Git status: not started. PR: TBD.
- Document dataset names, lake paths, and schema contracts for instruments, canonical listings, quotes, returns, covariance, and weights. Git status: not started. PR: TBD.
- Add a repeatable quality gate command once test, lint, and type tools are present. Git status: not started. PR: TBD.

## Later

- Add completeness reporting for ETF quote-history coverage. Git status: not started. PR: TBD.
- Add missing-ISIN review, currency handling, and survivorship-bias handling. Git status: not started. PR: TBD.
- Automate documentation refreshes for architecture, risks, decisions, README facts, and generated project-history summaries. Git status: not started. PR: TBD.
- Add release or migration notes for dataset renames and contract changes. Git status: not started. PR: TBD.

## Update Rules

Update this file whenever:

- Work is completed, deferred, split, or superseded.
- `RISKS.md` introduces a mitigation that requires follow-up work.
- `DECISIONS.md` records a decision with implementation tasks.
- A new dataset, external API, or quality gate is added.
- A PR is opened, pushed, merged, blocked, or otherwise changes status.