# Architecture

Last reviewed: 2026-07-12

## Table Of Contents

- [Purpose](#purpose)
- [Module Overview](#module-overview)
- [Current Shape](#current-shape)
- [Module Boundary](#module-boundary)
- [Simple Lake Layout](#simple-lake-layout)
- [Boundaries](#boundaries)
- [Validation Boundary](#validation-boundary)
- [Update Rules](#update-rules)

## Purpose

This project analyzes EODHD end-of-day ETF quotes and builds minimum-risk fund portfolio weights. The architecture should keep instrument discovery, quote ingestion, storage contracts, transformation logic, optimization, and validation gates separated so changes can be tested locally and reviewed safely.

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
     +----------->| fetch            |
		  | plan, archive,   |
		  | normalize quotes |
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
		  +--------+---------+      +----------------+
		  | portfolio        |----->| trading        |
		  | constraints and  |      | Flatex export  |
		  | baseline weights |      | preparation    |
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

`founder.contracts` owns typed cross-module data contracts. It defines validated dataclasses for Search candidates, canonical universe rows, fetch runs, and fetch errors when code needs stronger structure than plain row dictionaries.

`founder.paths` owns lake artifact locations. It keeps Bronze, Silver, and Gold path construction deterministic so modules do not hard-code filesystem layouts.

`founder.schemas` owns required table fields. It gives Search, Fetch, coverage, and tests one place to check the shape of table contracts before data moves between layers.

`founder.table_io` owns current table serialization. It reads and writes JSON objects, physical Parquet row tables, and review CSVs behind helper functions so storage details stay out of module logic.

`founder.search` owns discovery normalization and universe approval. It writes raw candidate payloads, normalizes Search rows, selects one canonical listing per non-empty ISIN, exports review artifacts, and writes the active universe pointer for Fetch.

`founder.fetch` owns data loading for the approved universe. It validates canonical rows, builds EODHD symbols, writes fetch plans, archives quote, dividends, and splits payloads, normalizes quote rows, logs non-secret errors, and writes coverage manifests.

`founder.universe_review` owns pre-optimization universe checks. It summarizes missing ISINs, currency exposure, and survivorship-bias warnings so weak inputs are visible before portfolio weights are trusted.

`founder.gold` owns portfolio-ready risk inputs. It builds adjusted-close returns, correlations, and covariance rows from validated Silver quote history.

`founder.portfolio` owns optimization constraints and deterministic baseline weights. It validates long-only bounds, minimum and maximum weights, quote-coverage assumptions, and simple seed allocations before a full optimizer is introduced.

`founder.trading` owns Flatex trade-preparation exports. It converts approved target weights, latest prices, and canonical listing metadata into broker-ready CSV order rows without calling broker APIs or deciding the optimization objective.

`founder.pipeline` owns the deterministic dry-run workflow. It stitches Search, Fetch, Silver normalization, coverage, and Gold inputs together with sample data so users can verify the architecture without credentials.

`founder.cli` owns command-line entry points. It parses user commands and routes them to repeatable workflows such as `founder dry-run` without embedding business logic in the CLI layer.

`founder.quality` owns repository validation commands. It runs the local PR and main gates used by GitHub workflows, including formatting, linting, typing, tests, coverage, working-tree checks, and Conventional Commit validation.

`founder.docs_refresh` owns documentation review reporting. It scans tracked documentation files for review markers and writes `docs/docs_refresh_report.json` so docs-heavy changes can verify that documentation stayed current.

## Current Shape

- **Discovery**: EODHD search and exchange symbol-list enumeration identify ETF and fund universes by ticker, name, ISIN, exchange, and type.
- **Bronze**: Raw EODHD API responses and quote ingestion outputs.
- **Silver**: Normalized ETF quote and instrument datasets with stable identifiers, schema checks, and coverage metadata.
- **Gold**: Portfolio-ready return, covariance, risk, and optimized-weight datasets derived from validated Silver inputs.
- **Portfolio**: Constraint validation and deterministic seed weights consume Gold risk inputs and stay separate from market-data ingestion.
- **Trading**: Flatex export helpers turn approved target weights into broker-ready order rows without calling broker APIs.
- **Validation**: Focused tests first, followed by full quality gates for behavior, typing, formatting, architecture boundaries, and at least 95% test coverage before main merges.
- **Configuration**: Secrets and local credentials live in ignored local environment files such as `.env.local`.
- **Logging**: Shared Founder logging writes uniformly formatted `.logs/` files with debug verbosity and retention.
- **Dry run**: `founder dry-run` executes the mocked pipeline from Search through Gold inputs without credentials.
- **Docs refresh**: `founder-docs-refresh` writes a generated documentation review report for tracked repository docs.

## Module Boundary

- **Search module**: owns filtered EODHD discovery, candidate normalization, one-row-per-ISIN canonical selection, XETRA preference, review artifacts, and the active universe pointer.
- **Fetch module**: owns canonical-universe validation, fetch planning, EOD quotes, additional EODHD listing datasets, lake writes, coverage, and fetch error logging.
- **Universe review module**: owns missing-ISIN, currency-exposure, and survivorship-bias review summaries before optimization consumes a universe.
- **Portfolio module**: owns explicit optimization constraints and deterministic baseline weight validation.
- **Trading module**: owns Flatex CSV order preparation from approved target weights and latest prices.
- **Contract**: Fetch consumes only the Search module's approved `canonical_universe.parquet`; Fetch must not perform fuzzy discovery, and Search must not fetch full quote history.

## Simple Lake Layout

- **Bronze**: raw or near-raw EODHD search, quote, dividends, splits, and mapping payloads.
- **Silver**: normalized candidates, canonical universe, quotes partitioned by year, and coverage-ready tables.
- **Gold**: portfolio-ready returns, correlation, covariance, risk inputs, and later portfolio weights.
- **Silver metadata**: active universe pointer, fetch plans, fetch runs, coverage, errors, and dataset version metadata stored under the Silver layer.

## Boundaries

- Discovery, fetch planning, checkpointing, retries, and completeness reporting belong near ingestion code.
- Search and Fetch communicate through explicit versioned contracts, not shared mutable state.
- Dataset names, lake paths, contracts, manifests, CLI choices, and tests must move together.
- Transformation code should depend on explicit inputs and contracts, not hidden global state.
- Optimization code should consume validated quote history and explicit constraints, not raw API responses.
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