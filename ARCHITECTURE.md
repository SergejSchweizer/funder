# Architecture

Last reviewed: 2026-07-19

## Table Of Contents

- [Purpose](#purpose)
- [Module Overview](#module-overview)
- [Current Shape](#current-shape)
- [Module Boundary](#module-boundary)
- [Simple Lake Layout](#simple-lake-layout)
- [Portfolio Analysis And Evaluation](#portfolio-analysis-and-evaluation)
- [Hosted Multi-Tenant Architecture](#hosted-multi-tenant-architecture)
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

`founder.statistics_views` owns Selection Statistics Views (PR74): read-only materialization of which cached univariate/bivariate Gold rows belong to a Metadata Filter or Univariate Filter selection. It never recomputes a missing row -- it reports `missing_univariate_listings`/`missing_bivariate_pairs` deterministically and lets the caller decide whether to run `write_univariate_statistics`/`write_bivariate_statistics`. `read_selection_statistics` loads a selection's cached rows without recomputing, raising when the cache is incomplete rather than returning a partial result.

`founder.multivariate_statistics` owns portfolio-level analytics for a selected ISIN membership (PR69). It defaults to the latest ready `univariate_filter` selection, filters Silver quotes to that selection, and writes selected Gold/Evaluation/Portfolio artifacts. `write_multivariate_statistics` runs the deterministic baseline objectives (Equal Weight, grid-based Minimum Variance/Maximum Sharpe/Risk Parity, HRP baseline, Maximum Diversification, efficient frontier, walk-forward backtest, rebalancing, tail risk). It defaults to all visible CPU cores for selected Gold input generation, and cache mode passes the same worker count to univariate and bivariate cache refreshes; `--concurrency` caps worker processes when needed. With `use_selection_statistics_cache=True` (CLI `--use-selection-statistics-cache`, PR75), it first consumes PR74 Selection Statistics Views and PR73 generic Gold caches, fills only missing/stale selected listing and pair deltas, reconstructs selected covariance/correlation inputs from cached rows, and reuses an unchanged portfolio run when its deterministic `portfolio_run_id` manifest and artifacts are complete. `write_production_multivariate_statistics` (PR70) is an additive production-mode entry point that refuses -- rather than silently falling back to a baseline -- when the selection's quote history fails `founder.return_quality.evaluate_quote_quality`'s production data-quality gate, the aligned return matrix is empty, `founder.risk_model.estimate_risk_model`'s diagnostics are not production eligible, a requested `founder.profiles` candidate is infeasible, or a candidate is missing its baseline comparison; on success it writes weight rows for every requested profile via `founder.profiles.write_profile_candidate` with a deterministic `production_adapter_id`. `write_multivariate_recommendation` (PR71) runs the production adapter, then adds `founder.scorecard` walk-forward traceability where a profile's objective is scorecard-compatible (Growth only today) and `founder.stress` sensitivity summaries for every candidate, before comparing all candidates via `founder.recommendation` into one deterministic report; income quality, sustainable income, NAV erosion, and income efficiency always report `unavailable` pending PR62E. `write_multivariate_trading_handoff` (PR72) rejects trade preparation by default unless an explicit `approved_comparison_slot` resolves to an included recommendation candidate, then optionally includes a current-versus-target transition plan, a deterministic `founder.trading` Flatex export, and drift/risk/stale-data monitoring statuses (distribution-cut/NAV-erosion always `unavailable` pending PR62E); it never decides broker execution or alters current positions.

`founder.bronze` owns data loading for the approved universe. It validates canonical rows, builds EODHD symbols, writes bronze plans, archives quote, dividends, and splits payloads, logs non-secret errors, and writes operational coverage manifests. It is designed for unattended cron execution with bounded EODHD parallelism, default concurrency `2`, shared request pacing, `Retry-After` handling, resumable runs, and no overlapping Bronze writes for the same lake root.

`founder.silver` owns Bronze-to-Silver market data builds. It reads archived quote rows, validates schema and merge keys, and writes one Silver quote file per exchange and ISIN without calling EODHD. Silver writes listing files with bounded parallelism and defaults to two worker threads.

`founder.universe_review` owns pre-optimization universe checks. It summarizes missing ISINs, currency exposure, and survivorship-bias warnings so weak inputs are visible before portfolio weights are trusted.

`founder.gold` owns portfolio-ready risk inputs. It builds daily adjusted-close log returns and simple returns, incremental Pearson correlations, online sample covariance rows, correlation edge rows, and per-asset feature rows from validated Silver quote history. Gold processes listings with worker processes across all CPU cores visible to the system by default, avoids duplicate symmetric pair calculations, accepts explicit concurrency caps, and uses a per-listing Gold run manifest to resume unchanged input snapshots. `founder.return_quality` is the shared price-quality gate that Gold and Univariate Statistics both use: it quarantines non-positive or duplicate-date prices instead of fabricating a zero return, flags stale-price runs and unexplained calendar gaps, and defines the 252/504/756 observation-day minimum-history thresholds used for production-eligibility labeling.

`founder.evaluation` owns portfolio analysis datasets that compare candidate portfolios and optimization techniques. It consumes Gold return inputs and writes aligned return matrices, asset metrics, portfolio return series, drawdowns, and portfolio metrics today; later evaluation work extends this boundary with efficient-frontier points, walk-forward backtests, rebalancing simulations, and tail-risk diagnostics without calling EODHD. `founder.evaluation_parts` provides internal package-style boundaries while preserving the public `founder.evaluation` import surface. Portfolio wealth simulation compounds each asset's simple return, while Sharpe, Sortino, and other statistical metrics continue to use log returns; asset metrics expose explicit `meets_min_history_252/504/756` and `production_eligible` fields instead of silently treating short histories as production-ready.

`founder.portfolio` owns optimization constraints, target weights, and risk-contribution diagnostics. It validates long-only bounds, minimum and maximum weights, quote-coverage assumptions, and objective settings for constrained minimum variance, risk parity, hierarchical risk parity, maximum diversification, CVaR, and related optimizers. `founder.portfolio_parts` provides internal package-style boundaries while preserving the public `founder.portfolio` import surface. Existing optimizers are deterministic baseline decision-support outputs and include structured diagnostics; they are not execution approval by themselves.

`founder.tax`, `founder.costs`, and `founder.cashflow` own jurisdiction-neutral after-tax, after-cost economics (PR62A; see [CONTRACTS.md](CONTRACTS.md) and `docs/backlog/eu-tax-cost-architecture.md`). `founder.tax` defines immutable tax contracts (`InvestorTaxProfile`, `TaxRuleSetRef`, `TaxEvent`, `TaxCalculationResult`), a `CountryTaxAdapter` protocol, a `CountryTaxRegistry` keyed by ISO country code with every EU member state registered as an explicit `unsupported` placeholder, and a `CostBasisStrategy` protocol for jurisdiction-specific disposal accounting. `founder.costs` defines composable broker/venue/execution/FX/jurisdiction-tax/recurring cost-component contracts and a `CostProfileRegistry`. `founder.cashflow` defines the neutral `CashFlowResult` contract that a future orchestration layer will populate from tax and cost results. None of these modules hard-code a concrete country's tax rate, allowance, or broker fee; every result carries an explicit `exact`/`verified_estimate`/`user_supplied_estimate`/`unavailable`/`unsupported` status (`founder.calculation_status`) so a missing or unverified rule is never silently treated as zero. Country-specific adapters (Austria and beyond) and real cost profiles are follow-up work (PR62B onward) gated on verified, source-attributed rule data.

`founder.profiles` owns versioned Defensive/Balanced/Income/Growth portfolio profile contracts and ensemble candidate construction (PR63). It composes already-merged production optimizers -- True HRP, Equal Risk Contribution, and a new shrinkage Minimum Variance that wires `founder.risk_model`'s Ledoit-Wolf estimator through PR60's solver -- into the initial Balanced ensemble via per-asset median aggregation, normalization, and a final capped-simplex projection. Profile candidates report Equal Weight and Inverse Volatility baseline comparisons, constraint violations, and a deterministic candidate id, and never raise for expected fail-closed conditions (insufficient history, solver non-convergence); they report an explicit `infeasible` status with reasons instead. The Income profile's net-income and NAV-erosion risk limits always report `unavailable` because they require the after-tax cash-flow stack (PR62E), never an invented income figure; group and issuer concentration limits are out of scope until group/issuer metadata is plumbed through the lake.

`founder.scorecard` owns the walk-forward model comparison scorecard (PR64). It runs `founder.evaluation.build_walk_forward_backtest` for multiple candidate objectives on identical pinned windows, rebalance policy, and costs, then reports one deterministically ranked row per candidate: median and adverse-quantile out-of-sample return, median Sharpe/Sortino, historical CVaR, whole-period max drawdown and recovery duration, concentration, and weight stability. Ranking uses median out-of-sample Sharpe across completed splits -- never a single split's or an in-sample return -- with a candidate-id tie-break, and a candidate whose request is infeasible is reported `status="blocked"` rather than crashing the whole comparison. Income quality always reports `unavailable` pending PR62E.

`founder.stress` owns stress, bootstrap, and sensitivity analysis for an already-computed candidate portfolio (PR65). It reuses `founder.evaluation.build_portfolio_returns`/`build_drawdowns` and `founder.portfolio_parts.cvar.historical_var_and_cvar` for return-series-based scenarios (historical stress replay, distribution cuts, seeded block bootstrap) rather than a new simulation engine. Covariance-only scenarios (correlation convergence, covariance perturbation) have no return series to replay, so they report a hand-implemented parametric Gaussian VaR/CVaR from the stressed portfolio volatility instead. The "historical stress period" is always the worst-drawdown window of a requested length detected deterministically within the caller's own data -- never a hardcoded or asserted crash date. `build_sensitivity_summary` aggregates median/worst-case metrics across scenario results for one candidate.

`founder.recommendation` owns the explainable recommendation report (PR66). It compares already-computed `founder.profiles` candidates -- with optional `founder.scorecard`/`founder.stress` traceability and an optional current-position snapshot -- into best-Defensive/best-Diversified/best-Income/best-Total-Return/best-Ensemble slots, propagating (never inventing) exclusion reasons, constraint violations, and data-quality warnings supplied by the caller. Every report carries a fixed no-guaranteed-return disclaimer and `requires_user_approval=True`; income and broker-cost quality always report `unavailable` pending PR62E/PR62D. `render_recommendation_markdown` produces deterministic, HTML-escaped Markdown output.

`founder.trading` owns Flatex trade-preparation exports. It converts approved target weights, latest prices, and canonical listing metadata into broker-ready CSV order rows without calling broker APIs or deciding the optimization objective.

`founder.pipeline` owns deterministic dry-run workflows. It should stitch Fetch All ISINs, selection, quote building, coverage, and statistics inputs together with sample data so users can verify the architecture without credentials.

`founder.cli` owns command-line entry points. It parses user commands and routes them to repeatable workflows such as `founder dry-run` without embedding business logic in the CLI layer.

`founder.quality` owns repository validation commands. It runs the local PR and main gates used by GitHub workflows. The required main merge gate covers Ruff lint and format, Pyright strict typing, Pytest, at least 95% coverage, Import Linter contracts, dataset schema-registry validation, working-tree checks, and Conventional Commit validation for branch commits and the final squash subject.

`founder.docs_refresh` owns documentation review reporting. It scans tracked documentation files for review markers and writes `docs/docs_refresh_report.json` so docs-heavy changes can verify that documentation stayed current.

`founder.hosted_catalog` owns the PR85 hosted PostgreSQL catalog contract. It defines the user/project/credential/grant/snapshot/analysis/artifact/audit schema, role boundaries, Row-Level Security policies, transaction-local authenticated user setting, and deterministic migration plan. It exposes a minimal connection protocol so migrations can be tested without binding the analytical core to a specific PostgreSQL driver.

`founder.hosted_auth` owns the PR86 Google-only authentication boundary. It builds OIDC authorization requests with
PKCE, state, and nonce; consumes an injected token exchanger and ID-token verifier; maps Google's stable `sub` claim to
one internal hosted user; and issues opaque server-side sessions with CSRF validation, expiry, rotation, and
revocation. It stores no Google tokens or provider secrets after session establishment.

`founder.hosted_credentials` owns the PR87 encrypted EODHD credential vault boundary. It encrypts one active credential
per user with a random data-encryption key, wraps that key with an externally supplied versioned KEK, binds ciphertext
to credential id, user id, provider, and schema version as authenticated associated data, returns only masked status
metadata, and fails closed when tampering, wrong user context, unavailable KEK versions, revoked/deleted state, or
authentication failure is detected.

`founder.shared_observations` owns the PR88 shared content-addressed market observation store boundary. It normalizes
provider observations, rejects user/credential/session fields in shared payloads, derives stable observation ids from
provider, dataset type, listing identity, business key, payload hash, and schema version, publishes immutable Parquet
segments through temporary files and atomic rename, and records segment manifests without granting user access.

`founder.entitlements` owns the PR89 user data entitlement and immutable snapshot boundary. It publishes user grants
only from successful provider-backed download runs, resolves user-owned snapshots, keeps new users empty, prevents
shared-object existence from creating access, and deletes user grants/snapshot pointers without deleting shared
physical observations still referenced by other users.

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

## Hosted Multi-Tenant Architecture

Founder's hosted architecture is PostgreSQL-first and user-key-backed. Google is the only end-user authentication
provider, PostgreSQL is the primary application catalog, EODHD credentials are envelope-encrypted with an external
key-encryption key, and shared market observations or derived artifacts never grant access by their physical existence.

The complete hosted trust-boundary baseline, threat model, data classification, prohibited designs, User Data Snapshot
semantics, artifact reuse semantics, and PR84-PR100 backlog mapping live in
[docs/hosted_security_architecture.md](docs/hosted_security_architecture.md).

The first hosted implementation boundary is the PostgreSQL application catalog. It creates separate owner, migrator,
application, and read-only roles; gives the application role no table ownership and no RLS bypass; stores encrypted
credential material only as ciphertext, nonces, wrapped data keys, key versions, associated data, HMAC fingerprints,
and masked labels; and records shared market/artifact identities without putting large analytical tables in
PostgreSQL.

The second hosted implementation boundary is Google-only authentication. OIDC callback handling must validate state,
nonce, issuer, audience, expiry, and verified email before it creates or updates a user. The Google email may change
without changing the internal user because the stable Google `sub` claim is the identity key. Browser-visible sessions
are opaque cookies backed by server-side state; CSRF, expiry, revocation, and rotation are enforced by the server.

The third hosted implementation boundary is the encrypted EODHD credential vault. Plaintext provider keys exist only
during set, validation, unwrap-for-provider-call, and key rotation operations. Stored rows contain ciphertext, nonce,
wrapped data key, wrap nonce, KEK version, associated data, keyed fingerprint, and masked label; database dumps and
shared storage do not contain plaintext or independently reusable credential material.

The fourth hosted implementation boundary is the shared market observation store. Identical normalized observations
deduplicate physically; appended date ranges and corrected historical payloads create distinct content-addressed
segments and object identities. Shared object presence is never authorization evidence, and segment payloads must not
contain user ids, credential ids, session tokens, or credential fingerprints.

The fifth hosted implementation boundary is user data entitlement. A grant can be created only from a successful
current-user provider run, and every hosted analysis must use an immutable User Data Snapshot rather than object
existence, date range, listing identity, content hash, or another user's run. Replaying the same successful response for
one user returns the same logical snapshot without duplicating grants.

Hosted analytical workflows must consume resolved scoped inputs. They must not scan unrestricted global Silver or Gold
paths, global current-selection pointers, or local lake directories. Local CLI mode remains supported through explicit
local adapters that are not authorization evidence for hosted users.

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
