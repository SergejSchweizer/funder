# Production Portfolio Implementation Map

Last reviewed: 2026-07-17

## Purpose

This document is an implementation annex to the `Production Portfolio Product PR Stack` in `BACKLOG.md`, especially PR56 through PR68. It records the concrete module ownership, files, contracts, datasets, and tests required to turn the current deterministic research baselines into production-labeled portfolio decision support.

The annex does not replace the canonical backlog. PR status, dependency order, branch names, and completion gates remain owned by `BACKLOG.md`.

## Current Baseline

PR56 is merged and provides the return-semantics and data-quality foundation:

- `return` is the statistical log return;
- `simple_return` is used for wealth simulation;
- non-positive and duplicate-date prices are quarantined instead of becoming fabricated zero returns;
- minimum-history and production-eligibility fields are persisted.

The remaining implementation work begins with PR57.

## Architecture Ownership Rules

1. Do not add further production implementations to `src/camovar/evaluation.py` or `src/camovar/portfolio.py`.
2. Keep `camovar.evaluation` and `camovar.portfolio` as compatibility facades that re-export stable public functions.
3. Move the real implementations into `evaluation_parts`, `portfolio_parts`, and the dedicated `risk_model` and `income` packages.
4. Keep pure mathematics separate from lake reads and writes.
5. Only writer or service modules may depend on `LakePaths`, `read_rows`, or `write_rows`.
6. Production portfolio work consumes a ready final Selection and its exact Selection calendar. It must not scan unrelated catalog, Gold, or legacy artifacts.
7. Every production-facing artifact must expose requested method, actual method, availability status, diagnostics, input identities, algorithm version, and `production_eligible`.
8. A baseline fallback must never be labeled as the requested production optimizer.

Target dependency direction:

```text
refresh
  -> selection
  -> update
       -> risk_model
       -> income
       -> evaluation_parts
       -> portfolio_parts
       -> schemas / paths / table_io
```

## Shared Return Mathematics

PR56 already introduced `src/camovar/return_quality.py`. Keep data-quality policy there.

Add a small pure module:

```text
src/camovar/return_math.py
```

It should own:

- simple return calculation;
- log return calculation;
- conversion between simple and log returns;
- simple-return wealth compounding;
- log-return cumulative conversion;
- shared numerical validation.

Callers:

- `src/camovar/gold.py`;
- `src/camovar/univariate_statistics.py`;
- `src/camovar/evaluation_parts/portfolio_returns.py`;
- `src/camovar/evaluation_parts/rebalance.py`;
- `src/camovar/evaluation_parts/backtest.py`.

Tests:

```text
tests/test_return_math.py
tests/test_return_quality.py
```

Required invariants:

- one-asset portfolio wealth equals the underlying asset wealth series;
- cumulative simple and log return representations agree within tolerance;
- an invalid price never produces a valid zero return;
- transformation functions are pure and order-stable.

## PR57. Instrument-Level Rebalancing Drift And Cost Basis

Primary implementation files:

```text
src/camovar/evaluation_parts/rebalance.py
src/camovar/evaluation_parts/rebalance_contracts.py
src/camovar/evaluation_parts/portfolio_returns.py
```

Compatibility files to reduce to facades after migration:

```text
src/camovar/evaluation.py
```

Contracts to introduce:

- `RebalancePolicy`;
- `TransactionCostPolicy`;
- `PositionState`;
- `RebalanceEvent`;
- `RebalanceResult`.

`RebalancePolicy` should include schedule, drift threshold, initial portfolio value, minimum trade value, cash policy, fractional-share policy, and target-weight source.

`rebalance.py` should own pure functions for:

- evolving each instrument with its own `simple_return`;
- calculating pre-trade values and weights;
- determining scheduled, threshold, and hybrid rebalance events;
- calculating target values and trade values;
- calculating turnover and transaction costs;
- preserving or allocating cash remainder;
- calculating post-trade values and weights;
- writing no artifacts directly.

Required instrument evolution:

```text
post_return_value_i = prior_value_i * (1 + simple_return_i)
pre_trade_weight_i = post_return_value_i / total_post_return_value
```

Persistence changes:

```text
src/camovar/schemas.py
src/camovar/paths.py
CONTRACTS.md
```

Retain aggregate `rebalance_events` and add a long-format dataset:

```text
rebalance_positions
```

Suggested required fields:

```text
run_id
evaluation_id
portfolio_id
date
isin
exchange
code
pre_return_value
post_return_value
pre_trade_weight
target_weight
target_value
trade_value
turnover_contribution
transaction_cost
post_trade_value
post_trade_weight
cash_remainder
```

Tests:

```text
tests/test_rebalance_engine.py
tests/test_rebalance_contracts.py
tests/test_evaluation.py
tests/test_schema_validation.py
tests/test_update_metric_stack.py
```

Required invariants:

- different asset returns create different weight drift;
- no-rebalance periods change weights but produce zero trade value;
- a threshold event fires only after the configured drift threshold;
- total position value plus cash reconciles to portfolio value;
- transaction costs reduce value exactly once;
- a hand-calculated spreadsheet fixture matches persisted rows.

## PR58. Risk Model Package And Covariance Diagnostics

Create:

```text
src/camovar/risk_model/
    __init__.py
    contracts.py
    matrix.py
    estimators.py
    diagnostics.py
    service.py
    writers.py
```

### `contracts.py`

Own immutable, versioned contracts:

- `RiskEstimator`;
- `RiskModelSpec`;
- `RiskModelRequest`;
- `RiskModelResult`;
- `CovarianceMatrixRef`;
- `CorrelationMatrixRef`;
- `CovarianceDiagnostics`.

`RiskModelSpec` should include estimator, return type, frequency, calendar id, full/rolling/expanding window policy, window size, EWMA decay, minimum observations, missing-observation policy, PSD policy, and algorithm version.

### `matrix.py`

Own:

- canonical asset ordering;
- conversion from aligned long-format rows to a numerical matrix;
- complete Selection-calendar enforcement;
- missing-value rejection or explicit policy application;
- covariance and correlation row serialization helpers;
- symmetry validation.

It must not use pairwise-intersection covariance as a substitute for a common-calendar portfolio covariance matrix.

### `estimators.py`

Own pure estimators:

- sample covariance;
- Ledoit-Wolf shrinkage covariance;
- EWMA covariance;
- rolling and expanding estimation windows.

### `diagnostics.py`

Own:

- observation and asset counts;
- missing-value and missing-pair counts;
- symmetry checks;
- eigenvalue and positive-semidefinite checks;
- condition number and stability category;
- shrinkage intensity;
- zero-variance detection;
- matrix-repair status;
- insufficient-history status.

### `service.py`

Resolve a risk-model request from a pinned final membership, exact Selection calendar, return artifact ids, and explicit `RiskModelSpec`. It should return existing immutable artifacts on cache hits.

### `writers.py`

Own all `LakePaths` and table serialization for risk-model artifacts.

Integration files:

```text
src/camovar/update/contracts.py
src/camovar/update/ports.py
src/camovar/update/service.py
src/camovar/schemas.py
src/camovar/paths.py
```

Legacy `src/camovar/gold.py` may retain sample covariance compatibility outputs, but production optimization must consume an explicit risk-model artifact reference.

Datasets:

```text
risk_model_covariance
risk_model_correlation
risk_model_diagnostics
```

Tests:

```text
tests/test_risk_model_contracts.py
tests/test_risk_model_matrix.py
tests/test_risk_model_estimators.py
tests/test_risk_model_diagnostics.py
tests/test_risk_model_service.py
```

Required invariants:

- canonical asset order is independent of input order;
- covariance is symmetric within tolerance;
- missing covariance cannot silently become zero;
- sample covariance matches the current trusted baseline fixture;
- shrinkage improves or explicitly reports matrix conditioning;
- artifact identity changes when estimator settings or calendar identity changes.

## PR59. Production Numerical Solver Boundary

Refactor the portfolio implementation into:

```text
src/camovar/portfolio_parts/
    constraints.py
    objectives.py
    baseline.py
    solver.py
    diagnostics.py
    writers.py
    risk_parity.py
    hrp.py
    diversification.py
    cvar.py
```

Keep:

```text
src/camovar/portfolio.py
```

as a compatibility facade only.

### `baseline.py`

Move the current discrete grid enumeration here. It remains available for tiny fixtures, regression tests, and explicit baseline runs.

Required label:

```text
optimizer_type = grid_baseline
production_eligible = false
```

When the candidate limit is exceeded, the baseline must return an explicit scale-limit result. It must not silently return Equal Weight under a Minimum Variance, Maximum Sharpe, Risk Parity, or Maximum Diversification label.

### `constraints.py`

Own:

- long-only and full-investment constraints;
- minimum and maximum instrument weights;
- issuer, asset-class, sector, country, currency, and strategy limits when metadata is available;
- maximum turnover;
- minimum income or other profile constraints where applicable;
- numerical equality and inequality constraint compilation.

### `objectives.py`

Own pure objective functions only:

- portfolio variance;
- expected portfolio return;
- negative Sharpe objective;
- risk-budget residual;
- negative diversification ratio;
- target-return residual.

It must not read lake files.

### `solver.py`

Define a stable protocol:

```text
PortfolioSolver.solve(SolverRequest) -> SolverResult
```

`SolverResult` must include:

- requested objective;
- actual method;
- status;
- weights or unavailable state;
- objective value;
- convergence status;
- iteration count;
- solver name and settings;
- maximum equality residual;
- maximum inequality violation;
- active bounds;
- infeasibility or failure reason;
- risk-model artifact id;
- production eligibility.

Add numerical dependencies in `pyproject.toml` only after verifying Python 3.14 support. Keep the backend behind the protocol so the dependency can be replaced without changing portfolio contracts.

### `diagnostics.py`

Move and expand optimizer diagnostics here. Diagnostics must distinguish:

```text
requested_method
actual_method
baseline_fallback
solver_failure
infeasible
scale_limit
production_eligible
```

### `writers.py`

Own target-weight, risk-contribution, solver-run, and failure-artifact persistence.

Datasets:

```text
optimizer_runs
optimized_weights
risk_contributions
```

Tests:

```text
tests/test_optimizer_baseline.py
tests/test_optimizer_constraints.py
tests/test_optimizer_solver.py
tests/test_optimizer_diagnostics.py
tests/test_optimizer_writers.py
```

Required invariants:

- a production request never uses the grid baseline implicitly;
- no optimizer is reported as successful with missing covariance inputs;
- infeasible constraints produce no plausible target weights;
- solver diagnostics are persisted even on failure;
- asset and constraint ordering does not alter logical output.

## PR60. Production Minimum Variance And Equal Risk Contribution

Primary files:

```text
src/camovar/portfolio_parts/objectives.py
src/camovar/portfolio_parts/solver.py
src/camovar/portfolio_parts/risk_parity.py
src/camovar/portfolio_parts/diagnostics.py
src/camovar/portfolio_parts/writers.py
```

Minimum Variance must consume a validated shrinkage or EWMA risk-model artifact and solve under explicit constraints.

Equal Risk Contribution must persist:

- marginal risk contribution;
- absolute risk contribution;
- percentage risk contribution;
- target risk budget;
- per-asset residual;
- total objective residual;
- convergence status.

Tests:

```text
tests/test_minimum_variance_solver.py
tests/test_equal_risk_contribution.py
tests/test_production_optimizer_integration.py
```

Required invariants:

- weights sum to one within explicit tolerance;
- every bound and group constraint is checked after solving;
- ERC risk contributions converge to the requested budgets or remain unavailable;
- near-singular covariance produces diagnostics rather than unstable unexplained weights;
- Equal Weight and Inverse Volatility remain mandatory comparison baselines.

## PR61. True HRP And Minimum CVaR Optimizers

### True HRP

Primary file:

```text
src/camovar/portfolio_parts/hrp.py
```

Own explicit steps:

- covariance-to-correlation conversion;
- correlation-distance construction;
- deterministic hierarchical linkage;
- quasi-diagonal ordering;
- cluster-variance calculation;
- recursive bisection;
- final constraint projection and diagnostics.

Persist:

- linkage method and version;
- canonical asset order;
- quasi-diagonal order;
- cluster ids and members;
- split allocation;
- cluster variance;
- final weight diagnostics.

Until this is implemented, the current midpoint recursion must be labeled:

```text
hierarchical_variance_baseline
production_eligible = false
```

### Minimum CVaR

Create or complete:

```text
src/camovar/portfolio_parts/cvar.py
```

Keep the boundary:

```text
evaluation_parts/tail_risk.py  -> evaluate VaR and CVaR
portfolio_parts/cvar.py        -> optimize CVaR
```

Datasets:

```text
hrp_linkage
hrp_clusters
cvar_scenarios
optimized_weights
```

Tests:

```text
tests/test_hrp.py
tests/test_cvar_optimizer.py
```

Required invariants:

- highly correlated assets cluster together in hand-checkable fixtures;
- linkage tie-breaking is deterministic;
- quasi-diagonal order is persisted and reproducible;
- CVaR uses explicit loss scenarios and confidence level;
- repeated threshold losses are handled consistently;
- baseline and production labels cannot be confused.

## PR62. Income And Distribution Quality Metrics

Create:

```text
src/camovar/income/
    __init__.py
    contracts.py
    distributions.py
    metrics.py
    policies.py
    service.py
    writers.py
```

### `contracts.py`

Own:

- `IncomePolicy`;
- normalized distribution-event contracts;
- monthly distribution-bucket contracts;
- income-metric result contracts;
- availability and warning reason codes.

`IncomePolicy` should include trailing window, conservative percentile, tax rate, fee assumptions, minimum distribution history, base currency, and algorithm version.

### `distributions.py`

Own normalization of:

- ex-date;
- payment date with explicit fallback;
- amount and currency;
- duplicate events;
- corrections and deletions;
- monthly aggregation;
- regularity classification.

### `metrics.py`

Calculate:

- trailing twelve-month distribution amount;
- trailing distribution yield;
- mean and median monthly distribution;
- conservative lower-percentile distribution;
- variability and coefficient of variation;
- number of cuts and largest cut;
- longest falling sequence;
- distribution trend;
- price return and total return;
- distribution-to-total-return gap;
- NAV erosion from genuine NAV only;
- income per Expected Shortfall;
- estimated gross and net income;
- sustainable income;
- income efficiency.

### `service.py`

Consume pinned quote, dividend, split, NAV, risk-metric, tax-policy, and fee-policy artifact references. It must not mutate Selection or call Refresh providers.

### `writers.py`

Persist immutable income artifacts and warnings.

Integration files:

```text
src/camovar/update/contracts.py
src/camovar/update/ports.py
src/camovar/update/service.py
src/camovar/selection/contracts.py
src/camovar/schemas.py
src/camovar/paths.py
```

Selection may expose income fields, but it consumes typed Update evidence and must never calculate these metrics itself.

Datasets:

```text
income_distribution_events
income_monthly_distributions
income_metrics
income_warnings
```

Tests:

```text
tests/test_income_contracts.py
tests/test_income_distributions.py
tests/test_income_metrics.py
tests/test_income_service.py
```

Required invariants:

- distribution frequency does not imply distribution quality;
- market close is never substituted for genuine NAV;
- the latest payment is never annualized as the sole sustainable-income estimate;
- insufficient history produces an unavailable result;
- high distributions with weak total return or NAV erosion produce warnings.

## Pairwise Statistics Scalability

Production pair statistics should use the Update pair cache and not one Parquet file per pair.

Pure mathematical engine:

```text
src/camovar/gold_pair_stats.py
```

Artifact and cache ownership:

```text
src/camovar/update/pair_cache.py
```

`gold_pair_stats.py` should own:

- return indexing;
- exact common-date intersection;
- sample covariance;
- Pearson and Spearman calculations;
- beta calculations;
- online mergeable state;
- stable unordered pair orientation.

`update/pair_cache.py` should own:

- pair identity and cache keys;
- input-version validation;
- append-only delta detection;
- correction and deletion invalidation;
- bucket assignment;
- scale and memory guards;
- locks and artifact persistence;
- threshold and top-k edge views.

Keep `src/camovar/bivariate_statistics.py` as a compatibility facade during migration.

Suggested storage:

```text
lake/update/pair_metrics/
    metric=pearson/
        bucket=000/
            part-*.parquet
```

Required invariant: an unordered pair is calculated once per complete cache key and reused across overlapping Selections.

## PR63. Portfolio Profiles, Constraints, And Ensemble Candidate

Create or extend:

```text
src/camovar/portfolio_profiles/
    __init__.py
    contracts.py
    profiles.py
    ensemble.py
    service.py
```

Versioned profiles:

- Defensive;
- Balanced;
- Income;
- Growth.

Each profile must expand into explicit risk-model choices, optimizer candidates, constraints, eligibility gates, baseline comparisons, and unavailable reasons.

The initial Balanced ensemble should combine production True HRP, ERC, and shrinkage Minimum Variance using per-asset median weights, normalization, and final constraint projection.

The Income profile must include sustainable net income, NAV erosion, CVaR, concentration, and turnover constraints.

Tests:

```text
tests/test_portfolio_profile_contracts.py
tests/test_portfolio_profiles.py
tests/test_portfolio_ensemble.py
```

Required invariant: a profile is a versioned configuration expansion, not hidden recommendation logic.

## PR64. Walk-Forward Model Comparison Scorecard

Primary implementation files:

```text
src/camovar/evaluation_parts/backtest.py
src/camovar/evaluation_parts/backtest_contracts.py
src/camovar/evaluation_parts/scorecard.py
```

`WalkForwardSpec` should include:

- rolling or expanding mode;
- training observations;
- testing observations;
- re-estimation frequency;
- rebalance policy;
- transaction-cost policy;
- risk-model spec;
- objective or profile spec;
- minimum-history and availability policy.

The engine must enforce a strict information cutoff:

```text
train_end < test_start
```

For every split it must refit the risk model and portfolio candidate using training data only, then apply the resulting weights to the test period.

Toy defaults such as two training observations and one test observation may remain in unit fixtures only. Production workflows should require explicit windows or use documented defaults such as 504 training observations and 21 testing observations.

`scorecard.py` should compare candidates using common out-of-sample metrics:

- return;
- volatility;
- Sharpe and Sortino;
- CVaR;
- drawdown and recovery;
- turnover and costs;
- weight stability;
- concentration;
- income quality where applicable;
- median and adverse quantiles across windows.

Tests:

```text
tests/test_walk_forward_contracts.py
tests/test_walk_forward_backtest.py
tests/test_walk_forward_information_cutoff.py
tests/test_walk_forward_costs.py
tests/test_model_comparison_scorecard.py
```

Required invariants:

- no test observation influences training weights;
- every candidate uses the same split calendar and cost policy;
- rankings cannot use highest in-sample return as the sole criterion;
- failed or unavailable splits remain visible and cannot become zero-valued success rows.

## PR65 Through PR68 Ownership Notes

### PR65. Stress, Bootstrap, And Sensitivity

Suggested package:

```text
src/camovar/stress/
```

Own historical stress definitions, seeded block bootstrap, covariance perturbation, correlation convergence, distribution-cut shocks, and sensitivity summaries. Persist seeds and scenario versions.

### PR66. Explainable Recommendation Report

Suggested package:

```text
src/camovar/recommendation/
```

Consume completed scorecards, stress results, income artifacts, constraints, and warnings. Produce structured report data with inclusion and exclusion reasons, candidate disadvantages, traceable assumptions, and no guaranteed-return wording.

### PR67. Current Positions And Flatex Transition

Primary package:

```text
src/camovar/trading/
```

Own current positions, target differences, whole-share rounding, minimum order size, fees, taxes, FX assumptions, cash remainder, and deterministic Flatex-oriented exports. It must consume an approved recommendation and must not choose the optimization objective.

### PR68. Local Reports And Monitoring

Suggested packages:

```text
src/camovar/projects/
src/camovar/reporting/
src/camovar/monitoring/
```

Own local project state, report rendering, drift checks, risk-limit checks, distribution-cut checks, NAV-erosion checks, stale-data checks, and alert-ready statuses.

## Schema And Artifact Checklist

Every new dataset must update these files together:

```text
src/camovar/schemas.py
src/camovar/paths.py
CONTRACTS.md
ARCHITECTURE.md
DECISIONS.md
RISKS.md
BACKLOG.md
```

Recommended new datasets:

```text
rebalance_positions
risk_model_covariance
risk_model_correlation
risk_model_diagnostics
optimizer_runs
hrp_linkage
cvar_scenarios
income_distribution_events
income_monthly_distributions
income_metrics
income_warnings
model_comparison_scorecard
```

Every production analytical artifact should include or reference:

```text
artifact_id
algorithm_version
input artifact ids
selection_id
final_membership_id
calendar_id
policy or specification id
status
availability_reason
requested_method
actual_method
production_eligible
```

## Test Strategy

In addition to example-based tests, add invariant and property-style fixtures covering:

- input-order independence;
- deterministic asset ordering;
- exact wealth reconciliation;
- covariance symmetry;
- PSD and condition diagnostics;
- complete constraint validation after optimization;
- no silent fallback;
- no unavailable-value-as-zero behavior;
- no future data in walk-forward training;
- no cross-Selection artifact contamination;
- cache reuse for overlapping Selections;
- immutable artifact identities;
- idempotent reruns and resumable partial failures.

The merge gate should continue to require Ruff, strict Pyright, architecture checks, schema validation, Pytest, and at least 95% coverage. Production numerical tests should use explicit tolerances and hand-checkable fixtures rather than exact floating-point byte equality where inappropriate.

## Delivery Order

The recommended implementation order remains the canonical backlog order:

```text
PR56  return semantics and quality          merged
PR57  instrument-level rebalancing drift
PR58  risk-model package and diagnostics
PR59  solver boundary and no silent fallback
PR60  production Minimum Variance and ERC
PR61  True HRP and Minimum CVaR
PR62  income and distribution quality
PR63  profiles, constraints, and ensemble
PR64  walk-forward comparison scorecard
PR65  stress, bootstrap, and sensitivity
PR66  explainable recommendation
PR67  current positions and Flatex export
PR68  local reports and monitoring
```

Do not begin the hosted API and Web UI production slice before PR60 is stable. Before that point, the interface would expose deterministic baselines that could appear more production-ready than their underlying numerical methods.

## Completion Gate

This implementation map is complete only when:

- compatibility facades no longer own production mathematics;
- return, rebalancing, risk-model, optimizer, income, and backtest contracts are explicit;
- missing or invalid analytical inputs produce unavailable results rather than plausible zeros;
- production optimizers use validated risk-model artifacts and persist solver diagnostics;
- baseline fallbacks are explicit and never mislabeled;
- walk-forward evaluation enforces information cutoffs and costs;
- recommendation and trading layers consume approved immutable artifacts without selecting objectives themselves;
- all listed datasets, docs, architecture checks, and tests move together.