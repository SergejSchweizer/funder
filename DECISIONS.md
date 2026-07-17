# Decisions

Last reviewed: 2026-07-13

## Table Of Contents

- [How To Read Decisions](#how-to-read-decisions)
- [D001. Keep Local Secrets Out of Git](#d001-keep-local-secrets-out-of-git)
- [D002. Track Architecture, Risks, Backlog, and Decisions as First-Class Docs](#d002-track-architecture-risks-backlog-and-decisions-as-first-class-docs)
- [D003. Use EODHD as the First ETF Quote Source](#d003-use-eodhd-as-the-first-etf-quote-source)
- [D004. Start With Risk-First Portfolio Evaluation](#d004-start-with-risk-first-portfolio-evaluation)
- [D005. Deduplicate ETF Universe By ISIN And Prefer XETRA](#d005-deduplicate-etf-universe-by-isin-and-prefer-xetra)
- [D006. Use EODHD For Data And Flatex For Trading](#d006-use-eodhd-for-data-and-flatex-for-trading)
- [D007. Split Discovery And Data Loading Into Search And Bronze Modules](#d007-split-discovery-and-data-loading-into-search-and-bronze-modules)
- [D008. Use Local And GitHub Quality Gates](#d008-use-local-and-github-quality-gates)
- [D009. Keep Quality Gates Local And Out Of `.github`](#d009-keep-quality-gates-local-and-out-of-github)
- [D010. Use Two Quality Gate Layers](#d010-use-two-quality-gate-layers)
- [D011. Write Physical Parquet Lake Tables](#d011-write-physical-parquet-lake-tables)
- [D012. Keep Optimization Constraints And Trade Exports Separate](#d012-keep-optimization-constraints-and-trade-exports-separate)
- [D013. Store Large Correlation Search As Edge Tables](#d013-store-large-correlation-search-as-edge-tables)
- [D014. Use Per-Layer Process Locks](#d014-use-per-layer-process-locks)
- [D015. Use Dataset Contracts And Job Manifests For Refactor Boundaries](#d015-use-dataset-contracts-and-job-manifests-for-refactor-boundaries)
- [Update Rules](#update-rules)

Record durable technical decisions here. Use short entries with context, decision, consequences, and update triggers.

## How To Read Decisions

Read decisions when you need to understand why the project chose a direction. Decisions should not restate operational runbooks or full module guides; they preserve context, consequences, and the trigger that would justify revisiting the choice.

## D001. Keep Local Secrets Out of Git

Date: 2026-07-12

Context: The project needs local API credentials for EODHD EOD historical data.

Decision: Store local credentials in ignored environment files such as `.env.local`. Track only examples or documentation, never real tokens.

Consequences: Any code that needs credentials should read from environment variables or local config loaders. `.gitignore` must continue excluding `.env` and `.env.*` while allowing `.env.example`.

Update trigger: Revisit if the project adopts a dedicated secret manager, encrypted local config, or deployment-specific credential flow.

## D002. Track Architecture, Risks, Backlog, and Decisions as First-Class Docs

Date: 2026-07-12

Context: The workspace needs persistent project memory that survives coding sessions and gives future changes a review checklist.

Decision: Maintain `ARCHITECTURE.md`, `RISKS.md`, `BACKLOG.md`, and `DECISIONS.md` at the repository root and stage them in Git.

Consequences: Changes that affect architecture, risk, planned work, or durable technical direction must update the corresponding document in the same change.

Update trigger: Revisit if these docs move into generated documentation or a different project governance system.

## D003. Use EODHD as the First ETF Quote Source

Date: 2026-07-12

Context: The project goal is to analyze end-of-day quotes for multiple thousands of ETFs and build risk-aware portfolio weights.

Decision: Use EODHD EOD Historical Data as the first data source for ETF discovery and quote ingestion. Use exchange symbol-list enumeration for broad universe discovery because the Search API is capped at 500 results.

Consequences: Discovery code must handle multiple exchanges, duplicate listings, ETF and fund type filters, and token-free outputs. Quote ingestion must validate coverage before optimization consumes the data. EODHD calls must use the shared client so request pacing, retry backoff, and `Retry-After` handling are applied consistently.

Update trigger: Revisit if another provider becomes primary, EODHD endpoint behavior changes, or the universe definition moves away from ETF/fund instruments.

## D004. Start With Risk-First Portfolio Evaluation

Date: 2026-07-12

Context: The first product goal is optimal portfolio weighting based on robust risk analysis. ETF expected-return estimates are noisy, and many UCITS ETF candidates are highly correlated.

Decision: Start with constrained minimum-variance optimization over validated ETF return histories, then evaluate risk parity, hierarchical risk parity, maximum diversification, walk-forward backtesting, rebalancing simulations, drawdown metrics, and CVaR before trusting target weights.

Consequences: The implementation needs clean return series, covariance estimation, duplicate instrument handling, drawdown and tail-risk metrics, out-of-sample checks, transaction-cost-aware rebalancing simulations, and documented constraints before weights are trusted.

Update trigger: Revisit if a return forecast model becomes reliable enough to make maximum Sharpe or target-return optimization a production objective rather than a comparison result.

## D005. Deduplicate ETF Universe By ISIN And Prefer XETRA

Date: 2026-07-12

Context: The `UCITS ETF` discovery set contains duplicate listings across exchanges. Portfolio construction should not overweight the same fund because one ISIN appears on multiple venues.

Decision: Use one canonical listing per non-empty ISIN for quote loading and optimization. Prefer the `XETRA` listing when the ISIN is available on XETRA; otherwise select a fallback exchange deterministically from the remaining listings.

Consequences: Bronze planning should target `docs/eodhd_ucits_etf_canonical_isins.csv`, not the raw listing discovery file. Rows without ISIN require a separate review before they can enter the optimization universe.

Update trigger: Revisit if the preferred exchange changes, a primary-listing signal becomes available, or optimization needs multiple currency/listing variants of the same ISIN.

## D006. Use EODHD For Data And Flatex For Trading

Date: 2026-07-12

Context: Founder needs a clear separation between market data sourcing and trade execution assumptions.

Decision: Use the EODHD subscription as the main source for EOD Historical Data and Flatex as the intended trading exchange/broker venue for ETF trades.

Consequences: Data ingestion should be designed around EODHD symbols, exchanges, and API limits. Portfolio output should include enough listing, currency, and exchange metadata to support later Flatex trade preparation.

Update trigger: Revisit if the market data subscription changes, Flatex is replaced, or execution constraints require a different canonical listing selection rule.

## D007. Split Discovery And Data Loading Into Search And Bronze Modules

Date: 2026-07-12

Context: The project needs filtered name/ISIN discovery first, then full EODHD data loading for the approved canonical universe.

Decision: Implement two clearly separated modules. Search produces versioned candidate and canonical-universe contracts. Bronze consumes only the approved canonical-universe contract and writes quote, mapping, coverage, and analytics data into the lake.

Consequences: The module boundary must be enforced by schema validation and tests. Search must not bronze full histories, and Bronze must not perform fuzzy discovery. All PRs that alter the contract must update architecture, decisions, risks, and backlog entries together.

Update trigger: Revisit if discovery and bronze are moved behind a shared orchestration framework or if a new provider requires a different contract boundary.

## D008. Use Local And GitHub Quality Gates

Date: 2026-07-12

Status: Superseded by D009.

Context: The project needs repeatable checks before implementing Search, Bronze, and lake-writing behavior.

Decision: Use Ruff, Mypy, Pytest, pre-commit, and a GitHub Actions `quality` workflow as the baseline quality gate. Protect `main` with the same workflow once the baseline is merged.

Consequences: Development changes should pass the local pre-commit hooks before push, and repository changes should keep workflow, README commands, and backlog status aligned.

Update trigger: Revisit if the project adopts additional checks such as coverage thresholds, security scanning, import-linter, or architecture rules.

## D009. Keep Quality Gates Local And Out Of `.github`

Date: 2026-07-12

Status: Superseded by D010.

Context: The repository should not track a `.github` workflow directory, while local checks still need to remain repeatable.

Decision: Keep Ruff, Mypy, Pytest, and pre-commit as the baseline local quality gate, but do not track GitHub Actions workflow files under `.github`.

Consequences: Branch protection must not require a GitHub Actions `quality` status check unless a workflow is reintroduced. Contributors should run `uv run pre-commit run --all-files` locally before opening or merging changes.

Update trigger: Revisit if repository-hosted CI is reintroduced or another external quality gate replaces local-only checks.

## D010. Use Two Quality Gate Layers

Date: 2026-07-12

Context: The project needs a simple quality policy that works locally and with GitHub branch protection while `.github/` remains untracked.

Decision: Use exactly two quality gate layers. The PR gate runs Ruff, Ruff format check, Mypy, Pytest, and Conventional Commit validation locally through `uv run founder-quality pr` and the pre-commit hook. The main gate runs Ruff, Ruff format check, Mypy, Pytest with at least 95% coverage, Conventional Commit validation, and clean tracked working-tree checks through `uv run founder-quality main`. GitHub mirrors these as `pr-quality` and `main-quality`. Branch protection requires the `main-quality` workflow status, conversation resolution, linear history, and disabled force pushes/deletions. Passing `main-quality` is the approval signal for same-repository PRs.

Consequences: PRs should run the local PR gate before push, branch commits must use Conventional Commit subjects, and merges should run the main gate before merging. Main merges fail when test coverage is below 95%. Same-repository PRs can be squash-merged automatically after the required `main-quality` workflow passes.

Update trigger: Revisit if the workflow name changes, hosted CI is replaced, or the project needs release-only gates.

## D011. Write Physical Parquet Lake Tables

Date: 2026-07-12

Context: The lake artifacts use `.parquet` table contracts and should open in standard Parquet readers.

Decision: Implement deterministic local table helpers in `founder.table_io` and keep storage calls behind path and schema contracts. `.parquet` paths are written as physical Apache Parquet files through pyarrow; `.json` and review CSV artifacts keep their native formats.

Consequences: Search, Bronze, coverage, Gold inputs, and dry runs produce lake tables that open in standard Parquet tooling while module code still depends only on `founder.table_io`.

Update trigger: Revisit if the project changes Parquet engine, compression, partitioning, or schema evolution policy.

## D012. Keep Optimization Constraints And Trade Exports Separate

Date: 2026-07-12

Context: The project is moving from validated Gold risk inputs toward portfolio weights and broker-specific trade preparation.

Decision: Keep portfolio constraint validation in `founder.portfolio`, universe review checks in `founder.universe_review`, and Flatex export shaping in `founder.trading`. Trade export helpers consume approved target weights, listing metadata, and prices; they do not compute the optimization objective or call broker APIs.

Consequences: Optimization logic can evolve independently from Flatex formatting. Missing-ISIN, currency, and survivorship-bias review summaries stay visible before weights are trusted or exported.

Update trigger: Revisit if a real optimizer, broker API integration, or multi-broker export format is added.

## D013. Store Large Correlation Search As Edge Tables

Date: 2026-07-13

Context: Correlation analysis may need to cover up to 150,000 ISINs. A dense matrix is expensive to query and hard to filter, while most product workflows need pair search, thresholds, top-k related instruments, and common-observation metadata.

Decision: Keep the existing per-ISIN Gold correlation and covariance baseline for small inputs, and add `gold/correlation_edges` as the scalable pair-search contract. Correlation edge rows store only upper-triangle pairs with deterministic listing ids, metric/version fields, common date range, common observation count, and bucketed Parquet output.

Consequences: Large-universe work should query `correlation_edges` instead of treating dense matrices as the primary persisted artifact. Future DuckDB, Polars, or sparse-array work should preserve the edge schema or document an explicit migration.

Update trigger: Revisit if the project adopts a different primary matrix store, changes bucket strategy, or requires exact random-access dense matrix slices as the main workload.

## D014. Use Per-Layer Process Locks

Date: 2026-07-13

Context: Bronze, Silver, and Gold can be run either as standalone CLI commands or through `founder fetch-all-quotes`. A global cron `flock` prevents one scheduled quote-fetch overlap, but it does not protect manual standalone layer commands from colliding with a quote fetch or with another same-layer command.

Decision: Use stable OS-backed locks per lake layer: `lake/bronze/runs/bronze.lock`, `lake/silver/runs/silver.lock`, and `lake/gold/runs/gold.lock`. Each layer command exits with a clear active-run error when the same layer is already running for the lake root.

Consequences: Different layers may still run at the same time when explicitly started, but duplicate Bronze, duplicate Silver, and duplicate Gold writes are blocked. The lock files may remain as metadata after a process exits, but the OS lock is released when the process terminates, avoiding stale file-existence locks.

Update trigger: Revisit if Founder moves to a distributed scheduler, multiple hosts write the same lake root, or the project needs whole quote-fetch serialization instead of same-layer serialization.

## D015. Use Dataset Contracts And Job Manifests For Refactor Boundaries

Date: 2026-07-13

Context: The codebase is moving from broad module files toward smaller refactor boundaries while keeping existing lake names, CLI behavior, and compatibility manifests stable.

Decision: Keep dataset ownership, schema versions, required fields, and stable sort keys in a central dataset contract registry. Use shared job manifests for long-running operational runs while preserving existing module-specific manifests during migration. Keep deterministic baseline portfolio optimizers behind a diagnostics contract that distinguishes decision-support outputs from future production solver outputs.

Consequences: Refactors should route new validation through the registry, write shared job manifests for new long-running jobs, and include optimizer diagnostics whenever target weights are written. Existing path strings, lake table names, public imports, and CLI behavior should remain compatible unless a later decision records an explicit migration.

Update trigger: Revisit if dataset schema versions need migrations, job manifests move to a database-backed scheduler, or production solver-backed optimizers replace deterministic baseline objectives.

## Update Rules

Add or update a decision when:

- A choice changes data contracts, external APIs, deployment, storage, or quality gates.
- A decision explains why a non-obvious approach was selected.
- A previous decision is replaced or retired.

Do not rewrite old decisions silently. Add a superseding entry and mark the old decision as superseded.
