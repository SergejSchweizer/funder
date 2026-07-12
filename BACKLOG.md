# Backlog

Last reviewed: 2026-07-12

This backlog captures known work that should stay visible across sessions. Keep entries short, actionable, and tied to risks or decisions where possible.

Every PR-sized backlog item must include `Git status` and `PR`. Use `Git status: not started` and `PR: TBD` until work begins.

## Search And Fetch Module PR Stack

### PR01. Project Package And Quality Baseline

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/1.

Depends on: initial documentation baseline.

Scope: Add `pyproject.toml`, source package skeleton, test skeleton, CLI entry point placeholders, dependency groups, Ruff configuration, pytest configuration, and README developer commands.

Acceptance: `python -m pytest`, `ruff check`, and the package import smoke test run locally; no EODHD token is read or required.

Idempotency: Re-running commands should not create or modify data files.

### PR02. Shared Configuration, HTTP, And Contract Primitives

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR01.

Scope: Add shared config loading from environment, an EODHD HTTP client with timeout/retry/rate-limit handling, typed contract models for search candidates, canonical universe rows, fetch runs, errors, and lake paths.

Acceptance: Unit tests cover missing token handling, URL construction without token logging, contract validation, and deterministic lake path construction.

Idempotency: Repeated client calls with the same mocked responses produce the same contract objects and never print secrets.

### PR03. Simple Bronze/Silver/Gold Lake Layout Contract

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR02.

Scope: Define the simple medallion lake layout: `data/bronze`, `data/silver`, `data/gold`, and `data/meta`; add schema docs for search outputs, canonical universe, quotes, fundamentals, coverage, and fetch manifests; update `.gitignore` so local lake data and DuckDB cache files stay out of Git.

Acceptance: Tests verify all lake paths and schemas; docs describe which module writes or reads each table.

Idempotency: Path/schema helpers are pure and deterministic.

### PR04. Search Module: EODHD Query And Raw Candidate Capture

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR03.

Scope: Implement `founder search` to call EODHD search and exchange-symbol endpoints for configured name filters such as `UCITS ETF`; write raw/near-raw search responses under `data/bronze/eodhd/search/run_date=YYYY-MM-DD/`; normalize candidate rows into `data/silver/search/search_run_id=.../candidates.parquet`.

Acceptance: Integration-safe tests use recorded or mocked EODHD responses; output includes names, ISINs, code, exchange, type, country, currency, source endpoint, and run id.

Idempotency: Re-running the same search run id overwrites or validates the same output atomically without duplicate rows.

### PR05. Search Module: Canonical ISIN Selection Contract

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR04.

Scope: Implement one-row-per-ISIN canonical selection from candidates, prefer `XETRA`, then deterministic fallback exchange ordering; exclude missing-ISIN rows from fetch input; write `canonical_universe.parquet` and `search_summary.json`.

Acceptance: Tests prove no duplicate ISINs, XETRA is always selected when available, fallback selection is stable, and missing ISIN rows are reported but not selected for fetch.

Idempotency: Same candidate input always produces byte-for-byte equivalent canonical content apart from allowed metadata timestamps.

### PR06. Search Module: Review Artifacts And Active Universe Pointer

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR05.

Scope: Add human-readable CSV export for review, update `data/meta/current_universe.json` to point at an approved canonical universe, and document the approval workflow.

Acceptance: Fetch can resolve the active universe path from metadata; docs explain how to approve a new search result without editing code.

Idempotency: Re-approving the same search run leaves the active pointer unchanged.

### PR07. Fetch Module: Input Contract Validation And Planning

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR06.

Scope: Implement `founder fetch plan` to read `canonical_universe.parquet`, validate required fields, reject duplicate or empty ISINs, derive EODHD symbols, and produce a fetch plan with per-listing start/end dates.

Acceptance: Tests cover valid canonical input, duplicate ISIN rejection, empty code/exchange rejection, and incremental date planning.

Idempotency: Planning reads existing metadata and produces stable plans without calling EODHD or writing quote data.

### PR08. Fetch Module: EOD Quote Download To Bronze

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR07.

Scope: Implement quote fetching for planned canonical listings; write raw EOD quote responses under `data/bronze/eodhd/quotes/run_date=YYYY-MM-DD/`; capture per-symbol successes, failures, retry status, and API call metadata.

Acceptance: Tests use mocked EODHD responses; failures are recorded without stopping the whole batch unless configured; token never appears in logs or files.

Idempotency: Re-running the same run id does not duplicate quote records and can resume failed symbols.

### PR09. Fetch Module: Normalize Quotes To Silver

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR08.

Scope: Normalize Bronze quote responses into `data/silver/quotes/year=YYYY/quotes.parquet` with columns for ISIN, code, exchange, date, OHLC, adjusted close, volume, currency, run id, and fetched time.

Acceptance: Tests verify schema, date parsing, numeric types, duplicate prevention by `(isin, exchange, code, date)`, and year partitioning.

Idempotency: Re-normalizing the same Bronze run is safe and produces no duplicate Silver quote rows.

### PR10. Fetch Module: Fundamentals And Identifier Mapping Capture

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR09.

Scope: Fetch ID mapping and fundamentals for canonical listings; archive complete raw payloads under Bronze; extract minimal Silver profile, holdings, allocation, and technical tables needed for filtering/reporting.

Acceptance: Tests cover missing fundamentals, nested payload preservation, selected field extraction, and schema stability.

Idempotency: Re-fetching the same run id records one latest payload per listing/run and preserves prior runs.

### PR11. Fetch Module: Coverage, Errors, And Monthly Refresh Behavior

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR10.

Scope: Add `data/meta/fetch_runs.parquet`, `coverage.parquet`, and `errors.parquet`; compute first/last quote dates, observed rows, missing periods, failed symbols, and next incremental fetch start with a small overlap window.

Acceptance: Tests cover first full fetch, monthly incremental fetch, overlap deduplication, partial failures, and coverage report generation.

Idempotency: A failed run can be resumed; successful reruns update manifests without duplicating quotes.

### PR12. Gold Inputs: Returns, Correlation, And Covariance Baseline

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR11.

Scope: Build initial `data/gold/returns`, `data/gold/correlation`, and `data/gold/covariance` outputs from Silver adjusted-close quotes for the active canonical universe.

Acceptance: Tests cover adjusted-close return calculation, date alignment, missing-data thresholds, correlation/covariance output schemas, and deterministic results for sample data.

Idempotency: Rebuilding the same `as_of` date replaces or validates the same Gold outputs without accumulating stale files.

### PR13. Finalization: End-To-End Dry Run, Docs, And Release Checklist

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR12.

Scope: Add an end-to-end dry-run command that executes search, canonical selection, fetch planning, mocked fetch, Silver normalization, coverage reporting, and Gold input generation; update README, ARCHITECTURE, RISKS, DECISIONS, and BACKLOG with final commands and known limitations.

Acceptance: One command validates the full mocked pipeline from search contract to Gold risk inputs; all repository tracking docs are current; backlog statuses and PR links are filled for completed stack items.

Idempotency: The final dry run is safe to execute repeatedly in a clean workspace and produces deterministic sample outputs.

## Future Work After Finalization

- Define portfolio constraints for the first minimum-risk optimization run. Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/6.
- Add Flatex-specific trade-preparation exports from portfolio weights. Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/6.
- Add missing-ISIN review, currency handling, and survivorship-bias handling. Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/6.
- Automate documentation refreshes for architecture, risks, decisions, README facts, and generated project-history summaries. Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/6.

## Update Rules

Update this file whenever:

- Work is completed, deferred, split, or superseded.
- `RISKS.md` introduces a mitigation that requires follow-up work.
- `DECISIONS.md` records a decision with implementation tasks.
- A new dataset, external API, or quality gate is added.
- A PR is opened, pushed, merged, blocked, or otherwise changes status.