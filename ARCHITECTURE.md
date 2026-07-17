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
		  secret config / EODHD token
			   |
			   v
		 +--------------------+
		 | config + http      |
		 | load settings and  |
		 | pace API requests  |
		 +---------+----------+
			   |
			   v
+----------+      +------------------+
| paths,   |<---->| fetch_all_isins  |
| schemas, |      | full metadata    |
| table_io |      | reference        |
+----+-----+      +--------+---------+
     |                     |
     |                     v
     |            +--------+---------+
     +----------->| metadata_filter  |
     |            | metadata         |
     |            | selections       |
     |            +--------+---------+
     |                     |
     |                     v
     |            +--------+---------+
     +----------->| univariate_      |
     |            | statistics       |
     |            +--------+---------+
     |                     |
     |                     v
     |            +--------+---------+
     +----------->| univariate_      |
     |            | filter           |
     |            +--------+---------+
     |                     |
     |                     v
     |            +--------+---------+
     +----------->| bivariate_       |
		  | statistics       |
		  +--------+---------+
			   |
			   v
		  +--------+---------+
		  | evaluation +     |
		  | portfolio        |
		  +--------+---------+

	quality + docs_refresh validate and document the whole flow
```

`founder.config` owns environment configuration. It loads EODHD settings, request timeouts, retry counts, request spacing, and backoff values without exposing secrets to logs or generated artifacts.

`founder.http` owns EODHD HTTP access. It builds tokenized requests, redacts secrets from errors, spaces requests, retries transient failures, and honors `Retry-After` for rate-limit responses.

`founder.logging` owns uniform module logging. It configures `.logs/founder-YYYY-MM-DD.log`, supports DEBUG verbosity for CLI commands, zips plain logs older than seven days, and deletes zip archives older than one month.

`founder.run_locks` owns per-layer process locks. It serializes Bronze, Silver, and Gold commands per lake root with stable OS locks so standalone commands and fetch-all-quotes runs cannot overlap the same layer.

`founder.__init__` owns the package import surface. It keeps the package importable and exposes the package version without triggering configuration loading, API calls, or lake writes.

`founder.contracts` owns typed cross-module data contracts. It defines validated dataclasses for selection rows, bronze runs, and bronze errors when code needs stronger structure than plain row dictionaries.

`founder.paths` owns lake artifact locations. It keeps Bronze, Silver, and Gold path construction deterministic so modules do not hard-code filesystem layouts.

`founder.schemas` owns dataset contracts. It gives Fetch All ISINs, Metadata Filter, Univariate Statistics, Univariate Filter, Bivariate Statistics, Bronze, Silver, Evaluation, Portfolio, and tests one registry for dataset ownership, schema versions, required fields, and stable sort keys before data moves between layers.

`founder.run_state` owns shared job manifests. It records deterministic job ids, job type, run id, status, input and output paths, row counts, concurrency, resume markers, and redacted error summaries without replacing module-specific compatibility manifests in one step.

`founder.table_io` owns current table serialization. It reads and writes JSON objects, physical Parquet row tables, and review CSVs behind helper functions so storage details stay out of module logic.

`founder.fetch_all_isins` owns full EODHD metadata reference refreshes. It enumerates exchange symbol lists, keeps ISIN-bearing listing metadata, and writes the single reusable all-ISIN source under `lake/reference/all_isins/`.

`founder.metadata_filter` owns metadata-only selections. It reads the all-ISIN reference, applies conjunctive predicates, and writes hash-addressable `isins.parquet` and `manifest.json` selection artifacts. Its public CLI filters are `--where`, `--name-contains`, `--selection-name`, `--root`, and `--debug`; `--where` predicates may use `=`, `!=`, `~`, `>`, `>=`, `<`, and `<=` against the `all_isins` fields `isin`, `exchange`, `code`, `name`, `instrument_type`, `country`, `currency`, `source_exchange`, and `fetched_at`.

`founder.univariate_statistics` owns reusable per-listing statistics from validated quote history.

`founder.univariate_filter` owns metric-based selections. It reads Gold univariate statistics, applies conjunctive predicates, and writes the same selection artifact shape as `metadata_filter`.

`founder.bivariate_statistics` owns pairwise statistics for persisted selections. Pair metrics are computed once per unordered pair, skip duplicate same-ISIN listings by default, and use only the common return-date intersection for each pair.

`founder.bronze` owns data loading for the approved universe. It validates canonical rows, builds EODHD symbols, writes bronze plans, archives quote, dividends, and splits payloads, logs non-secret errors, and writes operational coverage manifests. It is designed for unattended cron execution with bounded EODHD parallelism, default concurrency `2`, shared request pacing, `Retry-After` handling, resumable runs, and no overlapping Bronze writes for the same lake root.

`founder.silver` owns Bronze-to-Silver market data builds. It reads archived quote rows, validates schema and merge keys, and writes one Silver quote file per exchange and ISIN without calling EODHD. Silver writes listing files with bounded parallelism and defaults to two worker threads.

`founder.universe_review` owns pre-optimization universe checks. It summarizes missing ISINs, currency exposure, and survivorship-bias warnings so weak inputs are visible before portfolio weights are trusted.

`founder.gold` owns portfolio-ready risk inputs. It builds daily adjusted-close log returns, incremental Pearson correlations, online sample covariance rows, correlation edge rows, and per-asset feature rows from validated Silver quote history. Gold processes listings with bounded parallelism, defaults to two workers, avoids duplicate symmetric pair calculations, and uses a per-listing Gold run manifest to resume unchanged input snapshots.

`founder.evaluation` owns portfolio analysis datasets that compare candidate portfolios and optimization techniques. It consumes Gold return inputs and writes aligned return matrices, asset metrics, portfolio return series, drawdowns, and portfolio metrics today; later evaluation work extends this boundary with efficient-frontier points, walk-forward backtests, rebalancing simulations, and tail-risk diagnostics without calling EODHD. `founder.evaluation_parts` provides internal package-style boundaries while preserving the public `founder.evaluation` import surface.

`founder.portfolio` owns optimization constraints, target weights, and risk-contribution diagnostics. It validates long-only bounds, minimum and maximum weights, quote-coverage assumptions, and objective settings for constrained minimum variance, risk parity, hierarchical risk parity, maximum diversification, CVaR, and related optimizers. `founder.portfolio_parts` provides internal package-style boundaries while preserving the public `founder.portfolio` import surface. Existing optimizers are deterministic baseline decision-support outputs and include structured diagnostics; they are not execution approval by themselves.

`founder.trading` owns Flatex trade-preparation exports. It converts approved target weights, latest prices, and canonical listing metadata into broker-ready CSV order rows without calling broker APIs or deciding the optimization objective.

`founder.pipeline` owns deterministic dry-run workflows. It should stitch Fetch All ISINs, selection, quote building, coverage, and statistics inputs together with sample data so users can verify the architecture without credentials.

`founder.cli` owns command-line entry points. It parses user commands and routes them to repeatable workflows such as `founder dry-run` without embedding business logic in the CLI layer.

`founder.quality` owns repository validation commands. It runs the local PR and main gates used by GitHub workflows. The required main merge gate covers Ruff lint and format, Pyright strict typing, Pytest, at least 95% coverage, Import Linter contracts, dataset schema-registry validation, working-tree checks, and Conventional Commit validation for branch commits and the final squash subject.

`founder.docs_refresh` owns documentation review reporting. It scans tracked documentation files for review markers and writes `docs/docs_refresh_report.json` so docs-heavy changes can verify that documentation stayed current.

## Current Shape

- **Fetch All ISINs**: EODHD exchange symbol-list enumeration stores one irregularly refreshed all-ISIN metadata reference.
- **Metadata Filter**: Conjunctive metadata predicates turn the all-ISIN reference into persisted selections.
- **Bronze**: Raw EODHD API responses and quote ingestion outputs.
- **Silver**: Normalized ETF quote and instrument datasets with stable identifiers, schema checks, and coverage metadata.
- **Univariate Statistics**: Portfolio-ready one-listing metrics derived from validated Silver quote inputs.
- **Univariate Filter**: Conjunctive metric predicates turn univariate statistics into persisted selections.
- **Bivariate Statistics**: Pairwise covariance and correlation metrics for selected listings, aligned by common return dates.
- **Evaluation**: Return matrices, asset metrics, portfolio return series, drawdowns, and portfolio metrics consume Gold inputs and stay separate from market-data ingestion. Efficient-frontier points, robust optimization diagnostics, walk-forward backtests, rebalancing simulations, and tail-risk analysis build on that boundary.
- **Portfolio**: Constraint validation and target weights consume Gold evaluation inputs and stay separate from market-data ingestion.
- **Trading**: Flatex export helpers turn approved target weights into broker-ready order rows without calling broker APIs.
- **Validation**: Focused tests first, followed by full quality gates for behavior, typing, formatting, architecture boundaries, and at least 95% test coverage before main merges.
- **Operations**: Long-running jobs can write shared deterministic job manifests alongside compatibility module manifests.
- **Configuration**: Secrets and local credentials live in ignored local secret files such as `.secrets/eodhd.yaml`, with `.env.local` available for fallback and local tuning.
- **Logging**: Shared Founder logging writes uniformly formatted `.logs/` files with debug verbosity and retention.
- **Run locks**: Stable layer locks under `lake/{bronze,silver,gold}/runs/*.lock` prevent duplicate same-layer commands on one host.
- **Dry run**: `founder dry-run` should execute the mocked pipeline from Fetch All ISINs through statistics inputs without credentials.
- **Docs refresh**: `founder-docs-refresh` writes a generated documentation review report for tracked repository docs.

## Module Boundary

- **fetch_all_isins module**: owns full EODHD metadata reference refreshes and must not compute statistics or portfolio metrics.
- **metadata_filter module**: owns metadata-only selection predicates and must not call EODHD or compute price-derived metrics.
- **univariate_statistics module**: owns one-listing metrics from Silver quotes and must not perform pairwise analysis.
- **univariate_filter module**: owns metric-only selection predicates and must not call EODHD or recompute statistics.
- **bivariate_statistics module**: owns pairwise statistics for explicit selections and must align every pair on common return dates.
- **Bronze module**: owns bronze planning, EOD quotes, additional EODHD listing datasets, Bronze writes, operational coverage, and bronze error logging.
- **Silver module**: owns Bronze-to-Silver quote builds and analytical Silver quote files.
- **Universe review module**: owns missing-ISIN, currency-exposure, and survivorship-bias review summaries before optimization consumes a universe.
- **Evaluation module**: owns portfolio analytics and comparison datasets derived from Gold returns, correlation, and covariance.
- **Portfolio module**: owns explicit optimization constraints and selected target weights.
- **Trading module**: owns Flatex CSV order preparation from approved target weights and latest prices.
- **Contract**: Downstream work consumes persisted selection artifacts; selection modules must not perform fuzzy discovery, and Fetch All ISINs must not bronze full quote history.

## Simple Lake Layout

- **Bronze**: raw or near-raw EODHD quote, dividends, splits, and mapping payloads.
- **Silver**: normalized candidates, canonical universe, one quote file per exchange and ISIN, and coverage-ready tables.
- **Gold**: portfolio-ready returns, correlation, covariance, evaluation metrics, frontier points, backtests, risk inputs, and portfolio weights.
- **Silver operational datasets**: active universe pointer, bronze plans, bronze runs, coverage, errors, shared job manifests, and dataset version metadata stored under focused Silver directories.

## Portfolio Analysis And Evaluation

Portfolio evaluation should be reproducible from existing statistics and risk inputs and should not require Fetch All ISINs, Bronze, EODHD credentials, or broker access. The planned analysis scope is risk-first because the ETF universe is large, return forecasts are noisy, and many UCITS ETF listings are highly correlated.

The evaluation layer computes aligned return matrices, per-ISIN Sharpe, Sortino, and historical daily-loss CVaR metrics, portfolio return series, cumulative wealth, drawdown series, maximum drawdown, drawdown duration, recovery duration, Calmar ratio, ulcer index, efficient-frontier points, frontier weights, walk-forward backtests, rebalancing simulations, and portfolio tail scenario diagnostics from Gold return files.

The portfolio layer compares equal-weight, constrained minimum variance, maximum Sharpe as a comparison objective, target-return minimum variance, risk parity, hierarchical risk parity, and maximum diversification today. CVaR-aware target weights remain a tail-risk extension after historical CVaR evaluation. Constrained minimum variance and risk parity are the first candidates for trusted production weights; maximum Sharpe remains a comparison result until expected-return assumptions are validated out of sample.

Portfolio target-weight outputs include optimizer diagnostics such as optimizer type, status, objective value, covariance condition, missing covariance count, input listing count, and constraint violations. The current optimizer type is `deterministic_baseline`; future solver-backed optimizers must use the same diagnostics contract before any output can be treated as production execution input.

## Boundaries

- Discovery, bronze planning, checkpointing, bounded parallelism, layer locking, retries, and completeness reporting belong near ingestion code.
- Selection and downstream statistics communicate through explicit versioned contracts, not shared mutable state.
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
