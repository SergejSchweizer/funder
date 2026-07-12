# Architecture

Last reviewed: 2026-07-12

## Purpose

This project analyzes EODHD end-of-day ETF quotes and builds minimum-risk fund portfolio weights. The architecture should keep instrument discovery, quote ingestion, storage contracts, transformation logic, optimization, and validation gates separated so changes can be tested locally and reviewed safely.

## Current Shape

- **Discovery**: EODHD search and exchange symbol-list enumeration identify ETF and fund universes by ticker, name, ISIN, exchange, and type.
- **Bronze**: Raw EODHD API responses and quote ingestion outputs.
- **Silver**: Normalized ETF quote and instrument datasets with stable identifiers, schema checks, and coverage metadata.
- **Gold**: Portfolio-ready return, covariance, risk, and optimized-weight datasets derived from validated Silver inputs.
- **Validation**: Focused tests first, followed by full quality gates for behavior, typing, formatting, architecture boundaries, and at least 95% test coverage before main merges.
- **Configuration**: Secrets and local credentials live in ignored local environment files such as `.env.local`.
- **Dry run**: `founder dry-run` executes the mocked pipeline from Search through Gold inputs without credentials.

## Module Boundary

- **Search module**: owns filtered EODHD discovery, candidate normalization, one-row-per-ISIN canonical selection, XETRA preference, review artifacts, and the active universe pointer.
- **Fetch module**: owns canonical-universe validation, fetch planning, EOD quotes, identifier mapping, fundamentals, lake writes, coverage, and error manifests.
- **Contract**: Fetch consumes only the Search module's approved `canonical_universe.parquet`; Fetch must not perform fuzzy discovery, and Search must not fetch full quote or fundamental history.

## Simple Lake Layout

- **Bronze**: raw or near-raw EODHD search, quote, mapping, and fundamentals payloads.
- **Silver**: normalized candidates, canonical universe, quotes partitioned by year, selected fundamentals, coverage-ready tables.
- **Gold**: portfolio-ready returns, correlation, covariance, risk inputs, and later portfolio weights.
- **Meta**: active universe pointer, fetch runs, coverage, errors, and dataset version metadata.

## Boundaries

- Discovery, fetch planning, checkpointing, retries, and completeness reporting belong near ingestion code.
- Search and Fetch communicate through explicit versioned contracts, not shared mutable state.
- Dataset names, lake paths, contracts, manifests, CLI choices, and tests must move together.
- Transformation code should depend on explicit inputs and contracts, not hidden global state.
- Optimization code should consume validated quote history and explicit constraints, not raw API responses.
- Documentation snapshots must state their review date or be regenerated from source data.
- Table serialization is isolated behind `founder.table_io` so a future Parquet engine can replace the current dependency-free row writer without changing module boundaries.

## Quality Gate Mechanism

Founder uses two named GitHub quality scopes:

- **`pr-quality`** runs on pull requests and non-main branch pushes. It executes `uv run founder-quality pr`, which runs `ruff check .`, `ruff format --check .`, `mypy src tests`, `pytest`, and Conventional Commit validation for branch commits.
- **`main-quality`** runs on pull requests and pushes to `main`. It executes the full `pr-quality` scope and then enforces `pytest --cov=founder --cov-report=term-missing --cov-fail-under=95`.

Branch protection for `main` requires `main-quality`. A same-repository PR with a passing `main-quality` check counts as approved for merge and may be squash-merged automatically by the `auto-merge` workflow. Branch protection still keeps conversation resolution, linear history, disabled force pushes, and disabled branch deletion.

## Update Rules

Update this file whenever a change alters one of these items:

- A layer boundary or dependency direction.
- Dataset ownership, naming, contracts, or lake paths.
- Validation gates, architecture checks, or required release commands.
- Local configuration conventions that affect reproducibility.

Before merging architecture changes, update `RISKS.md`, `DECISIONS.md`, and `BACKLOG.md` when the change creates, resolves, or reprioritizes work.