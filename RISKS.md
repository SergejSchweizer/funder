# Risks

Last reviewed: 2026-07-19

## Table Of Contents

- [How To Read Risks](#how-to-read-risks)
- [R001. Exchange API Reliability Can Silently Reduce Historical Completeness](#r001-exchange-api-reliability-can-silently-reduce-historical-completeness)
- [R002. Dataset Naming Drift Can Break Bronze, Silver, and Gold Joins](#r002-dataset-naming-drift-can-break-bronze-silver-and-gold-joins)
- [R003. Large Refactors Can Blur Architecture Boundaries](#r003-large-refactors-can-blur-architecture-boundaries)
- [R004. Coverage and Strict Typing Can Drift After Broad Edits](#r004-coverage-and-strict-typing-can-drift-after-broad-edits)
- [R005. Documentation Snapshots Can Become Stale Relative to the Lake](#r005-documentation-snapshots-can-become-stale-relative-to-the-lake)
- [R006. ETF Universe Discovery Can Be Incomplete or Duplicated](#r006-etf-universe-discovery-can-be-incomplete-or-duplicated)
- [R007. Risk-Aware Weights Can Be Misleading Without Clean Inputs And Evaluation](#r007-risk-aware-weights-can-be-misleading-without-clean-inputs-and-evaluation)
- [R008. Search And Bronze Contract Drift Can Corrupt The Lake](#r008-search-and-bronze-contract-drift-can-corrupt-the-lake)
- [R009. Dense Correlation Storage Can Become Unqueryable At Large Universe Size](#r009-dense-correlation-storage-can-become-unqueryable-at-large-universe-size)
- [R010. Hosted Multi-Tenant Access Can Leak Provider Data Or Credentials](#r010-hosted-multi-tenant-access-can-leak-provider-data-or-credentials)
- [Update Rules](#update-rules)

This file tracks active operational, data correctness, and architecture risks. Keep it aligned with `AGENTS.md` and project history when commits introduce or retire meaningful risks.

## How To Read Risks

Read risks before changing ingestion, storage contracts, quality gates, or portfolio outputs. This file should identify what can go wrong and how to mitigate it; detailed module usage belongs in architecture and workflow docs.

## R001. Exchange API Reliability Can Silently Reduce Historical Completeness

Status: Active

Signal: External API route errors, retry behavior, rate limits, and long-running trade backfills appear repeatedly in project history.

Mitigation: Keep debug logs, checkpoint keys, deterministic windows, bounded bronze concurrency, per-layer run locks, request pacing, `Retry-After` aware retries, and completeness reports aligned before changing Bronze, Silver, or Gold execution.

## R002. Dataset Naming Drift Can Break Bronze, Silver, and Gold Joins

Status: Active

Signal: Dataset names have changed over time, including volatility cleanup and explicit OHLCV dataset naming.

Mitigation: Rename work must update registry specs, lake paths, contracts, CLI choices, manifests, tests, and docs in one change.

## R003. Large Refactors Can Blur Architecture Boundaries

Status: Active

Signal: Project history includes extraction work across loader, lake, Silver, and Gold services.

Mitigation: Keep dependency direction and side effects explicit; verify with architecture/import checks and focused regression tests.

## R004. Coverage and Strict Typing Can Drift After Broad Edits

Status: Active

Signal: Quality-gate commits show type coverage and test coverage are active project risks.

Mitigation: Require the `main-quality` merge gate to pass Ruff lint and format, Pyright strict, Pytest, at least 95% coverage, Import Linter contracts, and dataset schema-registry validation.

## R005. Documentation Snapshots Can Become Stale Relative to the Lake

Status: Active

Signal: README coverage statistics and missing-day details have been refreshed several times.

Mitigation: Regenerate or explicitly date coverage snapshots when lake content, dataset names, or coverage reporting changes. Use `uv run founder-docs-refresh` to write the tracked documentation review report before finalizing docs-heavy changes.

## R006. ETF Universe Discovery Can Be Incomplete or Duplicated

Status: Active

Signal: EODHD Search API is capped at 500 results, while exchange symbol-list enumeration found 8,165 instruments with `UCITS ETF` in the name across ETF and fund types.

Mitigation: Use exchange enumeration for broad discovery, record the checked exchange count, deduplicate to one canonical listing per ISIN, prefer XETRA when available, validate outputs before quote ingestion, and keep the deterministic dry run green.

## R007. Risk-Aware Weights Can Be Misleading Without Clean Inputs And Evaluation

Status: Active

Signal: The project goal depends on covariance, drawdown, tail-risk, and backtest estimates from thousands of ETF EOD quote histories.

Mitigation: Validate quote-history coverage, missing dates, duplicate listings, currency effects, stale prices, Gold return/covariance inputs, drawdowns, CVaR, walk-forward behavior, rebalancing turnover, transaction-cost assumptions, explicit optimization constraints, and Flatex export assumptions before publishing portfolio weights.

## R008. Search And Bronze Contract Drift Can Corrupt The Lake

Status: Active

Signal: The Search module selects the canonical universe, while the Bronze module will store full data for every selected ISIN.

Mitigation: Keep the module boundary contract versioned and tested. Bronze must reject duplicate ISINs, missing ISINs, missing symbols, and schema mismatches before writing lake data.

## R009. Dense Correlation Storage Can Become Unqueryable At Large Universe Size

Status: Active

Signal: The target universe may reach 150,000 ISINs, which implies billions of possible pair statistics.

Mitigation: Store scalable pair-search outputs as bucketed `gold/correlation_edges` rows with upper-triangle pairs, common-date observation metadata, threshold filtering, and top-k limiting before adding dense matrix or sparse-array storage.

## R010. Hosted Multi-Tenant Access Can Leak Provider Data Or Credentials

Status: Active

Signal: The hosted roadmap adds Google identities, persistent EODHD credentials, shared physical market data, shared
statistics caches, API/Web surfaces, and public deployment hardening.

Mitigation: Implement PR84-PR100 in order. Keep EODHD credentials envelope-encrypted with an external KEK, enforce
PostgreSQL Row-Level Security on user-owned data, publish user grants only after successful user-key-backed provider
requests, pin every analysis to immutable User Data Snapshots, require exact input-hash authorization before reusing
shared artifacts, and keep public-hosted mode blocked until licensing, privacy, backup, credential, and security gates
are green.

## Update Rules

Update this file whenever:

- A risk becomes newly active, retired, or materially changed.
- A mitigation changes because tests, logging, contracts, or docs changed.
- A release or migration changes operational behavior.

If project history tooling is available, regenerate or review risk evidence with:

```bash
uv run python scripts/update_project_history_docs.py
```
