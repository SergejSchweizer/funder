# Decisions

Last reviewed: 2026-07-12

Record durable technical decisions here. Use short entries with context, decision, consequences, and update triggers.

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

Context: The project goal is to analyze end-of-day quotes for multiple thousands of ETFs and build minimum-risk portfolio weights.

Decision: Use EODHD EOD Historical Data as the first data source for ETF discovery and quote ingestion. Use exchange symbol-list enumeration for broad universe discovery because the Search API is capped at 500 results.

Consequences: Discovery code must handle multiple exchanges, duplicate listings, ETF and fund type filters, and token-free outputs. Quote ingestion must validate coverage before optimization consumes the data. EODHD calls must use the shared client so request pacing, retry backoff, and `Retry-After` handling are applied consistently.

Update trigger: Revisit if another provider becomes primary, EODHD endpoint behavior changes, or the universe definition moves away from ETF/fund instruments.

## D004. Start With Minimum-Risk Portfolio Optimization

Date: 2026-07-12

Context: The first product goal is optimal portfolio weighting based on minimal risk.

Decision: Start with minimum-variance portfolio optimization over validated ETF return histories, then add constraints explicitly as project requirements mature.

Consequences: The implementation needs clean return series, covariance estimation, duplicate instrument handling, and documented constraints before weights are trusted.

Update trigger: Revisit if the objective changes to risk parity, target return, maximum Sharpe ratio, drawdown minimization, or multi-objective optimization.

## D005. Deduplicate ETF Universe By ISIN And Prefer XETRA

Date: 2026-07-12

Context: The `UCITS ETF` discovery set contains duplicate listings across exchanges. Portfolio construction should not overweight the same fund because one ISIN appears on multiple venues.

Decision: Use one canonical listing per non-empty ISIN for quote fetching and optimization. Prefer the `XETRA` listing when the ISIN is available on XETRA; otherwise select a fallback exchange deterministically from the remaining listings.

Consequences: Fetch planning should target `docs/eodhd_ucits_etf_canonical_isins.csv`, not the raw listing discovery file. Rows without ISIN require a separate review before they can enter the optimization universe.

Update trigger: Revisit if the preferred exchange changes, a primary-listing signal becomes available, or optimization needs multiple currency/listing variants of the same ISIN.

## D006. Use EODHD For Data And Flatex For Trading

Date: 2026-07-12

Context: Founder needs a clear separation between market data sourcing and trade execution assumptions.

Decision: Use the EODHD subscription as the main source for EOD Historical Data and Flatex as the intended trading exchange/broker venue for ETF trades.

Consequences: Data ingestion should be designed around EODHD symbols, exchanges, and API limits. Portfolio output should include enough listing, currency, and exchange metadata to support later Flatex trade preparation.

Update trigger: Revisit if the market data subscription changes, Flatex is replaced, or execution constraints require a different canonical listing selection rule.

## D007. Split Discovery And Data Loading Into Search And Fetch Modules

Date: 2026-07-12

Context: The project needs filtered name/ISIN discovery first, then full EODHD data loading for the approved canonical universe.

Decision: Implement two clearly separated modules. Search produces versioned candidate and canonical-universe contracts. Fetch consumes only the approved canonical-universe contract and writes quote, mapping, fundamentals, coverage, and analytics data into the lake.

Consequences: The module boundary must be enforced by schema validation and tests. Search must not fetch full histories, and Fetch must not perform fuzzy discovery. All PRs that alter the contract must update architecture, decisions, risks, and backlog entries together.

Update trigger: Revisit if discovery and fetch are moved behind a shared orchestration framework or if a new provider requires a different contract boundary.

## D008. Use Local And GitHub Quality Gates

Date: 2026-07-12

Status: Superseded by D009.

Context: The project needs repeatable checks before implementing Search, Fetch, and lake-writing behavior.

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

Decision: Use exactly two quality gate layers. The PR gate runs Ruff, Ruff format check, Mypy, Pytest, and Conventional Commit validation locally through `uv run founder-quality pr` and the pre-commit hook. The main gate runs Ruff, Ruff format check, Mypy, Pytest with at least 95% coverage, Conventional Commit validation, and clean tracked working-tree checks through `uv run founder-quality main`. GitHub implements the main merge layer through branch protection: required `quality` workflow status, conversation resolution, linear history, and disabled force pushes/deletions. Passing the full GitHub `quality` workflow is the approval signal for same-repository PRs.

Consequences: PRs should run the local PR gate before push, branch commits must use Conventional Commit subjects, and merges should run the main gate before merging. Main merges fail when test coverage is below 95%. Same-repository PRs can be squash-merged automatically after the required `quality` workflow passes.

Update trigger: Revisit if the workflow name changes, hosted CI is replaced, or the project needs release-only gates.

## D011. Keep Local Lake Serialization Dependency-Free For The Baseline

Date: 2026-07-12

Context: The backlog needs Bronze, Silver, Gold, and Meta contracts immediately, while the current package has no runtime dependencies and no Parquet engine installed.

Decision: Implement deterministic local table helpers in `founder.table_io` and keep storage calls behind path and schema contracts. The current writer emits newline-delimited JSON rows at the table contract paths used by the lake helpers.

Consequences: Search, Fetch, coverage, fundamentals, Gold inputs, and dry runs can be tested locally without new dependencies or credentials. If true Parquet output becomes required, replace `founder.table_io` behind the same contracts and update `docs/lake_contracts.md`.

Update trigger: Revisit before publishing lake artifacts to consumers that require physical Parquet files.

## Update Rules

Add or update a decision when:

- A choice changes data contracts, external APIs, deployment, storage, or quality gates.
- A decision explains why a non-obvious approach was selected.
- A previous decision is replaced or retired.

Do not rewrite old decisions silently. Add a superseding entry and mark the old decision as superseded.