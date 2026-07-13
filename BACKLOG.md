# Backlog

Last reviewed: 2026-07-13

## Table Of Contents

- [How To Use This Backlog](#how-to-use-this-backlog)
- [Search And Bronze Module PR Stack](#search-and-bronze-module-pr-stack)
- [Bronze Process Refactor PR Queue](#bronze-process-refactor-pr-queue)
- [Portfolio Evaluation And Optimization PR Stack](#portfolio-evaluation-and-optimization-pr-stack)
- [Future Work After Finalization](#future-work-after-finalization)
- [Update Rules](#update-rules)

This backlog captures known work that should stay visible across sessions. Keep entries short, actionable, and tied to risks or decisions where possible.

Every PR-sized backlog item must include `Git status` and `PR`. Use `Git status: not started` and `PR: TBD` until work begins.

## How To Use This Backlog

Read this after the architecture and workflow docs when you need implementation status. This file should not explain module behavior in depth; it records scope, dependencies, acceptance criteria, idempotency expectations, Git status, and PR links for trackable work.

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

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/24.

Priority: P0 first decision support.

Depends on: PR16.

Scope: Add portfolio-level metric computation for explicit weight vectors, including portfolio return series, cumulative wealth, running peak, drawdown series, maximum drawdown, drawdown duration, recovery duration, Calmar ratio, and ulcer index. Start with equal-weight and user-supplied weight inputs.

Acceptance: Tests cover single-asset, multi-asset, missing-return alignment, cash-free full-investment weights, max drawdown, drawdown duration, recovered and unrecovered drawdowns, and deterministic Gold output schemas.

Idempotency: Recomputing the same portfolio id from the same return matrix and weights overwrites or validates the same Gold portfolio-return, drawdown, and metric datasets.

### PR18. Portfolio Module: Core Optimization Objectives And Target Weights

Git status: not started. PR: TBD.

Priority: P0 first optimizer.

Depends on: PR17.

Scope: Extend `founder.portfolio` from constraint validation into deterministic optimization objectives that consume Gold evaluation datasets and write selected target weights to Gold. Include equal-weight baseline, constrained minimum variance, maximum Sharpe as a comparison objective, and target-return minimum variance before adding more advanced objectives.

Acceptance: Tests cover objective selection, covariance-matrix use, expected-return vector use, full-investment constraints, long-only constraints, allocation caps, risk-free-rate handling, infeasible constraints, deterministic tie-breaking, and Gold target-weight output rows with objective metadata.

Idempotency: Re-running the same optimization id with unchanged evaluation inputs and constraints produces the same target-weight rows and does not modify Search, Bronze, Bronze, or Silver data.

### PR19. Portfolio Module: Risk Parity And Equal Risk Contribution

Git status: not started. PR: TBD.

Priority: P1 robust optimizer.

Depends on: PR18.

Scope: Add risk parity and equal-risk-contribution computations from the covariance matrix. Compute marginal risk contribution, absolute risk contribution, percent risk contribution, objective residuals against equal risk budgets, and final long-only target weights.

Acceptance: Tests cover diagonal covariance, correlated assets, zero-variance assets, allocation bounds, risk-budget residuals, risk contribution rows, convergence failure reporting, and deterministic target-weight outputs.

Idempotency: Re-running the same risk-parity optimization id with unchanged covariance and constraints produces the same risk contribution and target-weight Gold rows.

### PR20. Evaluation Module: Walk-Forward Backtesting

Git status: not started. PR: TBD.

Priority: P1 trust gate.

Depends on: PR19.

Scope: Add walk-forward evaluation over rolling or expanding windows. For each train/test split, compute in-sample expected returns and covariance, fit selected objective weights, apply them out-of-sample, and write realized return, volatility, Sharpe, drawdown, turnover, and weight history rows.

Acceptance: Tests cover rolling windows, expanding windows, insufficient training history, deterministic split ids, objective reuse, out-of-sample return application, turnover from previous weights, and Gold backtest metric and weight-history schemas.

Idempotency: Re-running the same walk-forward backtest id with unchanged returns, objective settings, windows, and constraints produces the same split ids, metrics, and weight rows.

### PR21. Evaluation Module: Rebalancing Simulation

Git status: not started. PR: TBD.

Priority: P1 implementation realism.

Depends on: PR20.

Scope: Add rebalancing simulations for fixed calendar schedules and drift-threshold schedules. Compute pre-trade weights, target weights, turnover, transaction-cost estimates, post-cost returns, portfolio value, rebalance events, and realized drawdown metrics.

Acceptance: Tests cover monthly, quarterly, annual, and threshold rebalancing; no-rebalance periods; transaction-cost application; cash-free full investment; turnover calculation; drift detection; and deterministic Gold rebalance event and portfolio metric rows.

Idempotency: Re-running the same rebalancing simulation id with unchanged returns, target-weight rules, schedule, and cost assumptions produces the same events and metrics without duplicate rows.

### PR22. Portfolio Module: Hierarchical Risk Parity

Git status: not started. PR: TBD.

Priority: P2 correlated-universe optimizer.

Depends on: PR19.

Scope: Add hierarchical risk parity computations from the correlation and covariance matrices. Compute correlation distance, deterministic clustering order, quasi-diagonal ordering, recursive bisection allocations, cluster risk contributions, and final HRP target weights.

Acceptance: Tests cover correlation-to-distance conversion, stable clustering tie-breaks, two-cluster and multi-cluster examples, highly correlated ETF groups, allocation caps, deterministic ordering, and Gold outputs for cluster structure and target weights.

Idempotency: Re-running the same HRP optimization id with unchanged correlation, covariance, and constraints produces the same cluster rows and target-weight rows.

### PR23. Portfolio Module: Maximum Diversification Objective

Git status: not started. PR: TBD.

Priority: P2 robust comparison optimizer.

Depends on: PR19.

Scope: Add maximum-diversification optimization. Compute asset volatility vector, portfolio volatility, diversification ratio, constrained optimizer weights, and contribution diagnostics that explain which assets improved portfolio diversification.

Acceptance: Tests cover diagonal and correlated covariance matrices, zero-volatility handling, long-only bounds, allocation caps, diversification-ratio calculation, infeasible constraints, and deterministic Gold metric and target-weight rows.

Idempotency: Re-running the same maximum-diversification optimization id with unchanged inputs and constraints produces the same diversification metrics and target weights.

### PR24. Evaluation Module: Efficient Frontier Generator

Git status: not started. PR: TBD.

Priority: P2 analysis and visualization.

Depends on: PR18.

Scope: Add efficient-frontier computation from expected returns and covariance inputs. Generate target-return grid points, minimum-variance weights for each target, and long-format frontier weight rows. Keep optimizer settings, annualization period, risk-free rate, and allocation bounds explicit in the evaluation run metadata.

Acceptance: Tests cover two-asset analytic cases, long-only bounds, full-investment constraints, infeasible target returns, deterministic target grids, stable frontier point ids, and separate Gold datasets for frontier metrics and weights.

Idempotency: Re-running the same frontier evaluation id with the same inputs and settings produces the same point ids, metrics, and weight rows without accumulating stale frontier files.

### PR25. Portfolio Module: CVaR And Tail-Risk Optimization

Git status: not started. PR: TBD.

Priority: P3 tail-risk extension.

Depends on: PR21.

Scope: Add historical CVaR evaluation and optional CVaR minimization for long-only portfolios. Compute portfolio loss series, VaR threshold, CVaR, tail observation count, tail scenario weights, and constrained target weights for selected confidence levels.

Acceptance: Tests cover loss-series construction, VaR quantile selection, CVaR averaging, repeated losses at the threshold, confidence-level validation, long-only constraints, infeasible constraints, deterministic tail scenario rows, and Gold target-weight outputs.

Idempotency: Re-running the same CVaR evaluation or optimization id with unchanged returns, confidence level, and constraints produces the same tail-risk metrics and target weights.

### PR26. Evaluation CLI And Dry-Run Integration

Git status: not started. PR: TBD.

Priority: P1 for P0/P1 objectives, P3 for full advanced stack.

Depends on: PR14 and PR21. Full advanced-objective flags depend on PR22, PR23, PR24, and PR25.

Scope: Add a user entry point such as `founder evaluate` that runs evaluation and optional optimization from existing Gold returns. Extend the mocked dry run with evaluation outputs so the portfolio analytics path is reproducible without credentials.

Acceptance: CLI tests cover evaluation-only runs, optimization-enabled runs, selected objective flags, walk-forward and rebalancing flags, missing Gold input handling, deterministic dry-run outputs, and clear summaries of generated Gold datasets.

Idempotency: Re-running the same command with the same evaluation id and unchanged inputs produces the same Gold outputs and summary without duplicate rows or API calls.

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