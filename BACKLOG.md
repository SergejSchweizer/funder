# Backlog

Last reviewed: 2026-07-18

## Table Of Contents

- [How To Use This Backlog](#how-to-use-this-backlog)
- [Search And Bronze Module PR Stack](#search-and-bronze-module-pr-stack)
- [Bronze Process Refactor PR Queue](#bronze-process-refactor-pr-queue)
- [Portfolio Evaluation And Optimization PR Stack](#portfolio-evaluation-and-optimization-pr-stack)
- [Architecture Refactor PR Stack](#architecture-refactor-pr-stack)
- [Refactor Hardening PR Stack](#refactor-hardening-pr-stack)
- [Refresh, Selection, And Update Module PR Stack](#refresh-selection-and-update-module-pr-stack)
- [Production Portfolio Product PR Stack](#production-portfolio-product-pr-stack)
- [Multivariate Statistics Module PR Stack](#multivariate-statistics-module-pr-stack)
- [Generic Statistics Cache PR Stack](#generic-statistics-cache-pr-stack)
- [Hosted Product And Goal Traceability PR Stack](#hosted-product-and-goal-traceability-pr-stack)
- [Future Work After Finalization](#future-work-after-finalization)
- [Update Rules](#update-rules)

This backlog captures known work that should stay visible across sessions. Keep entries short, actionable, and tied to risks or decisions where possible.

Every non-merged PR-sized backlog item must include `Branch`, `Git status`, and `PR`. Use a branch path such as `feat/selection-cli`, `Git status: not started`, and `PR: TBD` until work begins. Historical merged entries do not require branch-path backfills.

## How To Use This Backlog

Read this after the architecture and workflow docs when you need implementation status. This file should not explain module behavior in depth; it records scope, dependencies, acceptance criteria, idempotency expectations, branch paths, Git status, and PR links for trackable work.

Use `<type>/<scope>-<short-description>` branch paths with one of `feat`, `fix`, `refactor`, `docs`, or `chore`. Every open PR series must end with a `Series Completion Gate` that names its final branch, requires a Conventional Commit squash subject, and lists the mandatory `merge-gate` checks.

## Search And Bronze Module PR Stack

### PR01. Project Package And Quality Baseline

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/1.

Depends on: initial documentation baseline.

Scope: Add `pyproject.toml`, source package skeleton, test skeleton, CLI entry point placeholders, dependency groups, Ruff configuration, pytest configuration, and README developer commands.

Acceptance: `python -m pytest`, `ruff check`, and the package import smoke test run locally; no EODHD token is read or required.

Idempotency: Re-running commands should not create or modify data files.

### PR02. Shared Configuration, HTTP, And Contract Primitives

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR01.

Scope: Add shared config loading from environment, an EODHD HTTP client with timeout/retry/rate-limit handling, typed contract models for search candidates, canonical universe rows, bronze runs, errors, and lake paths.

Acceptance: Unit tests cover missing token handling, URL construction without token logging, contract validation, and deterministic lake path construction.

Idempotency: Repeated client calls with the same mocked responses produce the same contract objects and never print secrets.

### PR03. Simple Bronze/Silver/Gold Lake Layout Contract

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR02.

Scope: Define the simple medallion lake layout: `lake/bronze`, `lake/silver`, and `lake/gold`; add schema docs for search outputs, canonical universe, quotes, coverage, and bronze manifests; update `.gitignore` so local lake data and DuckDB cache files stay out of Git.

Acceptance: Tests verify all lake paths and schemas; docs describe which module writes or reads each table.

Idempotency: Path/schema helpers are pure and deterministic.

### PR04. Search Module: EODHD Query And Raw Candidate Capture

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR03.

Scope: Implement `founder search` to call EODHD search and exchange-symbol endpoints for configured name filters such as `UCITS ETF`; write raw/near-raw search responses under `lake/bronze/eodhd/search/run_date=YYYY-MM-DD/`; normalize candidate rows into `lake/silver/search/search_run_id=.../candidates.parquet`.

Acceptance: Integration-safe tests use recorded or mocked EODHD responses; output includes names, ISINs, code, exchange, type, country, currency, source endpoint, and run id.

Idempotency: Re-running the same search run id overwrites or validates the same output atomically without duplicate rows.

### PR05. Search Module: Canonical ISIN Selection Contract

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR04.

Scope: Implement one-row-per-ISIN canonical selection from candidates, prefer `XETRA`, then deterministic fallback exchange ordering; exclude missing-ISIN rows from bronze input; write `canonical_universe.parquet` and `search_summary.json`.

Acceptance: Tests prove no duplicate ISINs, XETRA is always selected when available, fallback selection is stable, and missing ISIN rows are reported but not selected for bronze.

Idempotency: Same candidate input always produces byte-for-byte equivalent canonical content apart from allowed metadata timestamps.

### PR06. Search Module: Review Artifacts And Active Universe Pointer

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR05.

Scope: Add human-readable CSV export for review, update `lake/silver/universe/current_universe.json` to point at an approved canonical universe, and document the approval workflow.

Acceptance: Bronze can resolve the active universe path from metadata; docs explain how to approve a new search result without editing code.

Idempotency: Re-approving the same search run leaves the active pointer unchanged.

### PR07. Bronze Module: Input Contract Validation And Planning

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR06.

Scope: Implement `founder bronze plan` to read `canonical_universe.parquet`, validate required fields, reject duplicate or empty ISINs, derive EODHD symbols, and produce a bronze plan with per-listing start/end dates.

Acceptance: Tests cover valid canonical input, duplicate ISIN rejection, empty code/exchange rejection, and gap-aware date planning.

Idempotency: Planning reads existing metadata and produces stable plans without calling EODHD or writing quote data.

### PR08. Bronze Module: EOD Quote Download To Bronze

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR07.

Scope: Implement quote loading for planned canonical listings; write raw EOD quote responses under `lake/bronze/quotes/{exchange}/{year}/{ISIN}.parquet`; capture per-symbol successes, failures, retry status, and API call metadata.

Acceptance: Tests use mocked EODHD responses; failures are recorded without stopping the whole batch unless configured; token never appears in logs or files.

Idempotency: Re-running the same run id does not duplicate quote records and can resume failed symbols.

### PR09. Silver Quote Build Baseline

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR08.

Scope: Build Silver quote responses from Bronze quote rows into `lake/silver/quotes/{exchange}/{ISIN}.parquet` with columns for ISIN, code, exchange, date, OHLC, adjusted close, volume, currency, run id, and bronzed time.

Acceptance: Tests verify schema, date parsing, numeric types, duplicate prevention by `(isin, exchange, code, date)`, and per-ISIN Silver quote files.

Idempotency: Re-running the same Silver quote build for a Bronze run is safe and produces no duplicate Silver quote rows.

### PR10. Bronze Module: Identifier Mapping Capture

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR09.

Scope: Bronze ID mapping for canonical listings; archive complete raw payloads under Bronze; extract minimal Silver identifier tables needed for filtering/reporting.

Acceptance: Tests cover missing mappings, nested payload preservation, selected field extraction, and schema stability.

Idempotency: Re-loading the same run id records one latest payload per listing/run and preserves prior runs.

### PR11. Bronze Module: Coverage, Errors, And Monthly Refresh Behavior

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR10.

Scope: Add `lake/silver/runs/bronze_runs.parquet` and `lake/silver/coverage/coverage.parquet`; compute first/last quote dates, observed rows, missing periods, failed symbols, and next gap-aware bronze start with a small overlap window. Bronze failures are written to log files instead of lake Parquet tables.

Acceptance: Tests cover first full bronze, gap-aware refresh loads, overlap deduplication, partial failures, and coverage report generation.

Idempotency: A failed run can be resumed; successful reruns update manifests without duplicating quotes.

### PR12. Gold Inputs: Returns, Correlation, And Covariance Baseline

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR11.

Scope: Build initial `lake/gold/returns/{exchange}/{ISIN}.parquet`, `lake/gold/correlation/{exchange}/{ISIN}.parquet`, and `lake/gold/covariance/{exchange}/{ISIN}.parquet` outputs from Silver adjusted-close quotes for the active canonical universe.

Acceptance: Tests cover adjusted-close return calculation, date alignment, missing-data thresholds, correlation/covariance output schemas, and deterministic results for sample data.

Idempotency: Rebuilding Gold inputs replaces or validates the same per-ISIN outputs without accumulating stale files.

### PR13. Finalization: End-To-End Dry Run, Docs, And Release Checklist

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/3.

Depends on: PR12.

Scope: Add an end-to-end dry-run command that executes search, canonical selection, bronze planning, mocked bronze, Silver quote building, coverage reporting, and Gold input generation; update README, ARCHITECTURE, RISKS, DECISIONS, and BACKLOG with final commands and known limitations.

Acceptance: One command validates the full mocked pipeline from search contract to Gold risk inputs; all repository tracking docs are current; backlog statuses and PR links are filled for completed stack items.

Idempotency: The final dry run is safe to execute repeatedly in a clean workspace and produces deterministic sample outputs.

## Bronze Process Refactor PR Queue

### PR14. Bronze Process: Cron-Safe Bronze Ingestion And Medallion Builds

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/13.

Depends on: PR13.

Scope: Refactor the full bronze process as one coherent change. Make `founder.bronze` responsible for EODHD ingestion to Bronze plus Silver operational bronze-plan, bronze-run, coverage, and gap metadata only; add bounded parallel EODHD loading with default concurrency `2`; preserve shared request pacing and `Retry-After` handling; make Bronze safe for cron execution with stable run ids, resumable runs, and no overlapping writes; remove direct analytical Silver quote and Gold risk-output writes from bronze-owned code paths; add `founder.silver` for Bronze-to-Silver quote builds; add `founder gold` for Silver-to-Gold returns, correlation, and covariance builds; and add a convenience orchestration command such as `founder refresh` for running Bronze, Silver, and Gold in order.

Acceptance: Tests prove `founder bronze` writes Bronze and Silver operational datasets, does not write `lake/silver/quotes`, does not write `lake/gold`, preserves gap-aware planning, honors default concurrency `2`, accepts an explicit concurrency override, keeps token-safe retry/rate-limit behavior, prevents or reports overlapping cron runs for the same root/run id, and logs per-symbol failures without stopping the whole batch. Tests also prove `founder silver` rebuilds Silver quotes from Bronze without API calls, `founder gold` rebuilds Gold risk inputs from Silver without API calls, and `founder refresh` produces the same mocked final lake outputs as running the three phases manually.

Idempotency: Re-running the same cron bronze run id updates or validates Bronze and operational metadata without duplicating provider rows, losing partial progress, overlapping active writes, or touching analytical Silver and Gold outputs. Re-running Silver and Gold builds from unchanged inputs produces the same outputs without duplicate rows; re-running refresh with unchanged mocked inputs produces the same Bronze, Silver, Gold, and operational metadata outputs.

## Portfolio Evaluation And Optimization PR Stack

Priority policy: For the current UCITS ETF case, prioritize robust risk-first computations that work with daily Gold returns, noisy expected-return estimates, long-only constraints, and highly correlated instruments. Treat maximum Sharpe, efficient-frontier views, and CVaR as comparison or later-stage work until input quality, constraints, and out-of-sample behavior are proven.

### PR15. Gold Evaluation Dataset Contracts And Paths

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/20.

Priority: P0 foundation.

Depends on: PR14.

Scope: Add deterministic Gold path helpers, schema contracts, and documentation for independent portfolio evaluation outputs: aligned return matrices, asset metrics, portfolio returns, drawdowns, portfolio metrics, efficient-frontier points, frontier weights, and optimized weights. Keep the module independent of Search and Bronze.

Acceptance: Tests verify every new Gold path and schema; docs state that evaluation reads existing Gold returns and writes only Gold datasets; no EODHD token, Search run, or Bronze run is required.

Idempotency: Path and schema helpers are pure and deterministic; adding contracts does not create or mutate lake data.

### PR16. Evaluation Module: Return Matrix And Asset Metrics

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/21.

Priority: P0 foundation.

Depends on: PR15.

Scope: Create `founder.evaluation` to read `lake/gold/returns/{exchange}/{ISIN}.parquet`, align returns by date and listing, and write Gold asset metrics such as observation count, first date, last date, mean return, annualized return, annualized volatility, downside deviation, Sharpe ratio, and Sortino ratio.

Acceptance: Tests cover date alignment, missing-date handling, annualization, zero-variance assets, stable listing identifiers, and deterministic output ordering.

Idempotency: Re-running evaluation with the same Gold returns and evaluation id replaces or validates the same return-matrix and asset-metric outputs without duplicate rows.

### PR17. Evaluation Module: Portfolio Returns And Drawdown Metrics

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/24.

Priority: P0 first decision support.

Depends on: PR16.

Scope: Add portfolio-level metric computation for explicit weight vectors, including portfolio return series, cumulative wealth, running peak, drawdown series, maximum drawdown, drawdown duration, recovery duration, Calmar ratio, and ulcer index. Start with equal-weight and user-supplied weight inputs.

Acceptance: Tests cover single-asset, multi-asset, missing-return alignment, cash-free full-investment weights, max drawdown, drawdown duration, recovered and unrecovered drawdowns, and deterministic Gold output schemas.

Idempotency: Recomputing the same portfolio id from the same return matrix and weights overwrites or validates the same Gold portfolio-return, drawdown, and metric datasets.

### PR18. Portfolio Module: Core Optimization Objectives And Target Weights

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/26.

Priority: P0 first optimizer.

Depends on: PR17.

Scope: Extend `founder.portfolio` from constraint validation into deterministic optimization objectives that consume Gold evaluation datasets and write selected target weights to Gold. Include equal-weight baseline, constrained minimum variance, maximum Sharpe as a comparison objective, and target-return minimum variance before adding more advanced objectives.

Acceptance: Tests cover objective selection, covariance-matrix use, expected-return vector use, full-investment constraints, long-only constraints, allocation caps, risk-free-rate handling, infeasible constraints, deterministic tie-breaking, and Gold target-weight output rows with objective metadata.

Idempotency: Re-running the same optimization id with unchanged evaluation inputs and constraints produces the same target-weight rows and does not modify Search, Bronze, Silver, or Gold evaluation data.

### PR19. Portfolio Module: Risk Parity And Equal Risk Contribution

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/32.

Priority: P1 robust optimizer.

Depends on: PR18.

Scope: Add risk parity and equal-risk-contribution computations from the covariance matrix. Compute marginal risk contribution, absolute risk contribution, percent risk contribution, objective residuals against equal risk budgets, and final long-only target weights.

Acceptance: Tests cover diagonal covariance, correlated assets, zero-variance assets, allocation bounds, risk-budget residuals, risk contribution rows, convergence failure reporting, and deterministic target-weight outputs.

Idempotency: Re-running the same risk-parity optimization id with unchanged covariance and constraints produces the same risk contribution and target-weight Gold rows.

### PR27. Gold Correlation Edge Dataset Baseline

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/28.

Priority: P0 scalability foundation.

Depends on: PR18.

Scope: Add a compact Gold `correlation_edges` dataset for pair search and filtering without materializing dense `150k x 150k` matrices as the primary storage contract. Store upper-triangle pairs only, include deterministic listing ids, metric/version metadata, common date range, common observation count, and bucketed Parquet files.

Acceptance: Tests cover deterministic edge ordering, threshold filtering, top-k limiting, common-date observation metadata, upper-triangle-only output, bucketed Gold paths, and idempotent rewrites.

Idempotency: Re-running the same edge build for a version and metric replaces stale bucket files and writes the same rows for unchanged returns and options.

### PR28. Gold Spearman Correlation Edges

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/30.

Priority: P0 robust correlation foundation.

Depends on: PR27.

Scope: Extend Gold `correlation_edges` with `metric=spearman` by ranking common-date return values per pair and computing Pearson correlation on those ranks. Preserve threshold filtering, top-k limiting, bucketed Parquet output, and the existing edge schema.

Acceptance: Tests cover Spearman edge values, separate metric paths, unchanged Pearson behavior, and deterministic bucketed writes.

Idempotency: Re-running the same Spearman edge build for a version replaces stale Spearman bucket files and does not modify Pearson edge outputs.

### PR29. Gold Correlation Edges: Skip Same-ISIN Pairs

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/40.

Priority: P0 scalability and duplicate-instrument hygiene.

Depends on: PR27.

Scope: Update Gold `correlation_edges` so pair generation skips listings with the same ISIN even when exchange or code differs. Preserve upper-triangle output, metric-specific paths, common-date intersections, threshold filtering, top-k limiting, and bucketed Parquet output.

Acceptance: Tests prove same-ISIN cross-listing pairs are not emitted, cross-ISIN pairs remain, and edge rows still stay upper-triangle and deterministic.

Idempotency: Re-running the same edge build for a version and metric replaces the same bucket files without reintroducing same-ISIN rows.

### PR20. Evaluation Module: Walk-Forward Backtesting

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/34.

Priority: P1 trust gate.

Depends on: PR19.

Scope: Add walk-forward evaluation over rolling or expanding windows. For each train/test split, compute in-sample expected returns and covariance, fit selected objective weights, apply them out-of-sample, and write realized return, volatility, Sharpe, drawdown, turnover, and weight history rows.

Acceptance: Tests cover rolling windows, expanding windows, insufficient training history, deterministic split ids, objective reuse, out-of-sample return application, turnover from previous weights, and Gold backtest metric and weight-history schemas.

Idempotency: Re-running the same walk-forward backtest id with unchanged returns, objective settings, windows, and constraints produces the same split ids, metrics, and weight rows.

### PR21. Evaluation Module: Rebalancing Simulation

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/34.

Priority: P1 implementation realism.

Depends on: PR20.

Scope: Add rebalancing simulations for fixed calendar schedules and drift-threshold schedules. Compute pre-trade weights, target weights, turnover, transaction-cost estimates, post-cost returns, portfolio value, rebalance events, and realized drawdown metrics.

Acceptance: Tests cover monthly, quarterly, annual, and threshold rebalancing; no-rebalance periods; transaction-cost application; cash-free full investment; turnover calculation; drift detection; and deterministic Gold rebalance event and portfolio metric rows.

Idempotency: Re-running the same rebalancing simulation id with unchanged returns, target-weight rules, schedule, and cost assumptions produces the same events and metrics without duplicate rows.

### PR22. Portfolio Module: Hierarchical Risk Parity

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/34.

Priority: P2 correlated-universe optimizer.

Depends on: PR19.

Scope: Add hierarchical risk parity computations from the correlation and covariance matrices. Compute correlation distance, deterministic clustering order, quasi-diagonal ordering, recursive bisection allocations, cluster risk contributions, and final HRP target weights.

Acceptance: Tests cover correlation-to-distance conversion, stable clustering tie-breaks, two-cluster and multi-cluster examples, highly correlated ETF groups, allocation caps, deterministic ordering, and Gold outputs for cluster structure and target weights.

Idempotency: Re-running the same HRP optimization id with unchanged correlation, covariance, and constraints produces the same cluster rows and target-weight rows.

### PR23. Portfolio Module: Maximum Diversification Objective

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/34.

Priority: P2 robust comparison optimizer.

Depends on: PR19.

Scope: Add maximum-diversification optimization. Compute asset volatility vector, portfolio volatility, diversification ratio, constrained optimizer weights, and contribution diagnostics that explain which assets improved portfolio diversification.

Acceptance: Tests cover diagonal and correlated covariance matrices, zero-volatility handling, long-only bounds, allocation caps, diversification-ratio calculation, infeasible constraints, and deterministic Gold metric and target-weight rows.

Idempotency: Re-running the same maximum-diversification optimization id with unchanged inputs and constraints produces the same diversification metrics and target weights.

### PR24. Evaluation Module: Efficient Frontier Generator

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/34.

Priority: P2 analysis and visualization.

Depends on: PR18.

Scope: Add efficient-frontier computation from expected returns and covariance inputs. Generate target-return grid points, minimum-variance weights for each target, and long-format frontier weight rows. Keep optimizer settings, annualization period, risk-free rate, and allocation bounds explicit in the evaluation run metadata.

Acceptance: Tests cover two-asset analytic cases, long-only bounds, full-investment constraints, infeasible target returns, deterministic target grids, stable frontier point ids, and separate Gold datasets for frontier metrics and weights.

Idempotency: Re-running the same frontier evaluation id with the same inputs and settings produces the same point ids, metrics, and weight rows without accumulating stale frontier files.

### PR25. Portfolio Module: CVaR And Tail-Risk Optimization

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/34.

Priority: P3 tail-risk extension.

Depends on: PR21.

Scope: Add historical CVaR evaluation and optional CVaR minimization for long-only portfolios. Compute portfolio loss series, VaR threshold, CVaR, tail observation count, tail scenario weights, and constrained target weights for selected confidence levels.

Acceptance: Tests cover loss-series construction, VaR quantile selection, CVaR averaging, repeated losses at the threshold, confidence-level validation, long-only constraints, infeasible constraints, deterministic tail scenario rows, and Gold target-weight outputs.

Idempotency: Re-running the same CVaR evaluation or optimization id with unchanged returns, confidence level, and constraints produces the same tail-risk metrics and target weights.

### PR26. Evaluation CLI And Dry-Run Integration

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/34.

Priority: P1 for P0/P1 objectives, P3 for full advanced stack.

Depends on: PR14 and PR21. Full advanced-objective flags depend on PR22, PR23, PR24, and PR25.

Scope: Add a user entry point such as `founder evaluate` that runs evaluation and optional optimization from existing Gold returns. Extend the mocked dry run with evaluation outputs so the portfolio analytics path is reproducible without credentials.

Acceptance: CLI tests cover evaluation-only runs, optimization-enabled runs, selected objective flags, walk-forward and rebalancing flags, missing Gold input handling, deterministic dry-run outputs, and clear summaries of generated Gold datasets.

Idempotency: Re-running the same command with the same evaluation id and unchanged inputs produces the same Gold outputs and summary without duplicate rows or API calls.

## Architecture Refactor PR Stack

Priority policy: Keep this stack behavior-preserving first. Each PR must be small enough to review by module boundary, must preserve existing lake dataset names and CLI behavior unless its scope explicitly says otherwise, and must pass the existing PR quality gate before the next PR starts.

### PR30. Gold Pair Statistics Boundary Refactor

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/44.

Priority: P0 scalability and correctness guardrail.

Depends on: PR29.

Scope: Split `founder.gold` pair-statistic logic into focused internal units for return indexing, common-date pairing, online moments, Pearson/Spearman/covariance calculation, edge limiting, and deterministic pair-row construction. Preserve public Gold function names, CLI output, lake paths, schemas, worker concurrency behavior, and resume manifests. Add one shared pair-iteration path so dense correlation, covariance, and edge outputs cannot drift in ordering or same-ISIN filtering rules.

Acceptance: Tests prove unchanged outputs for existing return, covariance, correlation, Spearman edge, top-k, threshold, same-ISIN skip, concurrency, and resume fixtures. Tests also prove the shared pair iterator emits upper-triangle pairs deterministically, never recomputes symmetric pairs, and exposes enough metadata for both dense rows and edge rows.

Idempotency: Refactoring does not create new lake datasets or mutate existing data. Re-running Gold with unchanged Silver quotes produces the same return, covariance, correlation, feature, edge, and manifest rows as before the refactor.

### PR31. Dataset Contract Registry Refactor

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/44.

Priority: P0 schema drift prevention.

Depends on: PR30.

Scope: Introduce a central dataset contract registry that owns dataset names, schema versions, required fields, optional fields, stable sort keys, and owning module metadata for Search, Bronze, Silver, Gold, Evaluation, and Portfolio outputs. Keep existing path helpers and `required_fields` behavior compatible while routing them through the registry. Add validation helpers that writers can call before writing rows, but migrate writer call sites only where the touched module already has focused tests.

Acceptance: Tests verify every existing dataset contract currently referenced by paths, schemas, docs, and CLI summaries is present in the registry; required-field results remain backwards-compatible; registry lookup is deterministic; duplicate dataset names or fields fail fast; and row validation reports missing fields without reading credentials or lake data.

Idempotency: Registry lookups and validation are pure. Adding the registry must not rewrite lake files, rename datasets, change path strings, or modify existing CLI summaries except for deterministic error messages from validation helpers.

### PR32. Evaluation And Portfolio Package Boundary Refactor

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/44.

Priority: P1 maintainability for analysis and optimizer growth.

Depends on: PR31.

Scope: Convert the broad Evaluation and Portfolio modules into package-style boundaries while preserving import compatibility from `founder.evaluation` and `founder.portfolio`. Move matrix, asset metric, portfolio return, drawdown, walk-forward, rebalance, frontier, tail-risk, constraint, objective, risk-parity, HRP, maximum-diversification, and writer helpers into focused internal modules. Keep public functions re-exported from the original module names so existing CLI and tests continue to work.

Acceptance: Tests prove existing imports, CLI evaluation behavior, dry-run integration, optimizer outputs, and Gold writer paths remain unchanged. Module-level tests cover that internal packages do not import Search, Bronze, Silver, CLI, or config modules, preserving architecture direction.

Idempotency: The refactor is behavior-preserving and writes no data by itself. Re-running evaluation and portfolio commands with unchanged Gold inputs produces the same output rows, file paths, and summaries as before the refactor.

### PR33. Unified Run State And Job Manifest Refactor

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/44.

Priority: P1 operations and dashboard readiness.

Depends on: PR32.

Scope: Add a shared run-state contract for long-running Search, Bronze, Silver, Gold, Evaluation, and Portfolio jobs. Record deterministic job manifests with job type, run id, status, timestamps, input paths, output paths, row counts, concurrency, resume marker, and non-secret error summary. Keep existing module-specific manifests readable and write compatibility adapters instead of replacing them in one step. Expose a small internal service API that CLI commands can use without embedding job-state formatting logic.

Acceptance: Tests cover manifest creation for successful, partial, failed, and resumed jobs; token redaction; deterministic manifest ids; stable JSON ordering; compatibility with existing Bronze and Gold run metadata; and CLI summaries sourced from the shared run-state API. Tests prove failed or resumed jobs do not duplicate provider, Silver, Gold, Evaluation, or Portfolio rows.

Idempotency: Re-running the same job id with unchanged inputs updates only deterministic status and summary fields allowed by the manifest contract, preserves prior error evidence, and never creates duplicate lake rows or overlapping active-job locks.

### PR34. Production Optimizer Interface And Diagnostics Refactor

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/44.

Priority: P2 portfolio trust and future solver integration.

Depends on: PR33.

Scope: Separate deterministic baseline optimizers from future production solver-backed optimizers behind a stable optimizer interface. Add structured diagnostics for feasibility, objective value, constraint violations, covariance conditioning, input coverage, turnover estimate, and optimizer status. Preserve existing equal-weight, minimum-variance, maximum-Sharpe, target-return minimum-variance, risk-parity, HRP, maximum-diversification, frontier, and CVaR outputs while adding diagnostics rows or metadata through explicit Gold contracts.

Acceptance: Tests cover identical target weights for existing deterministic optimizers, deterministic diagnostics for feasible and infeasible cases, covariance warning thresholds, missing-input coverage warnings, allocation-bound violations, and CLI summaries that distinguish baseline results from production-ready solver results. Docs state that baseline objectives are deterministic decision-support outputs, not execution approval.

Idempotency: Optimizer diagnostics are deterministic for unchanged inputs and constraints. Re-running an optimization id overwrites or validates the same target-weight and diagnostic outputs without changing Search, Bronze, Silver, Gold return, or Evaluation datasets.

## Refactor Hardening PR Stack

Priority policy: Treat this stack as the next behavior-preserving hardening pass after PR30-PR34. Each PR must be based on the previous PR in this section, preserve public imports and existing CLI commands, keep current lake paths and schemas stable unless explicitly stated, and add architecture tests before moving code across boundaries.

### PR35. Enforce Real Evaluation And Portfolio Package Boundaries

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/46.

Priority: P0 maintainability and architecture enforcement.

Depends on: PR34.

Scope: Replace the current `evaluation_parts` and `portfolio_parts` re-export shells with real internal modules that own implementation code. Move matrix, metrics, portfolio-return, drawdown, walk-forward, rebalance, frontier, tail-risk, constraint, objective, risk-parity, HRP, and maximum-diversification functions into their focused modules while keeping `founder.evaluation` and `founder.portfolio` as compatibility facades. Add import-boundary tests that prevent internal Evaluation and Portfolio modules from importing Search, Bronze, Silver, CLI, config, or HTTP modules.

Acceptance: Existing public imports from `founder.evaluation` and `founder.portfolio` still work. Existing CLI evaluation behavior, dry-run behavior, optimizer outputs, and Gold writer paths remain unchanged. Tests fail if a package boundary module is only a re-export wrapper or if a forbidden dependency direction is introduced.

Idempotency: This PR only moves code and adds boundary checks. Running evaluation, portfolio optimization, dry-run, and existing tests with unchanged inputs produces byte-equivalent rows, paths, and JSON summaries compared with the pre-refactor behavior.

### PR36. Extract Scalable Gold Pair Statistics Engine

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/46.

Priority: P0 scalability for large covariance and correlation workloads.

Depends on: PR35.

Scope: Move Gold pair-statistics code into a focused engine that owns return indexing, common-date intersection, pair iteration, online covariance, incremental Pearson, approximate online Spearman, observation metadata, upper-triangle generation, same-ISIN filtering, threshold filtering, top-k limiting, and deterministic bucket assignment. Keep existing dense per-ISIN correlation and covariance outputs as compatibility outputs, but make `correlation_edges` the primary scalable pair-search path.

Acceptance: Tests prove dense covariance/correlation rows, Pearson edges, Spearman edges, common-date metadata, same-ISIN skipping, top-k limiting, threshold filtering, bucket ordering, and worker outputs are unchanged for existing fixtures. New tests prove the engine streams pair records without materializing unnecessary symmetric duplicate pairs and exposes one shared observation contract for dense and edge outputs.

Idempotency: Re-running Gold with unchanged Silver quotes produces the same return, covariance, correlation, feature, edge, run-manifest, and job-manifest rows as before this PR. The PR must not rename lake folders, change schema fields, or rewrite existing local lake data during tests.

### PR37. Type Critical Dataset Rows And Contract Validation

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/46.

Priority: P1 schema drift prevention.

Depends on: PR36.

Scope: Introduce typed row contracts for the highest-risk datasets: Gold returns, covariance rows, correlation edge rows, evaluation return matrix rows, portfolio target weights, optimizer diagnostics, and job manifests. Keep `JsonRow` as the serialization boundary but convert high-risk internal functions to accept and return typed DTOs or `TypedDict`s before writing rows. Route writer validation through the dataset contract registry for touched outputs.

Acceptance: Mypy remains strict. Tests prove missing required fields fail before writes for the typed datasets, optional fields stay backward-compatible, stable sort keys are respected, and existing serialized rows are unchanged. Documentation states which datasets are now typed internally and which remain generic row dictionaries.

Idempotency: Contract validation is pure and deterministic. Re-running touched writers with unchanged inputs produces the same files and row ordering; invalid rows fail before any partial write happens.

### PR38. Split CLI Parsing From Workflow Execution

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/46.

Priority: P1 operational clarity and reuse.

Depends on: PR37.

Scope: Introduce workflow modules for Search, Bronze, Silver, Gold, Refresh, and Evaluate. Keep `founder.cli` responsible for parser construction, argument normalization, logging setup, and printing summaries only. Move live/mock Bronze execution, layer-lock orchestration, refresh phase sequencing, Gold build invocation, and Evaluation option routing into workflow functions with typed summary results.

Acceptance: CLI tests prove every existing command, flag, default, error, and JSON summary remains compatible. Unit tests can call each workflow without parsing argv. Refresh tests prove Bronze, Silver, and Gold phase summaries and failure behavior are deterministic. No workflow module imports `argparse`.

Idempotency: Re-running CLI commands and direct workflow calls with unchanged inputs produces the same lake writes and summaries. The refactor must not add hidden network calls, change default concurrency, or alter lock paths.

### PR39. Add Import-Boundary And Scale-Guard Quality Gates

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/46.

Priority: P1 long-term architecture safety.

Depends on: PR38.

Scope: Add automated architecture checks for forbidden dependency directions, package boundary ownership, private-helper imports across layers, and accidental dependency-heavy shared utilities. Add scale-guard tests for pair-statistics generation and optimizer candidate generation so large-universe code paths fail fast with explicit limits or streaming behavior instead of silently materializing unbounded dense structures.

Acceptance: The PR quality gate includes the new architecture checks. Tests fail if Silver imports private Bronze helpers, Evaluation imports ingestion layers, Portfolio core math reads lake files directly, CLI is imported from business modules, or shared modules start importing heavy layer-specific dependencies. Scale-guard tests cover Gold pair generation and Portfolio candidate generation with deterministic thresholds.

Idempotency: New gates are read-only and deterministic. Running the gate multiple times does not create or modify lake files, docs, or generated artifacts beyond existing test temp directories.

## Refresh, Selection, And Update Module PR Stack

Status note (superseded): This entire stack is historical. PR40-PR55 merged the `founder.refresh`/`founder.selection`/`founder.update` package boundaries and standalone `founder-refresh`/`founder-selection`/`founder-update` entry points described below, but a later CLI simplification replaced that three-module surface with the current five-stage statistics funnel (`fetch_all_isins`, `fetch_all_quotes`, `metadata_filter`, `univariate_filter`/`univariate_statistics`, `bivariate_statistics`, `multivariate_statistics`) documented in `ARCHITECTURE.md` and `README.md`. The `founder.selection` and `founder.update` packages and their standalone entry points no longer exist; see `docs/backlog/00-critical-correctness-priority-queue.md` C01 for the pyproject.toml script-registry defect this left behind and its fix. Do not use this section as a guide to the current CLI or module layout.

Priority policy: Replace the technical-layer workflow surface with three domain modules and three CLI namespaces: `refresh` discovers every provider-visible ISIN and maintains catalog plus market-data snapshots; `selection` defines, persists, and activates deterministic conjunctive selections without network or metric computation; `update` computes and reuses metrics only for the current Selection, asks `selection` to finalize metric predicates, and publishes analyses. Each module owns its contracts, application service, ports, adapters, CLI parser, locks, manifests, and current pointer. Dependency direction is strict: `refresh` imports neither other domain module; `selection` may consume only public Refresh contracts/read ports; `update` consumes public Refresh and Selection contracts/services; no reverse imports are allowed. Standalone entry points `founder-refresh`, `founder-selection`, and `founder-update` and equivalent `founder refresh`, `founder selection`, and `founder update` namespaces delegate to the same module-owned parsers. PR40 through PR55 are a strict stack: base each branch on the preceding branch until it merges, then restack all downstream branches. Preserve current commands through explicit compatibility adapters until PR55 performs the documented cutover.

Delivery order is determined first by dependency and then by unblocking value: PR40 establishes package boundaries; PR41 through PR44 stabilize the Refresh, Selection, and Update public contracts before side effects; PR45 through PR47 make the global Refresh source operational; PR48 exposes Selection; PR49 and PR50 produce and apply candidate evidence; PR51 establishes exact-calendar portfolio comparability before PR52 adds pairwise similarity statistics; PR53 and PR54 integrate analyses and execution; PR55 performs migration and cutover. Every PR depends directly on its predecessor so the declared order and stacked branch ancestry remain identical.

### PR40. Three-Module Boundaries And Public Contract Skeleton

Branch: `refactor/three-module-boundaries`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/51.

Priority: P0 architecture foundation.

Depends on: PR39.

Scope: Create package boundaries `founder.refresh`, `founder.selection`, and `founder.update`, each with public `contracts`, `ports`, `service`, and `cli` modules plus private infrastructure adapters where required. Define public import surfaces and forbid consumers from importing another module's adapters, repositories, private helpers, or CLI implementation. Keep existing `config`, `http`, `logging`, `paths`, `schemas`, `table_io`, `run_locks`, and `run_state` as infrastructure shared by ports rather than a fourth business module. Make `founder.cli` a dispatcher that delegates parser registration and execution to module-owned CLI adapters; it must contain no Refresh, Selection, or Update business decisions. Keep legacy Search, Bronze, Silver, Gold, Evaluation, and Portfolio facades operational behind compatibility adapters during the stack.

Acceptance: Import and architecture tests prove the dependency direction `refresh <- selection <- update`, prove no reverse or circular import, prove domain services do not import `argparse`, EODHD, or filesystem implementations, and prove CLI modules do not own business logic. Each package imports without reading configuration, opening the network, acquiring locks, or touching the lake. Existing command behavior and public facades remain unchanged in this PR. A contract-version policy defines additive versus breaking changes, canonical serialization, and migration ownership.

Determinism: Public DTO equality and hashes use typed canonical payloads with explicit schema versions; adapters, process time, filesystem paths, and dictionary order cannot affect domain identities. Architecture checks enumerate allowed dependency directions explicitly and return stable diagnostics.

Idempotency: Importing modules, constructing services, registering parsers, and running architecture checks are read-only. Repeating package setup creates no lake artifacts, pointers, locks, network requests, or compatibility-state changes.

### PR41. Refresh Catalog Contracts And Stable Instrument Identities

Branch: `feat/refresh-catalog-contracts`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/51.

Priority: P0 Refresh data-model foundation.

Depends on: PR40.

Scope: In `founder.refresh.contracts`, add immutable, versioned DTOs for `InstrumentRecord`, `ListingRecord`, `CatalogSnapshot`, `CatalogCompleteness`, `CanonicalListingPolicy`, `MarketDatasetVersion`, `MarketDataVersionSet`, `RefreshSnapshotRef`, and missing-ISIN or unsupported-listing review rows. Define `instrument_id` as the normalized non-empty ISIN and `listing_id` from a versioned hash of normalized provider, exchange, and code. Preserve every listing for an ISIN; keep listing country, exchange, and trading currency separate from domicile and fund metadata. Include provider-declared distribution frequency and provenance, historical-NAV capability, active state, `first_seen`, and `last_seen`. Define producer-owned Refresh read ports that Selection and Update can consume without importing Refresh adapters. Add deterministic lake paths, schemas, sort keys, and atomic current-Refresh-pointer semantics without changing runtime ingestion.

Acceptance: Contract and path tests cover duplicate listings, conflicting metadata, one ISIN across exchanges and currencies, empty or invalid ISINs, disappeared listings, declared payout metadata, NAV capability present or absent, schema migration, and canonical-listing-policy metadata. A `RefreshSnapshotRef` pins exactly one catalog snapshot and one immutable market-data version set; partial or incompatible references fail validation. Documentation distinguishes instrument, listing, catalog snapshot, market-data version, provider metadata, and derived metrics.

Determinism: Canonical JSON, normalized identifiers, explicit contract versions, and stable sorting make instrument, listing, catalog, version-set, and pointer ids independent of input order, Parquet encoding, process time, locale, and worker scheduling. Operational timestamps and retry counters are excluded from content identities.

Idempotency: Rebuilding contracts and paths from identical normalized records produces the same immutable ids and logical rows without duplicate members or pointer churn. Contract validation and read-port access never mutate Refresh, Selection, or Update state.

### PR42. Selection Predicate And Metric-Requirement Contracts

Branch: `feat/selection-predicate-contracts`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/51.

Priority: P0 deterministic Selection semantics.

Depends on: PR41.

Scope: In `founder.selection.contracts`, define typed `Predicate`, `PredicateValue`, `FilterPhase`, `FieldDefinition`, `MetricRequirement`, `MetricEvidence`, `ClassificationProfileRef`, and `BenchmarkRef` contracts. Build a strict field registry and compiler supporting `eq`, `ne`, `in`, `not-in`, `contains`, `starts-with`, `regex`, `lt`, `lte`, `gt`, `gte`, `between`, `is-null`, and `not-null` only where valid for the field type. Combine predicates conjunctively; values inside one `in` predicate are alternatives. Separate catalog predicates, raw-metric predicates, and classification predicates. Catalog fields come from public Refresh contracts; Selection itself owns the names, types, operators, availability rules, and evidence requirements for metric fields, while Update later produces that evidence. Use parameterized DuckDB reads over immutable Refresh catalog Parquet files; reject raw SQL, unknown metadata paths, implicit casts, and unavailable-value-as-zero behavior.

Acceptance: Tests cover every operator and scalar type, repeated predicates, null and availability semantics, case normalization, injection-like input, invalid values, unknown fields, instrument-versus-listing scope, exact and `in` exchange filters, declared payout frequency, every planned raw metric and classification field, and deterministic canonical listing resolution. The public field-listing API exposes field name, type, scope, phase, nullability, allowed operators, metric requirement, and benchmark requirement. Selection tests use supplied metric evidence only and prove no EODHD, Bronze, Silver, Gold, or Update import or side effect.

Determinism: Canonical predicate JSON sorts normalized predicates by phase, field, operator, and typed value. CLI ordering, catalog row order, dictionary order, locale, and DuckDB scan order cannot change definition hashes, required metric sets, candidate ordering, or predicate outcomes.

Idempotency: Predicate compilation and evaluation are pure and read-only. Rebuilding views or evaluating identical catalog rows and metric evidence produces the same result without changing Refresh snapshots, metric artifacts, Selection pointers, or lake data.

### PR43. Selection Identity, Candidate And Final Membership Contracts

Branch: `feat/selection-membership-contracts`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/51.

Priority: P0 durable Selection lifecycle.

Depends on: PR42.

Scope: Add immutable `SelectionDefinition`, `CandidateMembership`, `FinalMembership`, `SelectionState`, `CurrentSelectionPointer`, and `MetricEvidenceManifestRef` contracts plus Selection repository ports. Derive `selection_id` from canonical catalog, raw-metric, and classification predicates, canonical-listing policy, metric and classification profile references, and optional benchmark listing id. Derive `candidate_membership_id` from ordered canonical listing ids after catalog predicates and pin its source `catalog_snapshot_id`, not a market-data version set. Finalization is a public pure Selection service that accepts one candidate id plus a complete typed metric-evidence manifest, validates evidence versions and availability, applies remaining predicates, and derives `membership_id`; Update must call this service rather than implementing filter semantics. Catalog-only Selections finalize immediately. Metric-dependent Selections remain `pending_update` until valid evidence arrives. Store active, paused, archived, empty, pending, ready, and stale states and use compare-and-swap current pointers.

Acceptance: Tests cover identical filters in different orders, stable readable names, hash collisions guarded by full hashes, one canonical listing per ISIN, changed and unchanged catalog membership, pending metric requirements, complete and incomplete evidence, unavailable metrics, stale evidence, benchmark mismatch, empty membership, lifecycle transitions, member diffs, repeated finalization, and concurrent pointer updates. A candidate can be current while final membership is pending; only a ready final membership is eligible for pair or portfolio analytics.

Determinism: Selection names, ids, candidate and final membership ids, member ordering, required metric sets, states, and diffs depend only on versioned definitions, pinned Refresh catalog snapshot, canonical policy, and evidence identities. Creation time, user locale, process order, and CLI predicate order are metadata only.

Idempotency: Creating, refreshing, activating, or finalizing the same Selection against unchanged inputs resolves to existing immutable artifacts without duplicate rows or pointer churn. A changed candidate or final membership writes a new version and never mutates prior membership content; failed compare-and-swap leaves the newer pointer untouched.

### PR44. Update Contracts, Pinned Inputs, And Shared Work Planner

Branch: `feat/update-work-planner`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/51.

Priority: P0 Update execution foundation.

Depends on: PR43.

Scope: In `founder.update.contracts`, add immutable, versioned `UpdateRequest`, `PinnedUpdateInput`, `MetricSpec`, `MetricCacheKey`, `MetricArtifactRef`, `UpdatePlan`, `UpdateRunManifest`, `UpdateResult`, and `CurrentUpdatePointer` contracts. An Update defaults to the current Selection but pins the exact `selection_id`, `candidate_membership_id`, current `RefreshSnapshotRef`, benchmark, as-of date, metric profile, and classification profile before planning. Require the Refresh snapshot's `catalog_snapshot_id` to equal the candidate's source catalog id; otherwise return `selection_stale` and require an explicit `founder selection refresh` rather than changing membership inside Update. A compatible newer market-data version set for the same catalog is valid. Build a pure work planner from Selection-owned `MetricRequirement` rows. It unions identical asset, benchmark-relative, classification, pair, calendar, and analysis keys across requested work, marks each as hit, append delta, rebuild, missing, blocked, or oversized, and orders dependencies explicitly. Update owns metric artifacts and manifests but does not own Selection predicate semantics, catalog downloads, or current-Selection changes.

Scope continued: Define compare-and-swap publication: a completed run may publish final Selection evidence and the current Update pointer only if the current Selection still references the pinned candidate and the current Refresh pointer still equals the pinned Refresh snapshot. If either pointer advances during execution, preserve the immutable completed artifacts but mark the run `stale_not_published`. Add one Update run lock per lake root and selection id plus per-cache-key locks so independent Selections can run concurrently while shared artifacts are computed once. Keep cache repositories behind Update ports and preserve sparse and scale-limit contracts before any dense allocation.

Acceptance: Contract and planner tests cover no current Selection, pending and ready Selections, empty candidates, compatible newer market-data versions, mismatched catalog snapshots, missing or stale Refresh versions, missing benchmark, duplicate requirements, overlapping Selections, cache corruption, append-only changes, corrections, deletions, incompatible algorithm versions, pair limits, stale publication, and concurrent identical keys. A plan cannot include pair, calendar, or portfolio work before final membership exists; it schedules candidate asset evidence first and a Selection-finalization barrier before final-member work.

Determinism: Plan ids, cache keys, dependency order, hit decisions, stale decisions, and manifests derive only from pinned contract ids, canonical metric specs, algorithm versions, and immutable input versions. Selection order, filesystem discovery order, worker scheduling, and operational timestamps cannot change logical plans or artifact identities.

Idempotency: Replanning unchanged pinned inputs yields the same plan and performs no writes. Executing or resuming a plan computes each missing key once, reuses completed immutable artifacts, and never republishes unchanged evidence or pointers. A failed or stale run cannot roll back newer Selection, Refresh, or Update state.

### PR45. Refresh Complete EODHD Catalog Synchronization

Branch: `feat/refresh-catalog-sync`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 complete all-ISIN discovery.

Depends on: PR44.

Scope: Implement the Refresh catalog service and EODHD adapter to enumerate every configured exchange symbol list without a name query, archive raw responses per exchange in Bronze, normalize all provider-visible listings, and publish an immutable Silver catalog snapshot. Add bounded, resumable metadata enrichment for fields absent from bulk lists, including declared distribution policy and historical-NAV capability when the provider exposes them. Record expected, completed, failed, and skipped exchanges and enrichments plus completeness policy results. Keep rows without an ISIN in review output, but exclude them from the market-data universe. Do not create Selections, compute metrics, or depend on Selection criteria.

Acceptance: Mocked provider and service tests cover all configured exchanges, duplicate symbols, multiple listings per ISIN, partial provider failure, retries and `Retry-After`, resume after interruption, missing ISINs, disappeared listings, incomplete enrichment, token redaction, and rejection of an incomplete snapshot. Summaries report listing, unique-ISIN, missing-ISIN, exchange, enrichment, NAV-capability, and error counts. No Search query or active Selection can restrict catalog synchronization.

Determinism: Equivalent provider payloads produce the same normalized snapshot, conflicts, and snapshot id regardless of response order, exchange completion order, worker scheduling, or retry history. Provider raw artifacts are keyed by provider, exchange, and response content rather than completion time.

Idempotency: Repeating or resuming a catalog run reuses completed raw and normalized artifacts, requests only missing work, and publishes no duplicate snapshot or pointer update. A failed completeness check leaves the prior current Refresh pointer unchanged.

### PR46. Refresh All-ISIN Market Data And Versioned Inputs

Branch: `feat/refresh-all-isin-market-data`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 catalog-wide data completeness.

Depends on: PR45.

Scope: Implement Refresh market-data planning for every active eligible unique ISIN in the current catalog, independent of every Selection. Resolve one deterministic canonical listing per ISIN and record explicit exclusions for missing, invalid, inactive, or provider-unsupported listings. Fetch gap-aware EOD quotes, dividends, splits, and historical NAV when supported with bounded concurrency, retries, partial-failure isolation, and full-history first load. Normalize Silver quote rows containing raw `close` and `adjusted_close`, dividend payment date with ex-date fallback, split ratios, and genuine split-adjusted NAV without substituting market price. Publish immutable per-listing dataset versions with parent ids, content fingerprints, date coverage, and `added`, `corrected`, and `deleted` change sets; group them into a `MarketDataVersionSet` only after atomic validation.

Acceptance: Tests prove every eligible catalog ISIN is planned exactly once, duplicate listings resolve consistently, Selection membership has no effect, and exclusions have stable reason codes. Fixtures cover full-history load, appended tails, historical gaps, raw-close and adjusted-close corrections, dividends, payment-date fallback, splits, NAV present or unavailable, deletions, duplicate provider rows, interrupted writes, and a correction with unchanged row count and last date. Failed validation cannot expose partial Bronze, Silver, version-manifest, or version-set state.

Determinism: Canonical listing choice, plan ordering, exclusion reasons, gap windows, normalized rows, fingerprints, change classifications, and version-set ids depend only on catalog policy, provider observations, prior immutable versions, and requested as-of date. Row order, task completion order, file encoding, locale, and process count cannot change logical outputs.

Idempotency: Repeating Refresh with unchanged provider data performs no duplicate downloads where content-addressed raw data is reusable, writes no new logical Silver versions or version set, and leaves pointers stable. Resume consumes only unfinished plan items; corrections rebuild only affected listing datasets and never mutate prior versions.

### PR47. Refresh Service, Standalone CLI, And Atomic Publication

Branch: `feat/refresh-cli`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 operable Refresh module.

Depends on: PR46.

Scope: Add module-owned `RefreshRequest`, `RefreshPlan`, `RefreshRunManifest`, `RefreshResult`, and compare-and-swap `CurrentRefreshPointer` contracts. Implement `founder.refresh.service` orchestration and the standalone `founder-refresh` CLI with `plan`, `run`, and `status`; register equivalent `founder refresh` routing without duplicating parser or handler logic. `run` defaults to all configured exchanges and every eligible catalog ISIN and supports explicit `--as-of`, `--run-id`, `--concurrency`, `--resume`, `--dry-run`, and `--debug`. It may synchronize the catalog and update Bronze/Silver market data, but it must never read the current Selection, compute Gold metrics, or invoke Update. Acquire one Refresh run lock per lake root, retain per-request retry limits, write resumable manifests, and publish the current Refresh snapshot atomically only when configured completeness requirements pass.

Acceptance: Dedicated CLI tests cover each command, argument, default, JSON result, `--debug`, dry-run with no writes, invalid dates, lock contention, partial provider failure, incomplete snapshots, resume, and successful current-pointer publication. Service tests call the same application API without parsing argv. An end-to-end mocked Refresh discovers ISINs, updates every eligible listing's required datasets, reports exclusions and coverage, and produces no Selection or metric artifacts. Existing legacy commands remain available through the compatibility route until PR55.

Determinism: `RefreshPlan` and content ids depend on normalized request fields, prior Refresh snapshot, provider content, and explicit as-of date; generated run ids and operational timestamps are metadata only. CLI argument order and standalone versus umbrella invocation produce identical requests and logical outputs.

Idempotency: Re-running `founder-refresh run` with unchanged data resolves to the existing immutable snapshot and leaves the current pointer unchanged. Interrupted runs resume incomplete plan items, and pointer publication uses compare-and-swap so an older run cannot overwrite a newer successful Refresh.

### PR48. Selection Service, Current Pointer, And Standalone CLI

Branch: `feat/selection-cli`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 operable Selection module.

Depends on: PR47.

Scope: Implement `founder.selection.service` and the standalone `founder-selection` CLI with `fields`, `create`, `list`, `show`, `use`, `refresh`, `diff`, and `status`; register equivalent `founder selection` routing through the module-owned parser. `create` persists an immutable definition and evaluates catalog predicates against a pinned Refresh snapshot. `use` atomically makes exactly one Selection the current Selection for default Update execution and may point to a `pending_update`, `ready`, or empty Selection while exposing that state. `refresh` recomputes candidate membership against an explicitly chosen or current Refresh snapshot but does not download data or compute metrics. Metric-dependent creation and refresh emit exact `MetricRequirement` rows for Update. All commands support structured JSON output and `--debug` without importing Update or provider adapters.

Scope continued: Generate a readable Selection name from all normalized `field_operator_value` fragments joined by underscores, truncate only at fragment boundaries, and append a short `selection_id` suffix. Require an explicit benchmark when predicates need downside capture or composite risk type. Expose current candidate id, current final membership id if ready, Refresh snapshot id, pending metric requirements, lifecycle state, and stale status in every relevant result. The CLI never silently changes the current Selection during `create` or `refresh`; only `use` changes that pointer.

Acceptance: Dedicated CLI tests cover every command, field and repeated-filter syntax, names, lifecycle transitions, current-pointer changes, pending and ready output, empty results, invalid benchmark requirements, stale Refresh snapshots, diffs, `--debug`, and standalone versus umbrella equivalence. Tests prove only `use` changes the current pointer, catalog-only Selections become ready without Update, metric Selections stay pending, and neither CLI nor service performs a network call or writes metric artifacts.

Determinism: Standalone and umbrella invocations normalize to the same typed command requests. The same definition and Refresh snapshot yield the same Selection, candidate membership, requirements, names, ordering, and JSON domain payload regardless of argument order or machine; only explicitly operational fields may differ.

Idempotency: Repeating `create`, `refresh`, or `use` with unchanged inputs resolves to existing definitions, memberships, requirements, and pointer values. Interrupted persistence cannot expose a definition without its candidate membership, and compare-and-swap prevents an older command from replacing a newer current Selection.

### PR49. Update Incremental Per-ISIN Metric Cache

Branch: `feat/update-asset-metric-cache`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 reusable candidate metrics.

Depends on: PR48.

Scope: Implement Update's lazy Asset Metric Cache for the union of listing ids in the pinned current Selection candidate membership, plus an explicitly requested benchmark. Define one versioned metric spec for adjusted-close daily log returns `ln(Px_t / Px_t-1)`, date window, annualization, risk-free assumptions, Expected Shortfall confidence, period-close policy, and algorithm versions. Persist immutable values and mergeable online state for observations, mean, second moment, annualized volatility, downside deviation, Sharpe, Sortino, positive-loss VaR and CVaR/`expected_shortfall`, cumulative wealth, running peak, maximum drawdown, completed peak-to-recovery duration, ongoing right-censored underwater duration, positive-day ratio, closed-month and closed-year positive ratios with denominators, bias-adjusted Fisher-Pearson return skewness, adjusted-close total-return CAGR, annualized OLS log-price slope, trend R-squared, observed payout frequency, and NAV erosion inputs. Keep provider-declared payout frequency as catalog metadata.

Acceptance: Hand-checkable fixtures cover log-return semantics, zero and invalid prices, Sharpe, Sortino, CVaR/Expected Shortfall, volatility, drawdown, completed and right-censored recovery, skewness with zero variance or insufficient history, positive day/month/year ratios, current partial-period exclusion, CAGR, slope units and R-squared, regular and irregular dividends, every payout category, genuine NAV distributions, missing NAV, and availability reasons. Tests prove a shared ISIN is computed once, catalog ISINs outside the candidate set create no artifacts, append applies each new observation once, and historical corrections match full recomputation.

Determinism: Asset keys include listing id, exact quote/dividend/split/NAV input versions, metric-spec hash, date window, and algorithm versions, never ordinary Selection filter thresholds. Online and full rebuilds agree within explicit numeric tolerances and produce identical metadata independent of Selection order, row order, process count, and worker scheduling.

Idempotency: Re-running Update with unchanged candidates and inputs reuses immutable asset artifacts. Verified append-only changes update online state and newly closed periods only; backfills, corrections, deletions, and policy changes rebuild only affected listing artifacts. Concurrent requests for one key publish one valid artifact.

### PR50. Update Screening Classifications And Selection Finalization

Branch: `feat/update-screening-classifications`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 metric-based current Selection.

Depends on: PR49.

Scope: Implement Update's candidate screening, benchmark-relative metrics, classification artifacts, and evidence delivery to Selection. The versioned default classification profile uses a trailing three-year window with at least 504 valid daily observations spanning two years and explicit `insufficient_history` or `unavailable` status. Because exchange `close` is not NAV, derive split-adjusted-but-not-dividend-adjusted `close_price_path_type` with log-slope classes `growing` for `> 0.02`, `stable` for `[-0.02, 0.02]`, `eroding` for `(-0.10, -0.02)`, and `strong_decline` for `<= -0.10`. Derive separate `nav_path_type` with the same boundaries only from genuine historical NAV. Build a distribution-adjusted NAV total-return index from true NAV and cash distributions and define `nav_erosion_rate = max(0, -nav_total_return_cagr)`; never proxy NAV with close or adjusted close.

Scope continued: Classify adjusted-close `total_return_type` as `negative` for CAGR `< -0.02`, `sideways` for `[-0.02, 0.02]`, `steadily_growing` for CAGR `> 0.02` with trend R-squared `>= 0.80`, annualized volatility `<= 0.20`, and maximum drawdown `>= -0.20`, and otherwise `volatile_growing`. Compute `downside_capture_ratio` on exact common dates where an explicit benchmark's adjusted-close log return is negative by dividing annualized compounded candidate return by annualized compounded benchmark return; require at least 60 benchmark-down observations and a negative denominator. A benchmark outside candidate membership is an explicit Update dependency and never becomes a final member implicitly.

Scope continued: Build `risk_type` from maximum drawdown, positive-loss Expected Shortfall at default confidence `0.975`, return skewness, downside capture, and recovery duration. Assign each component `low`, `moderate`, `high`, or `severe`, then use the worst component band. Default ordered intervals are: drawdown `>= -0.10`, `[-0.20, -0.10)`, `[-0.40, -0.20)`, `< -0.40`; Expected Shortfall `<= 0.01`, `(0.01, 0.02]`, `(0.02, 0.04]`, `> 0.04`; skewness `>= -0.50`, `[-1.00, -0.50)`, `[-2.00, -1.00)`, `< -2.00`; downside capture `<= 0.75`, `(0.75, 1.00]`, `(1.00, 1.25]`, `> 1.25`; recovery duration `<= 63`, `64-126`, `127-252`, `> 252` trading sessions. Missing required components make the composite unavailable while preserving raw available values.

Scope continued: Emit a complete Selection-owned `MetricEvidenceManifest` for filters including exchange, declared or observed monthly/annual payout, positive day/month/year ratios, return skewness, log-price slope, Expected Shortfall, maximum drawdown, recovery duration, NAV erosion, close-price path type, NAV path type, total-return type, downside capture, and risk type. Update then calls Selection's public finalization service; it never evaluates predicates itself. Only final members continue to pair and portfolio work.

Acceptance: Formula fixtures cover every exact classification boundary, split events without false decline, distributing assets whose close erodes while adjusted-close total return grows, true and missing NAV, NAV distributions, steady and volatile growth, sideways and negative returns, every risk component band, worst-band aggregation, completed and censored recovery, unavailable components, and a candidate gaining while its benchmark falls. Tests prove exact common-date downside capture, minimum observations, benchmark changes, every conjunctive field, evidence validation, final member ordering, threshold changes reusing raw artifacts, and Selection rather than Update owning predicate outcomes.

Determinism: Raw metric keys remain independent of filter and classification thresholds. Classification keys include raw artifact ids and full classification-profile id; benchmark-relative keys also include candidate and benchmark ids, both input versions, exact common-date-set hash, as-of date, and algorithm version. Evidence, labels, and final membership are independent of row order, CLI predicate order, locale, and scheduling.

Idempotency: Re-evaluating identical candidates, inputs, benchmark, and profiles reuses raw, benchmark-relative, classification, evidence, and final-membership artifacts. Ordinary filter-threshold changes reapply Selection predicates without recomputing unchanged raw metrics; profile or benchmark changes invalidate only dependent labels and evidence.

### PR51. Update Selection Calendar And Comparable Metric Cache

Branch: `feat/update-selection-calendar`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 comparable portfolio inputs.

Depends on: PR50.

Scope: Add an Update-owned `SelectionCalendar` contract deriving the exact common adjusted-close return-date intersection for a ready final membership and date policy, plus `calendar_id` from ordered dates and policy version. Build aligned long-format return matrices only for final members. Add comparable asset, covariance, and correlation artifacts keyed by listing or sorted pair, exact calendar id, and metric spec. Keep these separate from pairwise-intersection statistics: pair metrics may support similarity search, but portfolio covariance can be reused only when every member uses the identical Selection calendar. Record explicit empty, insufficient-history, and scale-limit outcomes instead of plausible zeros.

Acceptance: Tests prove every matrix member has exactly the same ordered dates, covariance and correlation use only that calendar, equivalent final memberships reuse calendar-scoped artifacts, and adding a short-history member changes the calendar and invalidates only calendar-dependent outputs. Fixtures cover dates appended by all members, one-sided dates, backfills, empty intersections, minimum-history failures, covariance symmetry, stable ordering, and a pairwise value that must not be reused for a different Selection calendar.

Determinism: Calendar ids, aligned row order, counts, comparable keys, matrix rows, covariance rows, and diagnostics are stable for the same final membership, input versions, and date policy. Set iteration, filesystem discovery, and worker scheduling cannot affect them.

Idempotency: Rebuilding an unchanged calendar and comparable metrics reuses immutable artifacts. A changed calendar creates a new version without mutating pairwise cache artifacts, prior calendars, or prior Selection analyses.

### PR52. Update Incremental Pair Metric Cache

Branch: `feat/update-pair-metric-cache`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 reusable final-member pair metrics.

Depends on: PR51.

Scope: Add Update's lazy Pair Metric Cache for pairs requested by the ready final membership. Derive `pair_id` from sorted distinct listing ids so symmetric and same-listing pairs are never computed twice. Persist exact pairwise common-date metadata and mergeable online state for sample covariance, incremental Pearson, and approximate online Spearman, including left and right input versions, metric-spec hash, observation count, first and last common dates, and common-date-set hash. Update only newly common observations for verified append-only deltas; rebuild affected pair state for historical corrections, deletions, or incompatible date sets. Bucket artifacts deterministically and preserve sparse threshold and top-k edge modes with explicit maximum-pair and memory guards.

Acceptance: For final Selection A `{A,B,C}` and B `{B,C,D}`, tests prove pair B/C is reused, only missing D pairs are new, and each unordered pair executes once per key. Tests cover one-sided appended dates, newly common dates, no-common-date deltas, backfills, corrections, same-ISIN cross-listings, empty intersections, sparse limits, pair-limit failures, cache corruption, concurrent requests, and prohibition of candidate-only or filtered-out pair work.

Determinism: Pair identity, orientation, bucket assignment, common-date order, online state, edge order, and cache decisions are stable across Selection order, process count, input row order, and worker scheduling. Approximate Spearman records an explicit algorithm and sketch version.

Idempotency: Re-running overlapping Updates with unchanged final memberships references the same pair artifacts without symmetric duplicates or recomputation. Append-only runs consume each newly common observation once; corrections rebuild only affected pair keys.

### PR53. Update Evaluation Profiles And Selection Analysis Manifests

Branch: `feat/update-evaluation-profiles`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 current-Selection analytical outputs.

Depends on: PR52.

Scope: Add versioned Update metric profiles, starting with `portfolio-full-v1`, that enumerate required asset screening, classification, benchmark-relative, pairwise, comparable, portfolio, frontier, optimizer, tail-risk, rebalance, and backtest outputs plus scale limits. Adapt existing Evaluation and Portfolio functions behind Update ports so they consume only the ready final membership and its exact Selection calendar. Write immutable Selection analysis manifests referencing shared artifacts rather than copying them. Derive `analysis_id` from selection and final membership ids, pinned market-data versions, benchmark, classification and metric profiles, calendar id, optimizer settings, date settings, and constraints. Never scan all catalog Gold data or call Refresh providers.

Acceptance: Tests produce or explicitly disable Sharpe, Sortino, Expected Shortfall, screening classifications, covariance and correlation modes, equal weight, minimum variance, risk parity, maximum diversification, efficient frontier, drawdown, tail risk, rebalance, and walk-forward outputs. Overlapping Selections report deterministic cache hits and execute each shared key once. Empty, insufficient, oversized, stale, paused, and failed Selections receive actionable status and no misleading portfolio output.

Determinism: Profile expansion, optimizer inputs, analysis ids, output ordering, diagnostics, and manifests depend only on pinned immutable inputs and versioned settings. Running one Selection alone or beside another yields the same artifact identities and analytical rows.

Idempotency: Re-running the same final membership and profile resolves to the same analysis manifest without recomputation. Partial failures resume missing outputs and cannot mutate completed artifacts or prior analyses.

### PR54. Update Service, Standalone CLI, And Atomic Publication

Branch: `feat/update-cli`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 operable Update module.

Depends on: PR53.

Scope: Implement `founder.update.service` and the standalone `founder-update` CLI with `plan`, `run`, and `status`; register equivalent `founder update` routing through the same module-owned parser. By default, `run` resolves exactly the current Selection, pins its candidate and current Refresh snapshot, computes or reuses candidate asset and benchmark evidence, invokes Selection finalization, computes pair/calendar/analysis outputs only for ready final members, and atomically publishes the Update result. Support explicit `--selection`, `--as-of`, `--metric-profile`, `--classification-profile`, `--concurrency`, `--resume`, `--dry-run`, `--run-id`, and `--debug`. Update must not invoke Refresh, make provider calls, mutate the current Selection definition, or update every saved Selection implicitly.

Scope continued: Write resumable run manifests with pinned inputs, plan id, cache hits, misses, deltas, rebuilds, blocked keys, candidate and final counts, availability reasons, scale diagnostics, output refs, and redacted failures. Acquire the Update and per-key locks defined in PR44. On publication, compare-and-swap against both the pinned current Selection candidate and pinned current Refresh snapshot; mark superseded work `stale_not_published` while retaining reusable immutable artifacts. Expose machine-readable exit status for no current Selection, pending data, empty final membership, stale run, partial failure, and success.

Acceptance: Dedicated CLI and service tests cover every command, option, default, JSON result, `--debug`, no-current-Selection failure, catalog-only and metric-dependent Selections, dry-run, cache reuse, append deltas, corrections, benchmark requirements, finalization, empty membership, lock contention, partial failure, resume, stale publication, and standalone versus umbrella equivalence. An end-to-end mocked flow proves Update computes metrics only for the current Selection candidate set, then pair and portfolio metrics only for its final members, without network calls or artifacts for unrelated catalog ISINs or saved Selections.

Determinism: Standalone and umbrella invocations produce the same typed request, plan, artifacts, final membership, analysis, and domain JSON for identical pinned inputs. Run timestamps, log lines, and worker completion order cannot affect identities or values.

Idempotency: Repeating `founder-update run` with unchanged current Selection and Refresh snapshot performs no duplicate calculation or pointer change. Resume executes incomplete keys only; concurrent or stale runs cannot overwrite newer Selection or Update state.

### PR55. Three-Module Cutover, Legacy Migration, And Documentation

Branch: `refactor/three-module-cutover`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/53.

Priority: P0 production cutover.

Depends on: PR54.

Scope: Make `founder refresh`, `founder selection`, and `founder update` the canonical operational surface and keep `founder-refresh`, `founder-selection`, and `founder-update` equivalent. Move old `search`, `bronze`, `silver`, `gold`, `evaluate`, and all-in-one `refresh` behavior under documented compatibility adapters for one migration window; no canonical command may invoke another domain module implicitly. Add a deterministic importer that maps current Search candidates, approved universe pointers, Bronze/Silver quotes, and reusable Gold artifacts into Refresh snapshots, one initial Selection, and Update cache references without redownload or data loss. Extend architecture checks to enforce package ownership, public-contract imports, CLI delegation, no network in Selection or Update, and no metric computation in Refresh or Selection.

Scope continued: Update README, ARCHITECTURE, lake contracts, DECISIONS, RISKS, TIMELINE, operations, cron examples, recovery procedures, and deprecation notes. Document the canonical sequence: `founder refresh run` gets all provider-visible ISINs and updates all eligible market data; `founder selection create ...` and `founder selection use ...` define and activate criteria; `founder update run` computes metrics for the current Selection only. Document snapshot pinning, current pointers, availability states, benchmarks, cache reuse, rollback, and how to reproduce a historical Update with explicit ids.

Acceptance: A full mocked integration test runs the three commands as separate processes and proves Refresh is global and Selection-independent, Selection is network-free and metric-free, and Update is current-Selection-scoped. It filters by exchange, payout frequency, positive periods, skewness, price slope, Expected Shortfall, drawdown, recovery, NAV erosion, close/NAV/total-return types, downside capture, and risk type; overlapping Selections reuse artifacts; unrelated ISINs receive no metrics. Migration preserves existing local data and yields deterministic identities. Compatibility, architecture, lock, partial-failure, restart, stale-pointer, and documentation tests pass.

Determinism: The same provider content, Refresh snapshot, Selection definition, candidate, benchmark, profiles, and Update settings produce the same memberships, plans, artifacts, analyses, migration mapping, and logical CLI results before and after restart. Compatibility warnings and deprecation dates are versioned.

Idempotency: Repeating migration or the full Refresh-Selection-Update cycle with unchanged inputs creates no duplicate snapshots, memberships, metrics, analyses, or pointer changes. A resumed command executes only its own module's incomplete work and never triggers hidden work in another module.

### Series Completion Gate

Final branch: `refactor/three-module-cutover`.

Squash rule: The final PR title and squash commit subject must use `type(optional-scope): subject`.

Required main merge gate: `merge-gate` must pass Ruff lint and format, architecture/import-boundary checks, Pyright strict, Pytest with coverage of at least 95%, and schema validation. The series remains incomplete while any stacked PR is unmerged or the final gate is not green.

## Production Portfolio Product PR Stack

Priority policy: This stack translates `GOALS.md` into production portfolio decision-support work. Each PR must be stacked on the previous PR until merged, must keep Refresh global, Selection deterministic and side-effect-free, and Update scoped to the current Selection. Production-facing outputs must be labeled unavailable or baseline until their data quality, return semantics, risk model diagnostics, constraints, walk-forward evidence, costs, and explanation artifacts are present. Every PR must preserve immutable input identities and avoid hidden network calls outside Refresh.

### PR56. Return Semantics And Data-Quality Gate

Branch: `fix/production-return-quality-gate`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/83.

Priority: P0 correctness foundation.

Depends on: PR55.

Scope: Make return type explicit in every affected contract and metric artifact; separate simple-return wealth simulation from log-return statistical calculations; reject, quarantine, or mark invalid prices instead of converting them to zero returns; add minimum-history, stale-price, duplicate-row, unexplained-gap, and quote-coverage checks before portfolio analysis can be marked production-eligible.

Acceptance: Tests cover zero, negative, missing, stale, duplicate, and corrected prices; simple wealth compounding; log-return metrics; closed-period denominators; minimum observation thresholds of 252, 504, and 756 daily observations; explicit unavailable reasons; and prevention of production-candidate output when quality gates fail.

Determinism: Quality decisions, return rows, unavailable reasons, and production-eligibility flags derive only from pinned market-data versions, explicit date windows, and versioned policy thresholds.

Idempotency: Re-running quality checks and return builds with unchanged inputs reuses or rewrites the same artifacts without duplicate rows, pointer churn, or changes to Refresh and Selection state.

### PR57. Instrument-Level Rebalancing Drift And Cost Basis

Branch: `fix/rebalance-instrument-drift`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/85.

Priority: P0 backtest correctness.

Depends on: PR56.

Scope: Correct rebalance simulation so each instrument drifts from its own simple return, not the portfolio return. Add explicit pre-trade value, pre-trade weight, target value, trade value, turnover, cash remainder, and post-cost portfolio value fields. Keep existing deterministic baseline schedules while making monthly, quarterly, annual, threshold, and hybrid rules use the same instrument-level engine.

Acceptance: Tests cover multi-asset drift, no-trade periods, threshold triggers, partial periods, cash remainder, transaction-cost application, changing target weights, and equality between a one-period manual spreadsheet fixture and persisted rows.

Determinism: Drift rows and rebalance events depend only on pinned aligned simple returns, prior weights, schedule policy, cost policy, and target-weight artifact ids.

Idempotency: Re-running the same rebalance id with unchanged inputs produces the same event ids, portfolio values, costs, weights, and metrics without appending duplicates.

### PR58. Risk Model Package And Covariance Diagnostics

Branch: `feat/risk-model-diagnostics`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/89.

Priority: P0/P1 risk-model foundation.

Depends on: PR57.

Scope: Introduce `founder.risk_model` with sample covariance, Ledoit-Wolf shrinkage covariance, EWMA covariance, rolling and expanding estimation windows, and structured diagnostics for estimation period, observation count, missing pair count, positive-semidefinite status, condition number or stability category, shrinkage intensity, missing-observation handling, and base return frequency.

Acceptance: Tests cover sample covariance parity with current baseline, Ledoit-Wolf shrinkage on small and highly correlated fixtures, EWMA decay behavior, rolling and expanding windows, PSD detection, condition-number categories, insufficient common history, and deterministic diagnostic rows.

Determinism: Risk-model artifact ids include membership id, calendar id, return type, estimator, estimator parameters, window policy, and algorithm version; worker order and filesystem order cannot affect matrices or diagnostics.

Idempotency: Recomputing unchanged risk models resolves to the same covariance, correlation, and diagnostic artifacts and does not mutate prior model versions.

### PR59. Production Numerical Solver Boundary

Branch: `feat/optimizer-solver-boundary`.

Git status: addressed (no dedicated PR under this branch name). See note below.

Priority: P0 optimizer foundation.

Depends on: PR58.

Status note: The stop-the-line "Mandatory Amendments To PR59" in `docs/backlog/00-critical-correctness-priority-queue.md` were implemented and merged first, ahead of this canonical entry, via `fix/solver-boundary-no-silent-equal-weight-fallback` (https://github.com/SergejSchweizer/founder/pull/99): `optimize_portfolio` gained an explicit `mode` (`production`/`baseline`), `production` mode rejects `candidate_limit_exceeded` instead of silently substituting Equal Weight, and diagnostics record `requested_method`/`actual_method`/`solver_name`/`solver_version`/`solver_status`/`convergence_status`/`constraint_residuals`/`bound_activity`/`iteration_count`/`numeric_tolerances`/`risk_model_id`/`fallback_used`/`fallback_reason`/`production_eligible`. PR60 (`feat/production-risk-optimizers`, https://github.com/SergejSchweizer/founder/pull/101) then gave `minimum_variance` and `risk_parity`/`equal_risk_contribution` a real solver-backed production path (`founder.portfolio_parts.solvers`, projected gradient descent), removing the grid-search fallback entirely for those two objectives in production mode. Deliberate deviation from this entry's literal scope: no numerical optimization dependency (e.g. scipy) was added -- the repository intentionally has zero numerical runtime dependencies (pyarrow only; see `founder.risk_model`'s hand-implemented Jacobi eigenvalue solver), so the solver boundary is a hand-implemented pure-Python projected gradient descent instead. `maximum_sharpe`, `target_return_minimum_variance`, and `maximum_diversification` remain grid-only comparison methods in production mode (consistent with PR61's "keep as comparison methods unless production criteria are met").

Scope: Add a numerical optimization dependency and a stable solver boundary for constrained convex portfolio problems. Separate deterministic baseline optimizers from production solver-backed optimizers, expose convergence status, objective value, constraint residuals, bound activity, iteration count, solver settings, and infeasibility reasons. Remove large-universe grid-search fallback behavior from production-labeled paths.

Acceptance: Tests cover feasible and infeasible quadratic programs, long-only/full-investment/min/max-weight constraints, concentration limits, deterministic tie-breaking, solver failure reporting, no-grid fallback in production mode, and unchanged baseline outputs where explicitly requested.

Determinism: Solver requests canonicalize asset order, constraints, bounds, risk-model ids, expected-return ids, and settings; diagnostics record tolerances so repeated runs are stable within explicit numeric tolerances.

Idempotency: Re-running the same solver request writes the same target-weight and diagnostic artifacts or the same explicit failure artifact without partial portfolio outputs.

### PR60. Production Minimum Variance And Equal Risk Contribution

Branch: `feat/production-risk-optimizers`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/101.

Priority: P1 robust portfolio construction.

Depends on: PR59.

Scope: Implement solver-backed constrained Minimum Variance and Equal Risk Contribution over shrinkage or EWMA risk models. Persist target weights, marginal risk contribution, absolute risk contribution, percentage risk contribution, objective residuals, constraint diagnostics, and production-readiness labels.

Acceptance: Tests cover diagonal covariance, correlated ETF clusters, near-singular covariance, allocation caps, issuer or group caps when supplied, zero-variance assets, equal-risk-budget residuals, convergence failure, and comparison against Equal Weight and Inverse Volatility baselines.

Determinism: Optimizer outputs depend only on pinned final membership, risk-model artifact, constraints, solver settings, and objective version.

Idempotency: Re-running unchanged objectives produces the same weights, diagnostics, and baseline comparisons without recomputing unchanged risk-model artifacts.

### PR61. True HRP And Minimum CVaR Optimizers

Branch: `feat/hrp-cvar-production-optimizers`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/104 (True HRP) and https://github.com/SergejSchweizer/founder/pull/109 (Minimum CVaR).

Priority: P1/P2 robust and tail-risk construction.

Depends on: PR60.

Progress note: the True HRP half of this scope (real hierarchical clustering, correlation-distance matrix, quasi-diagonal ordering, recursive bisection with inverse-variance cluster weights, linkage/dendrogram persistence, and a clearly labeled `hierarchical_risk_parity_baseline` for the retired naive split) is merged: https://github.com/SergejSchweizer/founder/pull/104. Historical Minimum CVaR optimization (Rockafellar-Uryasev reformulation, pure-Python alternating projected-subgradient solver, standalone `minimum_cvar_weights`/`write_minimum_cvar_portfolio` entry points) is also merged: https://github.com/SergejSchweizer/founder/pull/109. Turnover-aware CVaR constraints and issuer/group concentration caps beyond the existing per-asset `max_weight` bound remain out of scope and are not tracked as a follow-up PR here.

Scope: Replace temporary HRP behavior with true hierarchical clustering, correlation-distance matrix, quasi-diagonal ordering, and recursive bisection by cluster variance. Add historical Minimum CVaR optimization under long-only, concentration, and turnover-aware constraints. Keep Maximum Diversification and Maximum Sharpe as comparison methods unless their inputs satisfy production criteria.

Acceptance: Tests cover clustering tie-breaks, highly correlated groups, recursive bisection allocations, cluster variance, CVaR loss scenarios, repeated tail losses, confidence-level validation, long-only bounds, infeasible CVaR constraints, and explicit baseline versus production labels.

Determinism: HRP ordering, cluster ids, CVaR scenario ids, tail sets, and weights derive from canonical asset order, pinned returns, risk-model ids, objective settings, and algorithm versions.

Idempotency: Re-running unchanged HRP or CVaR requests reuses existing matrices and writes the same cluster, tail-risk, diagnostic, and target-weight artifacts.

### PR62A. Jurisdiction-Neutral Tax And Cost Contracts

Branch: `feat/tax-cost-neutral-contracts`.

Git status: not started. PR: TBD.

Priority: P1/P2 for the income product; blocks PR62B onward.

Depends on: PR61.

Scope: Create `founder.tax`, `founder.costs`, and `founder.cashflow` public contracts, a `CountryTaxAdapter` protocol and `CountryTaxRegistry` keyed by ISO country code with every EU member state registered as an explicit `unsupported` placeholder, a `CostBasisStrategy` protocol, composable broker/venue/execution/FX/jurisdiction-tax/recurring cost-component contracts and a `CostProfileRegistry`, a neutral `CashFlowResult` contract, and the shared `exact`/`verified_estimate`/`user_supplied_estimate`/`unavailable`/`unsupported` calculation-status vocabulary. No concrete tax rate, allowance, threshold, or broker fee may be hard-coded in core modules; see `docs/backlog/eu-tax-cost-architecture.md`.

Acceptance: Tests cover contract field validation, the EU-27 country registry resolving every known code as unsupported by default, registering and resolving a stub adapter, rejecting registration for an unknown country code, the cost-profile registry's kind validation and unsupported-by-default resolution, a cost-basis strategy implementation satisfying the protocol end to end, and the cash-flow result's reinvested/withdrawn reconciliation and status validation.

Determinism: Contracts carry explicit rule-set/profile references, validity windows, and calculation statuses so no result depends on wall-clock time or unpinned defaults.

Idempotency: These are contracts and registries only; there is no persisted lake artifact to reconcile in this PR.

### PR62B. Austria Tax And Broker Reference Adapter

Branch: `feat/tax-austria-adapter`.

Git status: not started. PR: TBD.

Priority: P1/P2 for the income product.

Depends on: PR62A.

Scope: Implement Austria as the first verified `CountryTaxAdapter`, covering private-investor capital-income events, fund-tax facts (OeKB-derived where available), tax-year state, supported loss-offset behavior, Austrian cost-basis behavior, and an initial Flatex Austria cost profile. All concrete rates, thresholds, and fee schedules must be sourced, dated, versioned, and reviewed (`TaxRuleSetRef.source_refs`/`reviewed_at`) rather than invented; unsourced figures must resolve to `unavailable`/`unsupported`, never a plausible estimate.

Acceptance: Tests cover Austria-specific event classification, distribution/deemed-income taxation, loss-offset and tax-year-close behavior, an Austria-versus-unsupported-country comparison producing different results from the same market events, and a Flatex Austria cost-profile estimate.

Determinism: Austria rule-set and cost-profile references are versioned and effective-dated; historical simulations resolve the version valid at the simulated event date.

Idempotency: Re-running unchanged Austria tax/cost calculations reuses the same rule-set/profile references and produces the same results.

### PR62C. Historical Rule Resolution And Tax-Year Engine

Branch: `feat/tax-rule-resolution-engine`.

Git status: not started. PR: TBD.

Priority: P1/P2 for the income product.

Depends on: PR62B.

Scope: Add effective-dated rule lookup across historical rule versions, tax-year state (income/gains/losses by category, allowances used, foreign-tax credits used, carry-forward state), loss offsetting, foreign-tax-credit capping, and deterministic tax-year close. Walk-forward and rebalance simulations must resolve the rule version valid at each simulated event date, never today's rule set.

Acceptance: Tests prove no future rule version is used before its `valid_from` date, a rule change produces different results across the effective date, loss-offset state does not leak between tax years, and foreign tax credits are capped per the selected country adapter.

Determinism: Tax-year state transitions are a pure function of ordered tax events, the resolved rule-set version, and prior carry-forward state.

Idempotency: Re-running an unchanged event sequence for a closed tax year reproduces the same tax-year-close result.

### PR62D. Broker, Venue, FX, And Transaction-Cost Engine

Branch: `feat/broker-venue-cost-engine`.

Git status: not started. PR: TBD.

Priority: P1/P2 for the income product.

Depends on: PR62A.

Scope: Implement composable broker, venue, execution/slippage, FX, recurring-account, and jurisdiction-transaction-tax cost profiles registered through `CostProfileRegistry`, and compose them into a `CostBreakdown` per trade. Replace any remaining global transaction-cost-rate assumption in production paths with this engine.

Acceptance: Tests cover independent broker/venue/execution/FX/recurring/transaction-tax profile composition, the same tax residence producing different costs under different brokers, the same broker producing different venue/execution costs across venues, and versioned/effective-dated profile resolution for historical trade dates.

Determinism: Cost-profile references are versioned and effective-dated; historical simulations resolve the profile valid on the simulated trade date.

Idempotency: Re-running an unchanged trade-cost request reuses the same profile references and produces the same `CostBreakdown`.

### PR62E. Net Cash Flow And Sustainability Metrics

Branch: `feat/cashflow-sustainability-metrics`.

Git status: not started. PR: TBD.

Priority: P1/P2 for the income product; required before PR63 onward.

Depends on: PR62C, PR62D.

Scope: Populate the `founder.cashflow` orchestration layer to produce gross, after-tax, and after-cost cash flows using resolved tax and cost results; natural, synthetic, hybrid, and full-reinvestment income strategies; stable monthly net-spendable-income metrics; nominal and real capital preservation; tax drag; cost drag; and sustainable-withdrawal warnings. Gross, after-tax, and after-cost series must reconcile exactly and remain separately visible.

Acceptance: Tests cover gross/after-tax/after-cost reconciliation, natural-versus-synthetic-versus-hybrid income comparison, tax-drag and cost-drag calculation, NAV erosion and real-capital-change reporting, and sustainable-withdrawal warning thresholds.

Determinism: Cash-flow artifacts key on portfolio holdings, market/trade events, resolved tax-year state, cost-profile references, income policy, and algorithm version.

Idempotency: Re-running unchanged cash-flow requests reuses existing tax/cost results and produces the same cash-flow and sustainability artifacts.

### PR62F. EU Adapter Expansion Framework

Branch: `feat/eu-adapter-expansion-framework`.

Git status: not started. PR: TBD.

Priority: P2/P3 EU rollout.

Depends on: PR62E.

Scope: Add country-adapter templates, source-reference and legal-review metadata requirements, adapter conformance tests, a country-readiness report (adapter status, supported investor/account/instrument types, fund-tax/loss-offset/cost-basis/broker-withholding status, last legal review, known limitations), and documentation for adding further EU jurisdictions without changing portfolio core code.

Acceptance: Tests cover conformance-test enforcement for a new adapter template, readiness-report field completeness, and that an unsupported country never appears as supported in the readiness report.

Determinism: Readiness-report rows are a pure function of registered adapters' declared metadata.

Idempotency: Re-running the readiness report with unchanged adapter registrations produces the same rows.

Series note: PR62A-PR62F replace the original single "PR62. Income And Distribution Quality Metrics" entry; distribution-quality metrics that do not require tax/cost integration are absorbed into PR62E's income-strategy comparison and monthly-income metrics. PR63 depends on PR62E, not on a standalone income-metrics PR.

### PR63. Portfolio Profiles, Constraints, And Ensemble Candidate

Branch: `feat/profile-constraints-ensemble`.

Git status: not started. PR: TBD.

Priority: P2 recommendation foundation.

Depends on: PR62E.

Scope: Add versioned Defensive, Balanced, Income, and Growth profile contracts with explicit objective sets, constraints, risk limits, income requirements, and production eligibility rules. Build the initial Balanced ensemble from True HRP, Equal Risk Contribution, and shrinkage Minimum Variance using per-asset median weights, normalization, and final constraint projection. Add Income-profile constraints for sustainable net income, NAV erosion, CVaR, concentration, and turnover.

Acceptance: Tests cover profile expansion, constraint validation, group and issuer limits when metadata is available, minimum and maximum weights, minimum income, maximum drawdown/CVaR/turnover, ensemble median aggregation, final projection, infeasible profile reporting, and comparison against Equal Weight and Inverse Volatility.

Determinism: Profile candidate ids include profile version, final membership id, risk-model ids, income artifact ids, optimizer ids, constraints, and projection settings.

Idempotency: Re-running a profile with unchanged inputs reuses component optimizer outputs and writes the same ensemble and constraint-diagnostic artifacts.

Progress note: `founder.profiles` (`ProfileContract`, `ProfileRiskLimits`, `defensive_profile`/`balanced_profile`/`income_profile`/`growth_profile`, `build_balanced_ensemble_weights`, `evaluate_profile_candidate`, `write_profile_candidate`) and `founder.portfolio.shrinkage_minimum_variance_weights` (wires `founder.risk_model`'s Ledoit-Wolf estimator into PR60's solver) are implemented and merged as an isolated development step per the stop-the-line policy: the Balanced ensemble, Defensive (shrinkage Minimum Variance), Growth (Equal Risk Contribution), and Income (Minimum CVaR) weight computations are real and production-eligible today, but the Income profile's `min_net_income`/`max_nav_erosion` risk limits always report `unavailable` -- they require PR62E's after-tax cash-flow stack, which remains open, so no income-based production claim is made. Group and issuer concentration limits remain out of scope until group/issuer metadata is plumbed through the lake. This progress does not change the "Depends on: PR62E" gate for the profile's full production eligibility.

### PR64. Walk-Forward Model Comparison Scorecard

Branch: `feat/walk-forward-scorecard`.

Git status: not started. PR: TBD.

Priority: P3 validation and selection.

Depends on: PR63.

Scope: Expand walk-forward testing across profiles, optimizers, and risk estimators with rolling and expanding windows, monthly and quarterly re-estimation, realistic rebalance rules, costs, turnover, and weight stability. Add a common scorecard for out-of-sample return, volatility, Sharpe, Sortino, CVaR, drawdown, recovery time, concentration, income quality, robustness across windows, and adverse-period behavior.

Acceptance: Tests cover information cutoffs per split, rolling and expanding windows, insufficient training windows, cost-adjusted returns, turnover, weight stability, median and adverse quantiles, deterministic ranking, and prevention of highest in-sample return as the sole recommendation criterion.

Determinism: Split ids, scorecard rows, rankings, and model-comparison ids depend only on pinned candidates, windows, rebalance policy, costs, risk estimators, objective ids, and scorecard version.

Idempotency: Re-running unchanged model comparison reuses completed split artifacts and produces the same scorecard, rank order, and availability reasons.

Progress note: `founder.scorecard` (`ScorecardCandidate`, `build_model_comparison_scorecard`) is implemented and merged, reusing the existing `founder.evaluation.build_walk_forward_backtest` engine (which already covers rolling/expanding windows, information cutoffs, insufficient-window rejection, and cost-adjusted turnover) rather than re-implementing it. It runs multiple candidate objectives on identical pinned windows/rebalance policy/costs and reports one deterministically ranked scorecard row per candidate: median and adverse-quantile out-of-sample return, median Sharpe/Sortino, historical CVaR, whole-period max drawdown and recovery duration, concentration, weight stability (weight variance across splits), and a deterministic `model_comparison_id`. Ranking uses median out-of-sample Sharpe across completed splits (never a single split's or in-sample return) with a candidate-id tie-break; a candidate whose request is infeasible is reported `status="blocked"` rather than crashing the comparison. Income quality always reports `unavailable` pending PR62E. Monthly/quarterly re-estimation cadence beyond the existing rolling/expanding window modes is not separately modeled and remains a documented follow-up gap.

### PR65. Stress, Bootstrap, And Sensitivity Analysis

Branch: `feat/stress-bootstrap-sensitivity`.

Git status: not started. PR: TBD.

Priority: P3 robustness evidence.

Depends on: PR64.

Scope: Add historical stress periods, correlation-convergence stress, distribution-cut scenarios, block-bootstrap return scenarios, covariance and parameter perturbations, alternate training windows, and alternate rebalance schedules. Persist scenario definitions, scenario results, and sensitivity summaries for every recommended candidate and baseline.

Acceptance: Tests cover deterministic historical period selection, block bootstrap with seeded scenario ids, covariance perturbation bounds, distribution-cut shocks, correlation-convergence shocks, scenario drawdown/CVaR outputs, and stable sensitivity summaries.

Determinism: Scenario ids include scenario policy, seed, input artifact ids, candidate id, and algorithm version; random draws must be reproducible from persisted seeds.

Idempotency: Re-running unchanged scenario analysis resolves to the same scenario ids and results and resumes only missing scenarios after interruption.

Progress note: `founder.stress` is implemented and merged: `historical_stress_scenario` (replays the worst-drawdown window of a requested length detected deterministically within the caller's own data -- never a hardcoded or asserted crash date), `distribution_cut_scenario` (a multiplicative return shock on selected ISINs), `block_bootstrap_scenarios` (seeded contiguous-block resampling, no numpy/scipy), `correlation_convergence_scenario` and `covariance_perturbation_scenario` (covariance-only scenarios reporting a hand-implemented parametric Gaussian VaR/CVaR since they have no return series to replay), and `build_sensitivity_summary` (median/worst-case aggregation across scenario results for one candidate). Scenario ids are deterministic via `stable_contract_id`. Alternate training windows and rebalance schedules are already covered by the existing `founder.evaluation.build_walk_forward_backtest`/`founder.scorecard` rolling/expanding window support and are not re-implemented here. Scenario-result persistence to a dedicated lake dataset (rather than returning in-memory dataclasses/rows) remains a documented follow-up once a concrete caller (PR66's recommendation report) needs it.

### PR66. Explainable Recommendation Report

Branch: `feat/recommendation-explanation-report`.

Git status: not started. PR: TBD.

Priority: P3 user decision support.

Depends on: PR65.

Scope: Introduce `founder.recommendation` to compare eligible candidates and produce best defensive, diversified, income, total-return, ensemble, Equal Weight, and current-portfolio comparison outputs. Generate human-readable assumptions, inclusion and exclusion reasons, target weights, risk contributions, expected income, drawdown, tail risk, concentration, costs, turnover, data-quality warnings, model disadvantages, and production-candidate status.

Acceptance: Tests cover explanation completeness, excluded-instrument reasons, warning propagation, candidate disadvantages, scorecard traceability, deterministic Markdown/HTML-safe structured report data, no guaranteed-return language, and explicit user-approval boundary before trade preparation.

Determinism: Recommendation ids derive from scorecard, stress results, income artifacts, profile settings, current-position snapshot if supplied, and report template version.

Idempotency: Re-running unchanged recommendations produces the same structured report artifacts and does not alter optimizer, backtest, Selection, Refresh, or Update artifacts.

Progress note: `founder.recommendation` is implemented and merged: `build_candidate_report` explains one `founder.profiles.evaluate_profile_candidate` output (inclusion/exclusion reasons, constraint violations, concentration, turnover versus an optional current-position snapshot, disadvantages) with optional `founder.scorecard`/`founder.stress` traceability (`scorecard_rank`, `sensitivity_worst_drawdown`/`sensitivity_worst_cvar`); `build_recommendation_report` compares candidates into best-Defensive/best-Diversified/best-Income/best-Total-Return/best-Ensemble slots plus an Equal Weight baseline already embedded per candidate, with a deterministic `recommendation_id` and a fixed `NO_GUARANTEE_DISCLAIMER`; `render_recommendation_markdown` produces deterministic, HTML-escaped Markdown. `requires_user_approval` is always `True`. Income and broker-cost quality always report `unavailable` pending PR62E/PR62D, never an invented figure; this module never fabricates an excluded-instrument or data-quality-warning reason, it only propagates reasons supplied by the caller from an upstream gate. Risk contributions and per-scenario tail-risk/drawdown detail beyond the aggregated scorecard/sensitivity summaries are not separately recomputed in this report and remain a documented follow-up if a future consumer needs the full row-level detail.

### Series Completion Gate

Final branch: `feat/recommendation-explanation-report`.

Squash rule: Every PR title and final squash commit subject must use `type(optional-scope): subject`. The final PR must not be merged until all prior PR56-PR66 branches are merged or explicitly superseded in this backlog.

Required main merge gate: `merge-gate` must pass Ruff lint and format, architecture/import-boundary checks, Pyright strict, Pytest with at least 95% coverage, dataset schema-registry validation, and the production-candidate report tests added in this stack. The series remains incomplete while any production-candidate output can be generated without data-quality gates, consistent return semantics, risk-model diagnostics, solver diagnostics, baseline comparison, walk-forward evidence, costs, tail-risk/drawdown metrics, concentration/risk contributions, and explanation artifacts.

## Multivariate Statistics Module PR Stack

Priority policy: `multivariate_statistics` is the portfolio-level counterpart to `bivariate_statistics`. It must default to the latest ready `univariate_filter` membership, must never widen the universe implicitly, and must write portfolio analytics only for the selected ISIN listings. The module is an orchestration surface over existing Evaluation and Portfolio calculations first; production-grade optimizers, income objectives, recommendations, and trading outputs should be added by stacking on the Production Portfolio Product PR Stack instead of bloating the baseline PR.

### PR69. Multivariate Statistics Baseline Module And CLI

Branch: `feat/multivariate-statistics-baseline`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/79.

Priority: P0 selected-portfolio analytics entry point.

Depends on: PR55.

Scope: Add `founder.multivariate_statistics`, `founder multivariate-statistics`, and `run_multivariate_statistics_workflow`. Resolve the latest `univariate_filter` selection by default, filter Silver quotes to those selected listings, write selected Gold returns/correlation/covariance/features, build a selected return matrix and asset metrics, then run the currently available portfolio calculations: Equal Weight portfolio evaluation, deterministic Minimum Variance, Maximum Sharpe comparison, Risk Parity, HRP baseline, Maximum Diversification, efficient frontier, walk-forward backtest, rebalance simulation, and tail-risk evaluation. Add module locking and a JSON CLI summary.

Acceptance: CLI tests prove the command uses the latest `univariate_filter` manifest without a pointer, excludes unselected ISINs, writes selected return matrix rows, writes portfolio metrics, writes optimized weights, writes tail-risk rows, and writes walk-forward rows. Re-running the command with the same evaluation id replaces or validates the same artifacts without appending duplicate portfolio rows.

Determinism: Evaluation ids, portfolio ids, selected listing order, target-return grid, objective order, and output row ordering are explicit and stable. The command must not read unrelated Gold return files when constructing the selected return matrix.

Idempotency: Re-running unchanged selected quotes and selection membership with the same options produces the same Gold, Evaluation, and Portfolio rows; it must not mutate metadata, univariate statistics, bivariate statistics, or Refresh state.

### PR70. Multivariate Production Portfolio Adapter

Branch: `feat/multivariate-production-adapter`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/117.

Priority: P1 production stack integration.

Depends on: PR69 and PR63.

Scope: Teach `multivariate_statistics` to consume the production data-quality gate, risk-model diagnostics, production solver outputs, profile constraints, and ensemble candidate artifacts introduced by PR56 through PR63. Keep deterministic baseline objectives available behind explicit flags, but make production-candidate summaries require quality gates, solver diagnostics, risk contributions, and baseline comparisons.

Acceptance: Tests prove production mode refuses invalid prices, insufficient history, missing risk-model diagnostics, infeasible constraints, and missing baseline comparisons. Tests also prove Balanced profile output includes HRP, ERC, shrinkage Minimum Variance, and ensemble rows when the prerequisite artifacts exist.

Determinism: Production adapter ids include selection membership, quality policy, risk-model ids, optimizer ids, profile version, and constraint version.

Idempotency: Re-running production multivariate analysis with unchanged prerequisite artifacts reuses those artifacts and writes the same analysis summary without recomputing lower-level caches.

Progress note: `founder.multivariate_statistics.write_production_multivariate_statistics`/`ProductionMultivariateConfig` are implemented and merged. It refuses (raises `ValueError`) rather than falling back to a baseline when: the selection's Silver quote history fails `founder.return_quality.evaluate_quote_quality`'s production data-quality gate (invalid prices, insufficient history, stale prices, unexplained gaps); the aligned return matrix is empty; `founder.risk_model.estimate_risk_model`'s diagnostics are not `production_eligible`; a requested `founder.profiles` candidate is `infeasible`; or a candidate's baseline comparison is empty. It writes weight rows for every requested profile via `founder.profiles.write_profile_candidate`, and the Balanced profile's candidate already includes True HRP, Equal Risk Contribution, and shrinkage Minimum Variance ensemble rows via the existing `build_balanced_ensemble_weights` composition (no separate wiring needed). The deterministic `production_adapter_id` is derived from selection membership, the quality policy name, risk-model estimator/algorithm version, requested profile names, profile versions, and the constraint set. Existing `write_multivariate_statistics` (the deterministic baseline module) is unchanged and remains available; this is an additive production-mode entry point, not a replacement.

### PR71. Multivariate Income And Recommendation Outputs

Branch: `feat/multivariate-income-recommendations`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/118.

Priority: P2/P3 user-facing decision support.

Depends on: PR70 and PR66.

Scope: Extend `multivariate_statistics` to include income quality, sustainable income, NAV erosion, income efficiency, recommendation scorecards, explainable selection and exclusion reasons, candidate disadvantages, and production-candidate status for Defensive, Balanced, Income, and Growth profiles. Keep reports traceable to Selection, Update, and Portfolio artifacts rather than recomputing formulas locally.

Acceptance: Tests cover income profile output, unsupported-distribution warnings, NAV-erosion warnings, recommendation reason propagation, no guaranteed-return language, and deterministic structured report payloads for the selected membership.

Determinism: Recommendation summaries derive only from pinned income artifacts, model-comparison scorecards, stress results, profile settings, and report template versions.

Idempotency: Re-running unchanged income/recommendation multivariate analysis produces the same report artifacts and does not alter optimizer, backtest, Selection, Refresh, or Update artifacts.

Progress note: `founder.multivariate_statistics.write_multivariate_recommendation`/`MultivariateRecommendationConfig` are implemented and merged. It runs the PR70 production adapter first (enforcing every production gate and writing profile weight rows), then adds PR64 walk-forward scorecard traceability where a profile's underlying objective is scorecard-compatible (currently only Growth, via `equal_risk_contribution`; Defensive's shrinkage Minimum Variance, Income's Minimum CVaR, and Balanced's multi-objective ensemble are not single walk-forward-compatible objectives today, so their `scorecard_rank` reports `None` rather than a fabricated comparison) and PR65 stress/sensitivity summaries for every profile candidate, then compares all candidates via PR66's `founder.recommendation` into one deterministic report. Income quality, sustainable income, NAV erosion, and income efficiency always report `unavailable` pending PR62E, never an invented figure.

### PR72. Multivariate Trading And Monitoring Handoff

Branch: `feat/multivariate-trading-monitoring-handoff`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/119.

Priority: P4 end-user workflow handoff.

Depends on: PR71.

Scope: Add an optional `multivariate_statistics` handoff to current-position transition analysis, Flatex export, local project report generation, and monitoring statuses. The module may reference approved recommendation weights and transition outputs, but it must not decide broker execution or alter current positions.

Acceptance: Tests prove the handoff rejects unapproved recommendations by default, includes current-versus-target differences when current positions are supplied, links deterministic Flatex export paths, and emits monitoring-ready drift, risk, stale-data, distribution-cut, and NAV-erosion statuses.

Determinism: Handoff ids include recommendation id, current-position snapshot id, transition-plan id, monitoring policy id, and report template version.

Idempotency: Re-running unchanged handoff inputs produces the same references and local report status without duplicate trade rows, alerts, or pointer changes.

Progress note: `founder.multivariate_statistics.write_multivariate_trading_handoff`/`TradingHandoffConfig` are implemented and merged. It runs the PR71 recommendation report first, then rejects (raises `ValueError`) by default unless `approved_comparison_slot` (e.g. `"best_ensemble"`) is explicitly supplied and resolves to an included candidate -- this module never infers or decides approval on the user's behalf. When approved: it includes per-ISIN current-versus-target weight differences when `current_weights` is supplied; links a deterministic Flatex export (`paths.trading_flatex_export(evaluation_id, approved_candidate_id)`, reusing the existing `founder.trading.prepare_flatex_orders`/`write_flatex_orders`) when `current_prices` and a positive `portfolio_value` are supplied; and reports `drift_status` (from the transition-plan deltas versus `drift_threshold`), `risk_status` (the approved profile's `risk_limits.max_cvar` versus the PR65 sensitivity summary's worst-case CVaR), and `stale_data_status` (from `founder.return_quality.evaluate_quote_quality`). `distribution_cut_status`/`nav_erosion_status` always report `unavailable` pending PR62E, never an invented figure. The deterministic `handoff_id` derives from the recommendation id, approved candidate id, current-position snapshot, transition plan, monitoring policy id, and report template version. Local project report generation (a rendered document beyond the structured JSON payload) remains a documented follow-up gap.

### Series Completion Gate

Final branch: `feat/multivariate-trading-monitoring-handoff`.

Squash rule: Every PR title and final squash commit subject must use `type(optional-scope): subject`. The final PR must not be merged until PR69 through PR71 and their declared Production Portfolio Product dependencies are merged or explicitly superseded in this backlog.

Required main merge gate: `merge-gate` must pass Ruff lint and format, architecture/import-boundary checks, Pyright strict, Pytest with at least 95% coverage, dataset schema-registry validation, and selected-membership multivariate integration tests. The series remains incomplete while `multivariate_statistics` can include unselected ISINs, read unrelated Gold return files for selected portfolio matrices, or label deterministic baselines as production candidates without the required production evidence.

## Generic Statistics Cache PR Stack

Priority policy: Univariate, Bivariate, and Multivariate Statistics should treat Metadata Filter and Univariate Filter outputs as selection views over stable Gold artifacts. Listing-level and pair-level statistics belong in reusable canonical paths keyed by listing or ordered listing pair. Selection commands should compute only missing or stale deltas, then return the full requested selection from cached plus newly computed rows. Multivariate portfolio runs may remain selection-parameter scoped, but they must consume generic listing and pair caches and record enough selection identity to avoid recomputing unchanged portfolios.

### PR73. Generic Listing And Pair Statistics Cache

Branch: `feat/generic-statistics-cache`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/80.

Priority: P0 reusable Statistics cache baseline.

Depends on: PR69.

Scope: Make `write_univariate_statistics` and `write_bivariate_statistics` read existing Gold artifacts before computing. Reuse univariate rows when listing identity, confidence level, quote observation count, quote date bounds, and distribution-event state still match the input. Reuse bivariate rows when pair identity, common return date bounds, and common observation count still match the input. Return the full selected output as cached plus newly computed rows, and write only missing or stale deltas.

Acceptance: Tests prove re-running unchanged Univariate Statistics does not rewrite listing artifacts, expanding a Bivariate selection keeps already computed pair files unchanged, and only new pair files are written for newly introduced combinations.

Determinism: Cache hit checks use explicit listing keys, pair keys, date bounds, observation counts, and run parameters; no filesystem modification time is used to decide correctness.

Idempotency: Re-running unchanged Metadata Filter selections returns the same rows and leaves matching Gold listing and pair artifacts untouched.

### PR74. Selection Statistics Views

Branch: `feat/statistics-selection-views`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/120.

Priority: P1 generic retrieval by Metadata Filter selection.

Depends on: PR73.

Scope: Add explicit selection-view artifacts that materialize which cached univariate and bivariate rows belong to each Metadata Filter or Univariate Filter selection. Add read APIs and CLI summaries that can load a selection's statistics without recomputing when all referenced cache rows are present and fresh.

Acceptance: Tests prove any persisted Metadata Filter selection can retrieve its univariate rows and pair rows from generic Gold cache paths, missing cache rows are reported deterministically, and view regeneration is idempotent.

Determinism: Selection views are keyed by `selection_id`, source module, selected listing keys, statistic version, and parameter set.

Idempotency: Rebuilding an unchanged selection view produces byte-equivalent rows and does not rewrite canonical statistic rows.

Progress note: `founder.statistics_views` (`build_selection_statistics_view`, `write_selection_statistics_view`, `read_selection_statistics`) is implemented and merged. It never recomputes a missing row: `build_selection_statistics_view` checks the existing PR73 generic Gold caches (`paths.gold_univariate_statistics(exchange, isin)` per listing; the bucketed `paths.gold_bivariate_statistics_bucket(version, bucket)` cache for every unordered listing pair, using the exact `pair_key` format `founder.bivariate_statistics` writes) and reports `missing_univariate_listings`/`missing_bivariate_pairs` deterministically rather than substituting a partial or fabricated result. `write_selection_statistics_view` persists the view to `paths.selection_statistics_view(source_module, selection_id)` (idempotent: an unchanged selection produces a byte-equivalent view). `read_selection_statistics` loads a selection's cached univariate/bivariate rows without recomputing, raising `ValueError` naming exactly what is missing when the cache is incomplete. A CLI summary command is not yet wired (a documented follow-up); the library API is the complete, tested surface for this PR.

### PR75. Multivariate Selection Cache Consumption

Branch: `feat/multivariate-selection-cache-consumption`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/121.

Priority: P1 portfolio delta reduction.

Depends on: PR74.

Scope: Teach `multivariate_statistics` to consume selection statistics views for returns, asset metrics, covariance/correlation inputs, and pair diagnostics before running portfolio-level calculations. Persist portfolio run identity from selected listing keys plus optimizer, evaluation, rebalance, tail-risk, and frontier parameters so unchanged portfolio runs can be reused safely.

Acceptance: Tests prove unchanged multivariate selection runs reuse generic inputs and portfolio artifacts, changed selections compute only the new listing/pair input deltas before portfolio recomputation, and portfolio outputs never include unselected listings.

Determinism: Portfolio cache ids are derived from sorted selected listing keys, input statistic versions, and explicit portfolio parameters.

Idempotency: Re-running an unchanged multivariate selection leaves generic input caches and portfolio outputs unchanged while returning the same JSON summary.

Implementation note: this PR adds explicit cache consumption to `founder.multivariate_statistics` behind
`MultivariateStatisticsConfig.use_selection_statistics_cache` and CLI flag `--use-selection-statistics-cache`.
The cache mode requires the resolved `selection_id`, writes only missing/stale selected listing return and
univariate rows, updates bucketed bivariate statistics through the PR73 delta writer, validates the PR74
Selection Statistics View, reconstructs selected covariance/correlation inputs from the cached univariate and
bivariate rows, and derives a deterministic `portfolio_run_id` from selection identity plus portfolio parameters.
If that run id already has a complete cache manifest and all referenced artifacts still exist, the command returns
the existing summary with `cache_status=portfolio_reused` instead of rewriting portfolio-level artifacts.

### Series Completion Gate

Final branch: `feat/multivariate-selection-cache-consumption`.

Squash rule: Every PR title and final squash commit subject must use `type(optional-scope): subject`. The final PR must not be merged until PR73 and PR74 are merged or explicitly superseded in this backlog.

Required main merge gate: `merge-gate` must pass Ruff lint and format, architecture/import-boundary checks, Pyright strict, Pytest with at least 95% coverage, dataset schema-registry validation, and cache-hit/cache-miss integration tests for Metadata Filter selections.

## Hosted Product And Goal Traceability PR Stack

Priority policy: This stack translates the remaining product and hosted-access goals in `GOALS.md` into implementable work after the local analytical core is production-safe. It must not weaken the local-first, user-owned-data model. Hosted work starts only after the production portfolio stack has clear production-candidate gates, and every hosted endpoint must preserve deterministic analysis ids, immutable artifacts, explicit user credentials boundaries, and no provider-data redistribution without a licensing decision. Each PR is stacked on the prior PR until merged.

### PR76. Goal Traceability Matrix And Product Scope Gate

Branch: `docs/goals-traceability-matrix`.

Git status: not started. PR: TBD.

Priority: P0 governance for product scope.

Depends on: PR75.

Scope: Add a maintained goal-to-backlog traceability matrix mapping `GOALS.md` sections to PR stacks, explicit production prerequisites, blocked hosted items, and out-of-scope broker-execution decisions. Add a machine-checkable documentation test that every active goal category has either an implemented PR, an open backlog PR, or an explicit deferred rationale.

Acceptance: Tests fail when a new top-level goal is added without a linked backlog entry. The matrix links risk-first portfolio construction, income specialization, current-position analysis, monitoring, hosted BYOK, licensing/privacy, and architecture-growth goals to concrete PR numbers.

Determinism: Goal anchors, backlog PR ids, and deferred statuses are sorted and validated from static Markdown content; validation cannot depend on timestamps or GitHub API state.

Idempotency: Regenerating or validating the same traceability matrix leaves files unchanged and never mutates lake data or runtime state.

### PR77. Local Portfolio Project And Analysis Manifest Catalog

Branch: `feat/local-project-analysis-catalog`.

Git status: not started. PR: TBD.

Priority: P0 product data model.

Depends on: PR76.

Scope: Add a local product catalog for portfolio projects, positions, settings, analysis runs, and artifact references using SQLite for small application state and Parquet for analytical outputs. Keep Founder Core calculations in `src/founder` and expose a service boundary that records project metadata, current positions, run status, input identities, and artifact paths without duplicating portfolio math.

Acceptance: Tests cover project creation, position updates, run manifest creation, immutable artifact references, SQLite migration bootstrap, missing artifact detection, no secret persistence, and deterministic serialization of project and run summaries.

Determinism: Project ids, run ids, and artifact refs derive from normalized portfolio content, input dataset ids, analysis settings, and schema versions unless the user explicitly requests a new named project.

Idempotency: Replaying the same project import or analysis registration reuses existing catalog rows or writes the same logical state without duplicate positions, duplicate run records, or rewritten analytical artifacts.

### PR78. Local Docker Compose BYOK Development Baseline

Branch: `chore/local-docker-compose-byok-dev`.

Git status: not started. PR: TBD.

Priority: P1 local development foundation.

Depends on: PR77.

Scope: Add the local Docker development baseline before any UI work: root `docker-compose.yml`, compose override or documented development profile, ignored runtime `data/` volume layout, environment variable contracts for `DATABASE_URL`, `FOUNDER_DATA_DIR`, `NEXT_PUBLIC_API_URL`, and session-scoped user key handling. Add placeholder build contexts for `apps/api` and `apps/web` only when the corresponding application directories are introduced by later PRs; the compose contract must be ready for local development from the first hosted PR.

Acceptance: CI or scripted tests validate the compose file, assert runtime data paths are outside Git, verify documented environment names, prove no PostgreSQL, Redis, queue, object storage, Kubernetes, or credential vault is required for the baseline, and confirm placeholder services or profiles fail with explicit "service not implemented yet" messages rather than silently starting incomplete applications.

Determinism: Build inputs, exposed ports, service names, environment names, and volume paths are explicit and documented; generated image tags in tests are content or commit based.

Idempotency: Re-running compose setup with unchanged source reuses the same data volume and does not reset SQLite, lake artifacts, analysis manifests, or local secrets unless an explicit clean command is invoked.

### PR79. FastAPI BYOK Analysis Service In Local Compose

Branch: `feat/hosted-api-byok-compose-baseline`.

Git status: not started. PR: TBD.

Priority: P1 hosted API foundation.

Depends on: PR78.

Scope: Add `apps/api` with a FastAPI service exposed through the local Docker Compose stack. Provide `/health`, `/portfolios`, `/portfolios/{portfolio_id}`, `/analyses`, `/analyses/{run_id}`, `/analyses/{run_id}/metrics`, `/analyses/{run_id}/returns`, and `/analyses/{run_id}/weights`. Execute small analyses synchronously at first, return run identifiers and status, pass user-supplied EODHD keys only through request/session scope, and store only non-secret project and artifact metadata. The API must be runnable both by direct local command and through `docker compose up api`.

Acceptance: API tests cover request validation, health, portfolio CRUD, synchronous analysis run creation, status responses, artifact-backed metric responses, secret redaction, missing-key failures, invalid portfolio size, direct local startup, compose startup, and no React-side financial calculations.

Determinism: API run ids and response payload ordering derive from normalized request bodies, project ids, pinned input versions, and analysis settings; logs, container ids, host ports, and operational timing cannot affect analytical identities.

Idempotency: Repeating the same analysis request for unchanged project inputs and settings returns the same completed run or an explicit cache hit without duplicate artifacts or repeated provider fetches beyond declared Refresh policy.

### PR80. Responsive Web UI Analysis Shell In Local Compose

Branch: `feat/hosted-web-analysis-shell`.

Git status: not started. PR: TBD.

Priority: P1 user workflow surface.

Depends on: PR79.

Scope: Add `apps/web` with a Next.js and React UI developed and run through the local Docker Compose stack. Provide routes for `/dashboard`, `/portfolio`, `/analysis/{run_id}`, and `/settings`. Use Plotly for charting, support desktop and mobile layouts, allow session-scoped EODHD key entry, portfolio input for an initial 3 to 10 funds, analysis submission, progress/status display, warnings, target weights, risk metrics, drawdowns, income summaries, and correlation views. The UI must consume the PR79 API via `NEXT_PUBLIC_API_URL` and must be runnable both by direct local command and through `docker compose up web`.

Acceptance: UI tests cover route rendering, mobile and desktop layouts, form validation, no key logging or persistence, API error states, loading and completed analysis states, chart-ready payload rendering, warning visibility, accessibility labels for core controls, direct local startup, compose startup, Web-to-API URL wiring, and a smoke test that `docker compose up web api` serves the UI and API health endpoint together.

Determinism: UI state transitions derive from API responses and stable route params; snapshot tests use fixed fixtures and never call providers or run portfolio math in the browser. Container names, local ports, API URLs, and generated client configuration are explicit and documented.

Idempotency: Reopening or refreshing a completed analysis page refetches the same run artifacts and does not create a new analysis unless the user explicitly submits a new request. Restarting the local compose stack preserves existing runtime data and does not create duplicate analyses.

### PR81. Licensing, Privacy, And Provider-Data Boundary Gate

Branch: `docs/hosted-licensing-privacy-gate`.

Git status: not started. PR: TBD.

Priority: P1 hosted risk gate.

Depends on: PR80.

Scope: Add a mandatory hosted-readiness gate for market-data licensing, derived-data display, redistribution rights, user-key handling, privacy controls, backup boundaries, log redaction, and no broker execution. The gate must block public-hosted defaults until a decision record marks each requirement approved, local-only, or disabled.

Acceptance: Tests or policy checks fail if hosted docs claim public availability while licensing, privacy, credential, and provider-data decisions are unresolved. API and Web docs include user-owned credential boundaries and no direct broker-order execution claims.

Determinism: Gate status is read from versioned decision records and static configuration, not environment-specific secrets or live provider calls.

Idempotency: Re-running the gate reports the same readiness status for unchanged decision records and does not alter runtime settings or user data.

### PR82. Hosted Report Export And User-Facing Explanation Views

Branch: `feat/hosted-report-explanation-views`.

Git status: not started. PR: TBD.

Priority: P2 product comprehension.

Depends on: PR81.

Scope: Add hosted report views and exports for selected and excluded instruments, target weights, risk contributions, expected income, drawdown, tail risk, concentration diagnostics, costs, turnover, model disadvantages, data-quality warnings, and current-versus-target differences when positions are supplied. Reports consume recommendation and analysis artifacts; they must not recompute formulas in Web UI code.

Acceptance: Tests cover deterministic report payloads, no guaranteed-return language, unavailable metric display, warning propagation, current-position comparison, chart/table consistency, mobile report readability, and export filenames keyed by run id and template version.

Determinism: Report ids and rendered sections derive from recommendation ids, analysis ids, project ids, position snapshot ids, and template versions.

Idempotency: Re-exporting an unchanged report produces the same content and filename, updating only explicitly allowed generated-at metadata.

### PR83. Hosted Monitoring And Architecture Growth Path

Branch: `feat/hosted-monitoring-growth-path`.

Git status: not started. PR: TBD.

Priority: P3 hosted operations.

Depends on: PR82.

Scope: Add optional scheduled monitoring runs for hosted projects, including drift, drawdown, risk-limit, stale-data, distribution-cut, and NAV-erosion statuses. Document independent migration paths from SQLite to PostgreSQL, local filesystem to object storage, synchronous API to worker/queue, session key to encrypted credential vault, and single API to multiple instances without changing API contracts.

Acceptance: Tests cover deterministic monitoring policies, unchanged-data no-op runs, alert-ready status payloads, disabled scheduling by default, stale data warnings, distribution-cut warnings, drift thresholds, and documented migration compatibility checks.

Determinism: Monitoring ids include project id, current Refresh snapshot, position snapshot, analysis or recommendation id, monitoring policy, schedule id, and algorithm version.

Idempotency: Re-running monitoring for unchanged inputs produces the same statuses and does not duplicate alerts, reports, provider downloads, or analysis runs.

### Series Completion Gate

Final branch: `feat/hosted-monitoring-growth-path`.

Squash rule: Every PR title and final squash commit subject must use `type(optional-scope): subject`. The final PR must not be merged until PR76 through PR82 are merged or explicitly superseded in this backlog.

Required main merge gate: `merge-gate` must pass Ruff lint and format, architecture/import-boundary checks, Pyright strict, Pytest with at least 95% coverage, dataset schema-registry validation, API/UI contract tests, secret-redaction tests, and hosted-readiness policy checks. The series remains incomplete while hosted flows can persist provider keys by default, expose provider data without a licensing decision, run financial logic in the Web UI, or create broker orders.

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
