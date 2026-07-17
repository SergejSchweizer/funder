# Critical Correctness Priority Queue

Last reviewed: 2026-07-17

## Purpose

This file is the stop-the-line execution-order override and implementation annex for the open Production Portfolio Product PR Stack in `BACKLOG.md`.

The existing PR56 and PR57 correctness work is merged. The repository audit performed after those merges identified additional defects that can either break installed commands, generate misleading out-of-sample evidence, understate portfolio risk, or report a baseline fallback as if it were an optimized portfolio. These defects must receive immediate attention before feature expansion, hosted UI work, recommendation reports, tax calculations, or trade preparation.

The canonical PR definitions remain in `BACKLOG.md`. Until this queue is reflected directly in that file, contributors must use the order and blocking rules below when selecting the next PR.

## Stop-The-Line Policy

1. An open P0 correctness item blocks the start of P1-P4 production portfolio work unless the later work is strictly isolated and cannot consume the affected output.
2. No portfolio, optimizer, backtest, recommendation, income, report, or trade artifact may be labeled `production_eligible` while one of its required P0 gates is unavailable.
3. Missing information must produce `unavailable`, `blocked`, or an explicit baseline status. Missing covariance, missing tax data, missing broker costs, solver failure, or scale-limit failure must never be converted to a plausible zero or silently replaced by Equal Weight.
4. Every generated artifact must record the requested method and the method actually executed.
5. Existing deterministic baseline outputs may remain available for development and comparison, but the UI, CLI summaries, manifests, and reports must identify them as baseline outputs.
6. The next implementation PR should be the first incomplete item in the ordered queue below.

## Immediate Execution Order

| Order | Work item | Priority | Blocks | Required before |
|---:|---|---|---|---|
| 1 | C01 Installed CLI entry-point consistency | P0 | package reliability and CI trust | every later PR |
| 2 | C02 Walk-forward return semantics and production defaults | P0 | all out-of-sample claims | PR58 onward and any recommendation work |
| 3 | C03 Pairwise scale guards and bucketed persistence | P0/P1 | safe large-universe execution | production multivariate runs |
| 4 | PR58 Risk Model Package And Covariance Diagnostics | P0 | valid portfolio risk inputs | PR59 onward |
| 5 | PR59 Production Numerical Solver Boundary | P0 | valid optimized portfolios | PR60 onward |
| 6 | PR60 Production Minimum Variance And Equal Risk Contribution | P1 | first trusted portfolio weights | PR61 onward |
| 7 | PR61 True HRP And Minimum CVaR Optimizers | P1/P2 | robust comparison set | portfolio profiles |
| 8 | PR62A-PR62F EU tax, broker cost, cash-flow, and income stack | P1/P2 for the income product | after-tax income claims | Income profile and recommendation |
| 9 | PR63-PR68 profiles, validation, recommendation, trading, and reports | P2-P4 | product surface | hosted product integration |

C01 and C02 are logically independent and may be implemented in parallel on separate branches. C03 may run in parallel if it does not modify the same files. PR58 must not be treated as complete until C01 and C02 are merged, and production multivariate execution must remain blocked until C03 is merged.

## C01. Installed CLI Entry-Point Consistency And Smoke Gate

Branch: `fix/cli-entrypoint-consistency`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/91.

Priority: P0 package correctness.

Depends on: merged PR57.

### Problem

`pyproject.toml` declares installed console scripts for `founder-selection` and `founder-update`, while the corresponding `founder.selection` and `founder.update` packages were intentionally removed during the later CLI simplification. The package can therefore advertise commands that cannot import their declared targets.

The current quality gate runs linting, formatting, strict type checking, tests, coverage, and architecture checks, but it does not prove that every `[project.scripts]` target imports or that each installed command can display help.

### Scope

- Reconcile every `[project.scripts]` entry with the current canonical CLI architecture.
- Remove obsolete scripts or deliberately restore supported adapters; do not retain dead entry points for historical compatibility.
- Add a registry-driven test that parses every project script declaration, imports the module, resolves the callable, and proves that it is callable.
- Add installed-package smoke tests for `--help` on every supported console script.
- Add umbrella CLI smoke tests for every current subcommand.
- Mark superseded Refresh/Selection/Update CLI documentation and backlog claims clearly as historical or superseded where they conflict with the current five-stage statistics funnel.
- Add the entry-point smoke test to `founder-quality pr` and `merge-gate` through the normal pytest suite.

### Acceptance

- A clean editable or wheel installation exposes no command whose import target is missing.
- Every declared script returns success for `--help` without reading secrets or creating lake artifacts.
- The test fails when a script target is deleted, renamed, lacks the declared callable, or raises during import.
- README, ARCHITECTURE, `pyproject.toml`, and CLI tests agree on the public commands.
- No compatibility command is retained unless its behavior and deprecation status are explicitly tested.

### Determinism

Script discovery, target resolution, and smoke-test ordering are derived from the canonical project metadata and sorted by script name.

### Idempotency

Repeated help and import checks do not create or mutate lake, log, configuration, or user data.

## C02. Walk-Forward Return Semantics And Production Defaults

Branch: `fix/walk-forward-return-semantics`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/93.

Priority: P0 quantitative correctness.

Depends on: merged PR57. May be developed in parallel with C01.

### Problem

The current baseline walk-forward implementation sums simple portfolio returns across a test window instead of geometrically compounding them. It then compares the resulting multi-day return with a daily volatility estimate, producing a Sharpe-like value whose numerator and denominator use inconsistent horizons.

The multivariate defaults currently allow a two-observation training window, a one-observation test window, zero transaction cost, and a maximum instrument weight of one. These values are useful only as tiny fixtures; they must not be the default for any production-facing analysis.

### Scope

- Geometrically compound simple returns for realized test-period return: `product(1 + r_t) - 1`.
- Keep log-return statistics and simple-return wealth paths explicitly separated.
- Calculate volatility, Sharpe, Sortino, and annualized returns with consistent periods and units.
- Define versioned development-fixture and production walk-forward profiles instead of one ambiguous default.
- Require production training history of at least 504 observations unless a versioned policy explicitly states otherwise.
- Use an economically meaningful test window such as 21 or 63 trading days in the initial production policy.
- Require multiple completed out-of-sample splits before an output can become production eligible.
- Include turnover and transaction-cost deductions in every production scorecard.
- Apply instrument concentration limits stricter than 100 percent for production profiles.
- Persist split-level inputs, train/test dates, requested objective, actual optimizer method, pre-cost return, transaction costs, post-cost return, and availability reasons.
- Block production status when the training window, test window, number of splits, return semantics, or cost policy is insufficient.

### Acceptance

- Hand-computed fixtures prove geometric compounding across positive, negative, and mixed simple returns.
- A fixture proves that log-return accumulation and simple-return wealth compounding reconcile within tolerance.
- Multi-day Sharpe and Sortino calculations use matching annualization and frequency assumptions.
- Two-day/one-day fixture settings remain available only under an explicitly named test or baseline profile.
- The production profile rejects histories below its minimum training length and rejects too few completed splits.
- Transaction-cost and turnover changes alter post-cost outputs but not pre-cost market returns.
- No future observation can influence a split's risk model, expected-return estimate, constraints, or weights.

### Determinism

Split ids include the aligned calendar id, train/test policy version, risk-model id, optimizer request, cost policy id, and algorithm version. Asset and date ordering is canonical.

### Idempotency

Unchanged split requests resolve to the same metrics and weights; interrupted runs resume only missing splits.

## C03. Pairwise Scale Guards And Bucketed Persistence

Branch: `perf/pairwise-bucketed-scale-guard`.

Git status: merged. PR: https://github.com/SergejSchweizer/founder/pull/95.

Priority: P0/P1 operational safety.

Depends on: merged PR57. May be developed in parallel with C01 and C02.

### Problem

The current bivariate path can materialize the complete pair set in memory and persist one Parquet file per pair. A universe with 1,759 listings has more than 1.5 million unordered pairs; 2,569 listings have more than 3.2 million. Millions of tiny files and a fully materialized pair list are unsuitable for a NAS-hosted product and can exhaust memory or filesystem resources.

### Scope

- Add an explicit maximum-pair guard before pair materialization or worker submission.
- Stream pair tasks in deterministic chunks instead of calling `list()` over the full pair iterator.
- Replace one-file-per-pair production persistence with deterministic bucketed Parquet artifacts.
- Keep pair identity stable through sorted listing ids and one canonical orientation.
- Add sparse threshold and top-k edge modes for workflows that do not need the full dense matrix.
- Cap default worker count using an explicit resource policy rather than all visible CPU cores.
- Persist pair-plan diagnostics: listing count, theoretical pair count, selected mode, chunk size, worker count, expected bucket count, memory estimate, and rejection reason.
- Preserve a compatibility reader for existing pair files during a documented migration window.
- Keep exact common-date metadata and cache invalidation rules for every pair.

### Acceptance

- A large synthetic universe is rejected before materializing pairs when it exceeds the configured limit.
- Chunked serial and parallel execution produce identical sorted rows and bucket assignments.
- No symmetric duplicate or same-ISIN pair is written.
- Bucket count grows sublinearly relative to pair count and does not create one file per pair.
- Sparse and top-k modes are deterministic and record omitted-pair semantics.
- Backfills or corrections rebuild only affected pair buckets.
- Corrupt or partial buckets are detected and do not masquerade as cache hits.

### Determinism

Pair ids, bucket ids, chunk boundaries, output ordering, and sparse ranking tie-breaks derive from canonical listing ids and versioned policy settings.

### Idempotency

An unchanged run reuses complete buckets and writes no duplicate pair rows. Resume replaces or completes only incomplete buckets.

## Mandatory Amendments To PR58

PR58 remains the first risk-model PR after the immediate hotfixes. Its existing scope must be strengthened with these non-negotiable requirements.

### Missing Covariance Is Not Zero

- Remove all production paths that evaluate portfolio variance, marginal risk, diversification, or risk parity through `covariances.get(..., 0.0)`.
- Validate that every required diagonal and off-diagonal element exists for the exact Selection calendar.
- Missing or non-finite elements produce a blocked risk-model artifact with explicit missing keys and counts.
- Statistical imputation, shrinkage, pairwise deletion, listwise deletion, and other missing-data policies must be explicit, versioned estimators rather than incidental dictionary defaults.

### Matrix Diagnostics

Every risk-model artifact must include:

```text
estimator
estimation_window
observation_count
return_frequency
return_type
missing_pair_count
non_finite_count
symmetry_residual
minimum_eigenvalue
positive_semidefinite_status
condition_number
stability_category
shrinkage_intensity
missing_data_policy
production_eligible
availability_reasons
```

### Architecture Ownership

- New risk-model mathematics belongs in `founder.risk_model`, not in `founder.portfolio` or orchestration code.
- Top-level Evaluation and Portfolio modules remain public compatibility facades.
- `evaluation_parts`, `portfolio_parts`, and the new `risk_model` package must contain the actual implementation rather than dynamically importing monolith functions back from the facade.

### Additional Acceptance

- A missing covariance fixture must fail closed rather than produce an artificially low variance.
- A near-singular highly correlated ETF fixture must produce explicit stability diagnostics.
- A non-PSD input must be rejected or repaired only through a named and versioned repair policy.
- Risk-model artifacts cannot be production eligible solely because an optimizer returned weights.

## Mandatory Amendments To PR59

PR59 remains the production solver boundary. Its existing scope must explicitly prevent method substitution and misleading labels.

### No Silent Equal-Weight Fallback

- Grid candidate limits may produce `candidate_limit_exceeded`; they may not silently return Equal Weight while retaining the requested Minimum Variance, Maximum Sharpe, Risk Parity, Target Return, or Maximum Diversification label.
- Equal Weight remains an explicit baseline objective, not a hidden fallback.
- Solver failure, infeasibility, iteration limit, numerical instability, and missing risk-model inputs produce explicit failure artifacts and no production weights.

### Required Solver Diagnostics

```text
requested_method
actual_method
solver_name
solver_version
solver_status
convergence_status
objective_value
constraint_residuals
bound_activity
iteration_count
numeric_tolerances
risk_model_id
fallback_used
fallback_reason
production_eligible
```

### Additional Acceptance

- Tests force the current candidate-count threshold and prove that the result cannot be labeled as the requested optimized method.
- Tests prove that explicit Equal Weight and an optimizer failure are distinguishable in artifacts, CLI summaries, and reports.
- Production mode never uses grid enumeration as an implicit substitute for a numerical solver.
- Baseline mode may retain deterministic grid behavior only when `actual_method` and `production_eligible=false` are persisted.

## Mandatory Amendments To PR61

The current recursive midpoint split is not true Hierarchical Risk Parity.

PR61 must:

- calculate correlation distance;
- perform an explicit hierarchical clustering/linkage method;
- persist the dendrogram or linkage representation;
- derive a deterministic quasi-diagonal asset order;
- perform recursive bisection along the actual cluster tree;
- expose linkage method, tie-breaking policy, cluster ids, cluster variances, and ordering diagnostics;
- rename the existing method as a baseline until the true implementation is merged.

No output from the midpoint recursive variance baseline may be labeled `hierarchical_risk_parity` in a production-facing artifact.

## Mandatory Amendments To PR62A-PR62F

The income product is not complete when distribution frequency and dates are available. It becomes decision-useful only after amount, sustainability, tax, cost, and capital-preservation calculations are integrated.

The EU-neutral stack documented in `docs/backlog/eu-tax-cost-architecture.md` must execute before any Income profile or recommendation is production eligible:

1. PR62A: jurisdiction-neutral tax, cost, cash-flow, and status contracts.
2. PR62B: Austria tax adapter and Flatex Austria reference cost profile.
3. PR62C: effective-dated rule resolution, tax-year state, cost basis, loss offset, and foreign-tax credit handling.
4. PR62D: broker, venue, spread, slippage, FX, custody, and transaction-cost engine.
5. PR62E: gross, after-tax, and after-cost cash flows; natural, synthetic, hybrid, and reinvestment policies; income stability and capital-preservation metrics.
6. PR62F: templates, conformance tests, source metadata, readiness reporting, and expansion to further EU country adapters.

Required income outputs include distribution amounts, trailing yield, monthly net spendable income, conservative lower-percentile income, distribution cuts, NAV erosion, after-tax total return, tax drag, cost drag, nominal capital change, real capital change, and sustainable withdrawal warnings.

Unsupported country, fund-tax, broker, or cost inputs must block jurisdiction-specific production claims.

## Production Label Gate

A portfolio candidate may be labeled production eligible only when all required gates below are satisfied:

```text
return semantics valid
price and history quality valid
aligned Selection calendar valid
walk-forward policy valid
sufficient out-of-sample splits
risk model complete and stable
no missing covariance interpreted as zero
solver converged
requested method equals actual method
constraints satisfied
turnover and transaction costs applied
income policy complete when applicable
tax and broker-cost coverage complete for the selected jurisdiction when applicable
stress and sensitivity evidence available for recommendations
all warnings and unavailable reasons propagated
```

Failure of any required gate produces no production label and no broker-ready trade export.

## CI And Governance Additions

The merge gate must eventually include regression coverage for:

- every declared project script importing and responding to `--help`;
- geometric walk-forward compounding and consistent annualization;
- no look-ahead across train/test boundaries;
- missing covariance failing closed;
- no hidden Equal-Weight fallback;
- requested versus actual optimizer method reconciliation;
- pair-count and memory guards before materialization;
- bucketed pair persistence and deterministic resume;
- facade-to-implementation dependency direction;
- explicit baseline, unavailable, blocked, and production statuses;
- no production recommendation or Flatex export from incomplete gates.

## Completion Rule

This critical queue is complete only when:

- C01, C02, and C03 are merged or explicitly superseded by equivalent merged work;
- PR58 and PR59 contain the mandatory amendments above;
- existing baseline artifacts are relabeled where necessary;
- the main merge gate proves the stop-the-line invariants;
- `BACKLOG.md`, ARCHITECTURE, README, lake contracts, and implementation-map documentation reflect the same execution order and status vocabulary.
