# Architecture

Last reviewed: 2026-07-13

## Table Of Contents

- [Purpose](#purpose)
- [Module Overview](#module-overview)
- [Current Shape](#current-shape)
- [Module Boundary](#module-boundary)
- [Simple Lake Layout](#simple-lake-layout)
- [Portfolio Analysis And Evaluation](#portfolio-analysis-and-evaluation)
- [Boundaries](#boundaries)
- [Validation Boundary](#validation-boundary)
- [Update Rules](#update-rules)

## Purpose

This project analyzes EODHD end-of-day ETF quotes and builds risk-aware fund portfolio weights. The architecture should keep instrument discovery, quote ingestion, storage contracts, transformation logic, portfolio evaluation, optimization, and validation gates separated so changes can be tested locally and reviewed safely.

## Module Overview

```text
		  local env / EODHD token
			   |
			   v
		 +--------------------+
		 | config + http      |
		 | load settings and  |
		 | pace API requests  |
		 +---------+----------+
			   |
			   v
+----------+      +--------+---------+      +----------------+
| paths,   |<---->| search           |----->| universe_review|
| schemas, |      | discover and     |      | inspect missing|
| table_io |      | approve universe |      | identifiers    |
+----+-----+      +--------+---------+      +----------------+
     |                     |
	|                     v
	|            +--------+---------+
     +----------->| bronze            |
		  | plan and archive |
		  +--------+---------+
			   |
			   v
		  +--------+---------+
		  | silver           |
		  | quote build      |
		  +--------+---------+
			   |
			   v
		  +--------+---------+
		  | gold             |
		  | returns, risk,   |
		  | covariance       |
		  +--------+---------+
			   |
			   v
		  +--------+---------+
		  | evaluation       |
		  | frontier,        |
		  | drawdown, tests  |
		  +--------+---------+
			   |
			   v
		  +--------+---------+      +----------------+
		  | portfolio        |----->| trading        |
		  | constraints and  |      | Flatex export  |
		  | target weights   |      | preparation    |
		  +--------+---------+      +----------------+
			   |
			   v
		  +--------+---------+
		  | pipeline + cli   |
		  | dry run and user |
		  | entry points     |
		  +------------------+

	quality + docs_refresh validate and document the whole flow
```

`founder.config` owns environment configuration. It loads EODHD settings, request timeouts, retry counts, request spacing, and backoff values without exposing secrets to logs or generated artifacts.

`founder.http` owns EODHD HTTP access. It builds tokenized requests, redacts secrets from errors, spaces requests, retries transient failures, and honors `Retry-After` for rate-limit responses.

`founder.logging` owns uniform module logging. It configures `.logs/founder-YYYY-MM-DD.log`, supports DEBUG verbosity for CLI commands, zips plain logs older than seven days, and deletes zip archives older than one month.

`founder.__init__` owns the package import surface. It keeps the package importable and exposes the package version without triggering configuration loading, API calls, or lake writes.

`founder.contracts` owns typed cross-module data contracts. It defines validated dataclasses for Search candidates, canonical universe rows, bronze runs, and bronze errors when code needs stronger structure than plain row dictionaries.

`founder.paths` owns lake artifact locations. It keeps Bronze, Silver, and Gold path construction deterministic so modules do not hard-code filesystem layouts.

`founder.schemas` owns required table fields. It gives Search, Bronze, coverage, and tests one place to check the shape of table contracts before data moves between layers.

`founder.table_io` owns current table serialization. It reads and writes JSON objects, physical Parquet row tables, and review CSVs behind helper functions so storage details stay out of module logic.

`founder.search` owns discovery normalization and universe approval. It writes raw candidate payloads, normalizes Search rows, selects one canonical listing per non-empty ISIN, exports review artifacts, and writes the active universe pointer for Bronze.

`founder.bronze` owns data loading for the approved universe. It validates canonical rows, builds EODHD symbols, writes bronze plans, archives quote, dividends, and splits payloads, logs non-secret errors, and writes operational coverage manifests. It is designed for unattended cron execution with bounded EODHD parallelism, default concurrency `2`, shared request pacing, `Retry-After` handling, resumable runs, and no overlapping writes for the same lake root and run id.

`founder.silver` owns Bronze-to-Silver market data builds. It reads archived quote rows, validates schema and merge keys, and writes one Silver quote file per exchange and ISIN without calling EODHD. Silver writes listing files with bounded parallelism and defaults to two worker threads.

`founder.universe_review` owns pre-optimization universe checks. It summarizes missing ISINs, currency exposure, and survivorship-bias warnings so weak inputs are visible before portfolio weights are trusted.

`founder.gold` owns portfolio-ready risk inputs. It builds adjusted-close returns, correlations, covariance rows, and per-asset feature rows from validated Silver quote history. Gold processes listings with bounded parallelism, defaults to two workers, avoids duplicate symmetric pair calculations, and uses a per-listing Gold run manifest to resume unchanged input snapshots.

`founder.evaluation` owns portfolio analysis datasets that compare candidate portfolios and optimization techniques. It consumes Gold return inputs and writes aligned return matrices, asset metrics, portfolio return series, drawdowns, and portfolio metrics today; later evaluation work extends this boundary with efficient-frontier points, walk-forward backtests, rebalancing simulations, and tail-risk diagnostics without calling EODHD.

`founder.portfolio` owns optimization constraints and target weights. It validates long-only bounds, minimum and maximum weights, quote-coverage assumptions, and objective settings for constrained minimum variance, risk parity, hierarchical risk parity, maximum diversification, CVaR, and related optimizers.

`founder.trading` owns Flatex trade-preparation exports. It converts approved target weights, latest prices, and canonical listing metadata into broker-ready CSV order rows without calling broker APIs or deciding the optimization objective.

`founder.pipeline` owns the deterministic dry-run workflow. It stitches Search, Bronze, Silver quote building, coverage, and Gold inputs together with sample data so users can verify the architecture without credentials.

`founder.cli` owns command-line entry points. It parses user commands and routes them to repeatable workflows such as `founder dry-run` without embedding business logic in the CLI layer.

`founder.quality` owns repository validation commands. It runs the local PR and main gates used by GitHub workflows, including formatting, linting, typing, tests, coverage, working-tree checks, and Conventional Commit validation.

`founder.docs_refresh` owns documentation review reporting. It scans tracked documentation files for review markers and writes `docs/docs_refresh_report.json` so docs-heavy changes can verify that documentation stayed current.

## Current Shape

- **Discovery**: EODHD search and exchange symbol-list enumeration identify ETF and fund universes by ticker, name, ISIN, exchange, and type.
- **Bronze**: Raw EODHD API responses and quote ingestion outputs.
- **Silver**: Normalized ETF quote and instrument datasets with stable identifiers, schema checks, and coverage metadata.
- **Gold**: Portfolio-ready return, covariance, correlation, asset-feature, evaluation, risk, and optimized-weight datasets derived from validated Silver inputs.
- **Evaluation**: Return matrices, asset metrics, portfolio return series, drawdowns, and portfolio metrics consume Gold inputs and stay separate from market-data ingestion. Efficient-frontier points, robust optimization diagnostics, walk-forward backtests, rebalancing simulations, and tail-risk analysis build on that boundary.
- **Portfolio**: Constraint validation and target weights consume Gold evaluation inputs and stay separate from market-data ingestion.
- **Trading**: Flatex export helpers turn approved target weights into broker-ready order rows without calling broker APIs.
- **Validation**: Focused tests first, followed by full quality gates for behavior, typing, formatting, architecture boundaries, and at least 95% test coverage before main merges.
- **Configuration**: Secrets and local credentials live in ignored local environment files such as `.env.local`.
- **Logging**: Shared Founder logging writes uniformly formatted `.logs/` files with debug verbosity and retention.
- **Dry run**: `founder dry-run` executes the mocked pipeline from Search through Gold inputs without credentials.
- **Docs refresh**: `founder-docs-refresh` writes a generated documentation review report for tracked repository docs.

## Module Boundary

- **Search module**: owns filtered EODHD discovery, candidate normalization, one-row-per-ISIN canonical selection, XETRA preference, review artifacts, and the active universe pointer.
- **Bronze module**: owns canonical-universe validation, bronze planning, EOD quotes, additional EODHD listing datasets, Bronze writes, operational coverage, and bronze error logging.
- **Silver module**: owns Bronze-to-Silver quote builds and analytical Silver quote files.
- **Universe review module**: owns missing-ISIN, currency-exposure, and survivorship-bias review summaries before optimization consumes a universe.
- **Evaluation module**: owns portfolio analytics and comparison datasets derived from Gold returns, correlation, and covariance.
- **Portfolio module**: owns explicit optimization constraints and selected target weights.
- **Trading module**: owns Flatex CSV order preparation from approved target weights and latest prices.
- **Contract**: Bronze consumes only the Search module's approved `canonical_universe.parquet`; Bronze must not perform fuzzy discovery, and Search must not bronze full quote history.

## Simple Lake Layout

- **Bronze**: raw or near-raw EODHD search, quote, dividends, splits, and mapping payloads.
- **Silver**: normalized candidates, canonical universe, one quote file per exchange and ISIN, and coverage-ready tables.
- **Gold**: portfolio-ready returns, correlation, covariance, evaluation metrics, frontier points, backtests, risk inputs, and portfolio weights.
- **Silver operational datasets**: active universe pointer, bronze plans, bronze runs, coverage, errors, and dataset version metadata stored under focused Silver directories.

## Portfolio Analysis And Evaluation

Portfolio evaluation should be reproducible from existing Gold risk inputs and should not require Search, Bronze, EODHD credentials, or broker access. The planned analysis scope is risk-first because the ETF universe is large, return forecasts are noisy, and many UCITS ETF listings are highly correlated.

The evaluation layer computes aligned return matrices, asset-level metrics, portfolio return series, cumulative wealth, drawdown series, maximum drawdown, drawdown duration, recovery duration, Calmar ratio, and ulcer index from Gold return files. It should later add efficient-frontier points, frontier weights, walk-forward backtests, rebalancing simulations, VaR, CVaR, and tail scenario diagnostics.

The portfolio layer should compare equal-weight, constrained minimum variance, maximum Sharpe as a comparison objective, target-return minimum variance, risk parity, hierarchical risk parity, maximum diversification, and CVaR-aware target weights. Constrained minimum variance and risk parity are the first candidates for trusted production weights; maximum Sharpe remains a comparison result until expected-return assumptions are validated out of sample.

## Boundaries

- Discovery, bronze planning, checkpointing, bounded parallelism, cron safety, retries, and completeness reporting belong near ingestion code.
- Search and Bronze communicate through explicit versioned contracts, not shared mutable state.
- Dataset names, lake paths, contracts, manifests, CLI choices, and tests must move together.
- Transformation code should depend on explicit inputs and contracts, not hidden global state.
- Evaluation and optimization code should consume Gold return, correlation, covariance, and metric datasets with explicit constraints, not raw API responses.
- Trade-preparation code should consume approved weights, prices, and canonical listing metadata; it must not decide the optimization objective.
- Documentation snapshots must state their review date or be regenerated from source data.
- Table serialization is isolated behind `founder.table_io` so modules write physical Parquet tables without embedding storage-engine details.

## Validation Boundary

Validation belongs at module boundaries and repository gates. Module-level tests should prove contracts, paths, and side effects close to the owning code. Repository-level commands and GitHub merge policy are documented in [README.md](README.md) and [AGENTS.md](AGENTS.md), so this architecture document does not repeat the full quality-gate checklist.

## Update Rules

Update this file whenever a change alters one of these items:

- A layer boundary or dependency direction.
- Dataset ownership, naming, contracts, or lake paths.
- Validation gates, architecture checks, or required release commands.
- Local configuration conventions that affect reproducibility.
- Logging format, retention, or debug behavior.

Before merging architecture changes, update `RISKS.md`, `DECISIONS.md`, and `BACKLOG.md` when the change creates, resolves, or reprioritizes work.