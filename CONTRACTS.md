# Lake Contracts

Last reviewed: 2026-07-13

## Table Of Contents

- [Layers](#layers)
- [Core Tables](#core-tables)
- [Portfolio Evaluation Outputs](#portfolio-evaluation-outputs)
- [How This Fits The Onboarding Flow](#how-this-fits-the-onboarding-flow)

Founder uses deterministic local lake artifacts under a `LakePaths` root. Table paths ending in `.parquet` are physical Apache Parquet files written through `founder.table_io`; JSON and CSV artifacts keep their native formats.

Read this after [ARCHITECTURE.md](../ARCHITECTURE.md) and before changing Search, statistics, or storage code.

## Layers

- Bronze stores raw or near-raw EODHD search, quote, dividends, and splits payloads.
- Silver stores normalized search candidates, canonical universe rows, and quote rows with one file per exchange and ISIN.
- Gold stores adjusted-close returns, correlation, covariance, asset features, portfolio evaluation, and target-weight rows.
- Silver also stores operational datasets for active universe pointers, bronze plans, bronze runs, coverage, errors, and dry-run summaries.

Bronze quote rows are partitioned by exchange and quote year, with one file per ISIN:

```text
bronze/quotes/{exchange}/{year}/{ISIN}.parquet
```

Silver and Gold remove the year directory so all years for an ISIN stay in one file:

```text
silver/quotes/{exchange}/{ISIN}.parquet
gold/returns/{exchange}/{ISIN}.parquet
gold/univariate_statistics/{exchange}/{ISIN}.parquet
gold/correlation/{exchange}/{ISIN}.parquet
gold/covariance/{exchange}/{ISIN}.parquet
gold/bivariate_statistics/version={version}/bucket={bucket}.parquet
gold/correlation_edges/version={version}/metric={metric}/bucket={bucket}.parquet
gold/features/{exchange}/{ISIN}.parquet
gold/runs/gold_runs.parquet
gold/evaluation/return_matrices/{evaluation_id}.parquet
gold/evaluation/asset_metrics/{evaluation_id}.parquet
gold/evaluation/portfolio_returns/{evaluation_id}.parquet
gold/evaluation/drawdowns/{evaluation_id}/{portfolio_id}.parquet
gold/evaluation/portfolio_metrics/{evaluation_id}.parquet
gold/evaluation/frontier_points/{evaluation_id}.parquet
gold/evaluation/frontier_weights/{evaluation_id}.parquet
gold/weights/{objective}/{evaluation_id}.parquet
gold/risk_contributions/{objective}/{evaluation_id}.parquet
```

Runtime logs are intentionally outside the lake under `.logs/`. They are operational diagnostics, not dataset artifacts.

Operational Silver artifacts use focused directories rather than a fourth lake layer:

```text
silver/universe/current_universe.json
silver/plans/bronze_plans/{run_id}.parquet
silver/runs/bronze_runs.parquet
silver/runs/dry_run_summary.json
silver/coverage/coverage.parquet
silver/coverage/quote_gaps.parquet
```

## Core Tables

- `search_candidates`: normalized discovery rows with search run id, query, endpoint, instrument identifiers, type, country, currency, ISIN, name, normalized name, and discovery timestamp.
- `canonical_universe`: one selected listing per ISIN, including selection reason and `selected_for_bronze=true`.
- `bronze_plan`: run id, ISIN, code, exchange, derived EODHD symbol, start date, and end date. In default gap-aware runs, one listing can expand into multiple gap windows.
- `quotes`: normalized OHLCV rows with adjusted close, currency, run id, and bronze timestamp. Delta writes merge into existing per-ISIN files by ISIN, exchange, code, and quote date.
- `dividends` and `splits`: near-raw EODHD rows archived under `bronze/{dataset}/{exchange}/{year}/{ISIN}.parquet` for each approved listing, matching the quote partition shape.
- `coverage`: first and last quote dates, observed rows, missing periods, and next bronze start used by gap-aware Bronze planning.
- `quote_gaps`: quote gap ranges by ISIN, code, exchange, symbol, data type, gap type, start, end, and missing trading-day count. Gap-aware Bronze downloads historical gaps first, then the tail to the selected run date.
- `errors`: non-secret bronze error records.
- `returns`, `correlation`, and `covariance`: Gold risk-input tables built from validated Silver quote rows and written as per-ISIN files without year partitions. Gold return rows use daily adjusted-close log returns: `ln(P_t / P_{t-1})`, plus a `simple_return` field, `(P_t / P_{t-1}) - 1`, used for wealth simulation instead of log-return compounding. Prices that are non-positive or repeat an earlier date are quarantined by `founder.return_quality` and excluded from both fields rather than becoming a fabricated zero return. Pairwise correlation and covariance values are computed only on the common date intersection of the two return series.
- `univariate_statistics`: one Gold row per ISIN listing, written to a stable listing path that does not include the search run id. Rows include return, volatility, downside, drawdown, trend, tail-risk, income-distribution, history-coverage, and data-quality summaries that can be reused when later search lists include the same listing. Portfolio-facing field groups are defined in `founder.univariate_categories` as Instrument Identity, History Coverage, Return Level, Return Distribution, Volatility And Downside Risk, Risk-Adjusted Performance, Tail Risk, Drawdown And Trend, Income Distribution, and Data Quality And Production Readiness. Rows also include `quarantined_price_count`, `non_positive_price_detected`, `duplicate_date_detected`, `stale_price_detected`, `unexplained_gap_detected`, `meets_min_history_252/504/756`, `production_eligible`, and `data_quality_reason` from the shared `founder.return_quality` gate.
- `bivariate_statistics`: one Gold row per pair of distinct ISIN listings, written to deterministic `version`/`bucket` Parquet files (`bucket = left_id % bucket_count`) instead of one file per pair, so file count grows sublinearly with pair count. Rows include stable listing keys, stable pair key, the `version` and `bucket` they were written under, common-date range, common observation count, Pearson correlation, Spearman correlation, covariance, each side's variance, and directional beta values. A universe whose theoretical pair count exceeds an explicit `max_pair_count` guard (default 500,000) is rejected before any pair is enumerated or submitted to a worker. Default worker count uses all CPU cores visible to the system; `--concurrency` or the API `concurrency` argument caps worker processes for bounded runs. Pair-plan diagnostics (listing count, theoretical pair count, mode, chunk size, worker count, bucket count, and rejection reason if any) are persisted as a `bivariate-statistics-plan` job manifest for every call. A bucket file is only rewritten when at least one of its pairs changed or was added/removed; unaffected buckets are left untouched, and a bucket whose stored `bucket` field does not match its own file position is treated as corrupt and never used as a cache hit. `founder.bivariate_statistics.read_legacy_bivariate_pair` remains available to read historical pre-C03 one-file-per-pair artifacts (`gold/bivariate_statistics/{left_exchange}/{left_ISIN}/{left_code}/{right_exchange}__{right_ISIN}__{right_code}.parquet`) during the migration window; new writes never use that layout.
- `selection_statistics_view` (PR74, `silver/{source_module}/selection_id={selection_id}/statistics_view.json`): a read-only materialization of which of the above cached univariate/bivariate rows belong to a Metadata Filter or Univariate Filter selection. `founder.statistics_views.build_selection_statistics_view` checks the generic Gold caches for every selected listing and unordered pair and reports `missing_univariate_listings`/`missing_bivariate_pairs` deterministically rather than recomputing or substituting a partial result; `read_selection_statistics` loads a selection's cached rows without recomputing and raises when the cache is incomplete.
- `correlation_edges`: Gold pair-search table for scalable correlation filtering. Rows store one upper-triangle pair where `left_id < right_id`, the listing identifiers, metric name, input version, common date range, common observation count, and correlation value. Same-ISIN pairs are skipped even when the listings use different exchanges or codes. Supported metrics are `pearson` and `spearman`; Pearson values are computed with an incremental online correlation algorithm, and Spearman values use an approximative online rank-score correlation. Edge values use only the common date intersection of the two return series. Bucket files are grouped by `left_id % bucket_count` so later DuckDB or Polars scans can filter relevant partitions instead of opening a dense matrix. Building edges without a `min_abs_correlation`/`top_k_per_left` filter (dense mode) is subject to the same `max_pair_count` scale guard as `bivariate_statistics`.
- `features`: per-listing Gold asset feature rows with first and last quote dates, quote and return observation counts, total return, mean return, volatility, and maximum drawdown.
- `gold_runs`: per-listing Gold completion manifest with status, input last quote date, global input snapshot date, listing count, and completion time. Gold uses this to resume the per-ISIN job without reprocessing completed listings when the input snapshot has not changed.

Bronze and Silver default to concurrency `2` for provider/API and IO safety. Univariate Statistics, Bivariate Statistics, Multivariate Statistics, and Gold risk-input builds default to all CPU cores visible to the system for CPU-heavy local calculations; every CLI exposes `--concurrency <workers>` to cap worker processes for bounded or deterministic runs.

Gold input builds are designed for large ETF universes. The CLI defaults to all visible CPU cores for parallel Gold workers, processes one ISIN listing per worker task, and computes each symmetric correlation/covariance pair only once before writing per-left-listing files. If any listing date or the listing count changes, the global input snapshot changes and Gold recomputes the affected matrix outputs instead of trusting stale pair statistics.

Gap-aware planning discovers missing windows from the `quotes` data type because quote rows are the dense dated market series. Bronze applies those planned windows to quotes, dividends, and splits through dataset strategies, and stores dividends and splits as dated Bronze rows beside quotes.

### Univariate Statistics Field Reference

The `univariate_statistics` row contains these fields. `README.md` keeps the longer user-facing semantics, ranges, units, and empirical bands; this contract table is the compact schema reference.

| Field | Short description |
| --- | --- |
| `isin` | Instrument ISIN identifier. |
| `exchange` | Listing exchange code. |
| `code` | Provider listing code or ticker. |
| `confidence_level` | Tail-risk confidence level used for VaR and Expected Shortfall. |
| `first_quote_date` | First quote date included in the listing window. |
| `last_quote_date` | Last quote date included in the listing window. |
| `quote_observation_count` | Count of quote rows for the listing. |
| `first_return_date` | First daily return date after the first valid quote. |
| `last_return_date` | Last daily return date. |
| `return_observation_count` | Count of daily return observations. |
| `start_adjusted_close` | First adjusted close in the quote window. |
| `end_adjusted_close` | Last adjusted close in the quote window. |
| `total_return` | Full-window simple return from first to last adjusted close. |
| `cagr` | Compound annual growth rate over the quote window. |
| `cumulative_log_return` | Sum of daily adjusted-close log returns. |
| `mean_log_return` | Arithmetic mean of daily log returns. |
| `median_log_return` | Median daily log return. |
| `min_log_return` | Worst daily log return. |
| `max_log_return` | Best daily log return. |
| `mean_simple_return` | Arithmetic mean of daily simple returns. |
| `median_simple_return` | Median daily simple return. |
| `min_simple_return` | Worst daily simple return. |
| `max_simple_return` | Best daily simple return. |
| `daily_log_return_std` | Sample standard deviation of daily log returns. |
| `daily_simple_return_std` | Sample standard deviation of daily simple returns. |
| `annualized_return` | Alias of annualized log return. |
| `annualized_log_return` | Mean daily log return multiplied by 252 trading days. |
| `annualized_simple_return` | Mean daily simple return multiplied by 252 trading days. |
| `annualized_geometric_return` | Geometric annual return derived from annualized log return. |
| `annualized_volatility` | Annualized daily log-return volatility. |
| `realized_variance` | Sum of squared daily log returns over the window. |
| `realized_volatility` | Square root of realized variance. |
| `downside_deviation` | Annualized downside deviation from negative daily log returns. |
| `sharpe_ratio` | Annualized log return divided by annualized volatility. |
| `sortino_ratio` | Annualized log return divided by downside deviation. |
| `var` | Historical daily-loss quantile at `confidence_level`. |
| `expected_shortfall` | Mean daily loss in the tail at or beyond VaR. |
| `tail_observation_count` | Number of tail observations used for Expected Shortfall. |
| `max_drawdown` | Worst peak-to-trough adjusted-close drawdown. |
| `positive_day_ratio` | Share of daily log returns greater than zero. |
| `log_price_slope` | Linear-regression slope of log adjusted close over quote order. |
| `trend_r_squared` | R-squared of the log-price trend regression. |
| `availability_reason` | Basic statistic availability status such as `ok` or insufficient returns. |
| `distribution_frequency` | Inferred distribution cadence from positive dividend events. |
| `distribution_events_per_year` | Annualized positive distribution event rate. |
| `last_distribution_date` | Latest positive distribution event date. |
| `distribution_observation_count` | Count of positive distribution events used for inference. |
| `quarantined_price_count` | Count of invalid price rows excluded by return-quality checks. |
| `non_positive_price_detected` | Whether a zero or negative price was detected. |
| `duplicate_date_detected` | Whether duplicate quote dates were detected. |
| `stale_price_detected` | Whether the stale-price quality gate fired. |
| `unexplained_gap_detected` | Whether unexplained quote-date gaps were detected. |
| `meets_min_history_252` | Whether the listing has at least 252 valid observations. |
| `meets_min_history_504` | Whether the listing has at least 504 valid observations. |
| `meets_min_history_756` | Whether the listing has at least 756 valid observations. |
| `production_eligible` | Whether the listing passes the current production-quality gate. |
| `data_quality_reason` | Main quality reason for eligibility or exclusion. |

## Portfolio Evaluation Outputs

Portfolio evaluation datasets belong in Gold because they are derived from validated Gold risk inputs and are intended for analysis, comparison, and target-weight selection. They are reproducible without EODHD credentials and do not mutate Bronze or Silver market data.

Gold evaluation datasets include:

- `evaluation/return_matrices/{evaluation_id}.parquet`: aligned long-format date, ISIN, exchange, code, and return rows used as the portfolio evaluation base.
- `evaluation/asset_metrics/{evaluation_id}.parquet`: observation counts, first and last return dates, annualized return, annualized volatility, downside deviation, Sharpe ratio, Sortino ratio, historical daily-loss VaR/CVaR, and `meets_min_history_252/504/756`/`production_eligible` minimum-history gates by listing. VaR and CVaR include their confidence level and tail observation count and use the same aligned return dates as the other asset metrics.
- `evaluation/portfolio_returns/{evaluation_id}.parquet`: weighted portfolio return and cumulative wealth series for candidate portfolios.
- `evaluation/drawdowns/{evaluation_id}/{portfolio_id}.parquet`: cumulative wealth, running peak, drawdown, drawdown duration, recovery duration, and recovery state by date.
- `evaluation/portfolio_metrics/{evaluation_id}.parquet`: portfolio-level return, volatility, Sharpe, Sortino, maximum drawdown, Calmar ratio, ulcer index, turnover, and post-cost metrics.
- `evaluation/frontier_points/{evaluation_id}.parquet`: target return, expected return, volatility, Sharpe ratio, feasibility status, and optimizer diagnostics for efficient-frontier points.

Portfolio variance, marginal risk contribution, diversification ratio, and risk-parity residual calculations in `founder.portfolio` (and `founder.evaluation`'s frontier volatility) fail closed instead of silently substituting zero for a missing or non-finite covariance element: `optimize_portfolio`, `hierarchical_risk_parity_weights`, `build_diversification_metric_rows`, and `build_risk_contribution_rows` raise a `ValueError` naming the missing/non-finite pair counts when the supplied covariance rows do not cover every required pair for the exact listing set. `build_optimizer_diagnostics` does not raise; instead it reports `optimizer_status="blocked_missing_covariance"` and `covariance_condition` of `missing_covariance`/`non_finite_covariance` with `portfolio_variance`/`objective_value` as `NaN`, so a blocked diagnostic can still be recorded without a crash. `founder.risk_model.RiskModelDiagnostics` (still a standalone, lake-independent library ahead of its PR59+ wiring) separately reports `non_finite_count`, `symmetry_residual`, `minimum_eigenvalue`, `production_eligible`, and `availability_reasons` computed purely from its own matrix diagnostics, never from whether a downstream optimizer happened to return weights.

`optimize_portfolio` accepts an explicit `mode` (`"production"` or `"baseline"`, default `"baseline"`). Whenever the exact grid enumeration for a Maximum Sharpe, Target Return, or Maximum Diversification request would exceed `MAX_EXACT_WEIGHT_CANDIDATES`, `mode="production"` raises a `candidate_limit_exceeded` error instead of silently substituting Equal Weight (these objectives remain grid-only comparison methods for now); `mode="baseline"` retains the deterministic Equal Weight fallback but every diagnostic (`build_optimizer_diagnostics`) reports it honestly: `requested_method` (the objective asked for) and `actual_method` (`equal_weight_fallback` when the limit was exceeded) diverge, `fallback_used=true`, `fallback_reason="candidate_limit_exceeded"`, and `production_eligible=false` regardless of mode when a fallback occurred. `build_optimizer_diagnostics` additionally persists `solver_name`, `solver_version`, `solver_status`, `convergence_status`, `constraint_residuals`, `bound_activity`, `iteration_count`, `numeric_tolerances`, and `risk_model_id` (empty until full risk-model wiring lands). Method detection (`founder.portfolio.resolve_actual_optimizer_method`) is a pure function of the objective, listing count, and grid step — never the resulting weights — so a genuine optimum that happens to equal Equal Weight is never mistaken for a hidden fallback.

`minimum_variance`, `risk_parity`, and `equal_risk_contribution` are solver-backed in `mode="production"` (PR60): `optimize_portfolio` routes them to `founder.portfolio_parts.solvers`, a hand-implemented pure-Python projected gradient descent solver (capped-simplex projection plus Armijo-style backtracking line search) — the repository intentionally has no numerical runtime dependency (pyarrow only), matching `founder.risk_model`'s hand-implemented Jacobi eigenvalue solver. These two objectives are therefore never subject to the grid candidate-limit guard in production mode; instead, `build_optimizer_diagnostics` reports `solver_name="projected_gradient_descent"`, the solver's real `iteration_count` and `convergence_status`, and `production_eligible=false` with `solver_status="solver_not_converged"` if the solver fails to converge within its iteration budget, so a non-convergent result is never mislabeled as a production weight. Diagnostics only ever claim solver provenance when the given weights numerically match the solver's own output for the exact same inputs — weights that came from elsewhere (e.g. a baseline grid result) are never misreported as a converged solver result. This PR60 solver operates on the same pairwise Gold covariance rows as the grid baseline; wiring `founder.risk_model`'s shrinkage/EWMA estimators (and a populated `risk_model_id`) through this boundary remains a follow-up.
- `evaluation/frontier_weights/{evaluation_id}.parquet`: long-format ISIN, exchange, code, and weight rows for each efficient-frontier point.
- `evaluation/backtests/{run_id}.parquet`: planned walk-forward train/test windows, requested objective, actual optimizer method executed (flags a candidate-limit equal-weight fallback separately from the requested objective), pre-cost and post-cost realized returns (geometrically compounded, not summed), consistently annualized realized volatility/Sharpe/Sortino, transaction cost, turnover, max drawdown, and a named walk-forward profile (`development` or `production`) with `production_eligible`/`availability_reason` fields. The `development` profile allows tiny fixture windows but is never production eligible; the `production` profile enforces minimum training history (504 observations), minimum test window (21 observations), a minimum completed-split count, and a stricter concentration limit before `production_eligible` can be true.
- `evaluation/backtest_weights/{run_id}.parquet`: long-format split, ISIN, exchange, code, and fitted weight rows for walk-forward history.
- `evaluation/rebalance_events/{run_id}.parquet`: one portfolio-level row per date with the pre-trade portfolio value (after that day's own-instrument drift, before any trade), turnover, transaction-cost estimate, post-cost return, resulting portfolio value, and cash remainder after the trade.
- `evaluation/rebalance_weights/{run_id}.parquet`: one row per date per instrument with pre-trade value, pre-trade weight, target weight, target value, and trade value. Each instrument drifts from its own simple return between rebalance dates; it never drifts from the blended portfolio return.
- `evaluation/tail_risk/{run_id}.parquet`: planned VaR, CVaR, confidence level, tail observation count, and tail scenario diagnostics.
- `weights/{objective}/{evaluation_id}.parquet`: selected target weights, constraints, and diagnostics for objectives such as equal weight, constrained minimum variance, risk parity, hierarchical risk parity, maximum diversification, and CVaR.
- `risk_contributions/{objective}/{evaluation_id}.parquet`: marginal, absolute, and percent risk contribution rows for risk-parity portfolios, including target risk budgets, per-asset residuals, portfolio variance, objective residual, and convergence status.
- `clusters/hierarchical_risk_parity/{evaluation_id}.parquet`: True Hierarchical Risk Parity recursive-bisection split rows (`hierarchical_risk_parity` objective), each with `cluster_id`, `left_cluster`/`right_cluster` membership, inverse-variance-weighted `cluster_variance`, `allocation`, the full quasi-diagonal `ordered_isins`, and `linkage_method`/`tie_breaking_policy`/`algorithm_version` diagnostics. The order is derived from single-linkage clustering over a correlation-distance matrix (`sqrt(0.5*(1-corr))`), not canonical ISIN order, so correlated assets end up adjacent before bisection. `founder.portfolio.hierarchical_risk_parity_baseline_weights`/`write_hierarchical_risk_parity_baseline` retain the pre-PR61 naive midpoint-split-by-canonical-order behavior for development and comparison only, always under the distinct `hierarchical_risk_parity_baseline` objective; that baseline must never be labeled `hierarchical_risk_parity` in a production-facing artifact.
- `clusters/hierarchical_risk_parity_linkage/{evaluation_id}.parquet`: the persisted single-linkage dendrogram itself -- one row per merge step with `step_index`, `left_cluster_id`/`right_cluster_id` (an ISIN for a leaf, `cluster-{id}` for a merged cluster), `distance`, `size`, and the same linkage diagnostics.
- `metrics/maximum_diversification/{evaluation_id}.parquet`: diversification ratio, portfolio volatility, and weighted asset-volatility diagnostics.

Historical Minimum CVaR (PR61's second objective, `minimum_cvar`) minimizes Conditional Value-at-Risk directly over the empirical historical loss distribution instead of a covariance matrix. `founder.portfolio.minimum_cvar_weights`/`write_minimum_cvar_portfolio` build a dense date-aligned return matrix (`founder.portfolio._aligned_return_matrix`, common dates across every requested listing only) and solve it with `founder.portfolio_parts.cvar.solve_minimum_cvar`, a hand-implemented pure-Python solver for the Rockafellar-Uryasev (2000) reformulation: an alternating scheme that recomputes the VaR threshold (`zeta`) exactly as the empirical quantile of the current weights' losses each iteration (a cheap sort, not a subgradient step) and takes one projected-subgradient step on the weights alone, projected onto the capped simplex via the same `project_capped_simplex` helper PR60's solvers use. As with the PR60 solvers, this objective is standalone rather than routed through `optimize_portfolio`/`build_optimizer_diagnostics` because it needs raw return scenarios, not a covariance matrix; `build_minimum_cvar_diagnostics` reports `solver_name="projected_subgradient_descent"`, `var`/`cvar`/`confidence_level`, `iteration_count`, and `convergence_status`, and — matching the same weights-provenance safeguard as PR60 — only claims solver provenance (`solver_status="feasible"`/`production_eligible=true`) when the given weights numerically match a fresh solve of the same inputs; otherwise it recomputes VaR/CVaR directly from the given weights and reports `solver_status="unverified"`/`production_eligible=false`. `minimum_cvar_weights` raises rather than returning weights when the solver does not converge within its iteration budget, or when fewer than two dates of common history are available across the requested listings. This objective currently has no turnover-awareness and no issuer/group concentration caps beyond the existing per-asset `max_weight`; those remain follow-up scope.

`founder.profiles` (PR63) adds versioned Defensive/Balanced/Income/Growth `ProfileContract`s (explicit objective sets, `PortfolioConstraints`, and `ProfileRiskLimits`) plus ensemble candidate construction. `build_balanced_ensemble_weights` computes the per-asset median of True HRP, Equal Risk Contribution, and a new `founder.portfolio.shrinkage_minimum_variance_weights` (Ledoit-Wolf shrinkage covariance from `founder.risk_model` fed into PR60's projected-gradient-descent solver with a larger iteration budget, since shrinkage covariance entries are typically smaller in magnitude than raw Gold covariance), normalizes, and projects onto the profile's final bounds. `evaluate_profile_candidate` never raises for expected fail-closed conditions (insufficient history, solver non-convergence, incomplete covariance); it reports an explicit `infeasible` status with reasons instead, alongside Equal Weight and Inverse Volatility baseline portfolio-variance comparisons and a deterministic `profile_candidate_id` (`founder.contract_versioning.stable_contract_id` over profile version, ISINs, objective set, and constraints). The Income profile's `min_net_income`/`max_nav_erosion` risk limits always report `unavailable`: they require the after-tax cash-flow stack (PR62A is merged; PR62B-PR62F remain open), never an invented income figure. Group and issuer concentration limits are out of scope until group/issuer metadata is plumbed through the lake. `write_profile_candidate` persists to the existing `weights/profile_{name}/{evaluation_id}.parquet` path (reusing `gold_optimized_weights`) with the full candidate diagnostics embedded.

`founder.scorecard` (PR64) compares multiple candidate objectives on identical pinned walk-forward windows, rebalance policy, and transaction costs by reusing `founder.evaluation.build_walk_forward_backtest` per candidate (no separate walk-forward engine). `build_model_comparison_scorecard` reports one row per candidate: `median_out_of_sample_return`/`adverse_out_of_sample_return`, `median_sharpe_ratio`/`median_sortino_ratio`, historical `var`/`cvar` (via `founder.portfolio_parts.cvar.historical_var_and_cvar` over the split-level realized returns), `whole_period_max_drawdown`/`recovery_duration_splits` (via `founder.evaluation.build_drawdowns` over the concatenated out-of-sample split sequence), `median_concentration`/`median_weight_variance`, and a deterministic `model_comparison_id`. Ranking is `median_sharpe_ratio` across completed splits, never a single split's or an in-sample return, with a candidate-id tie-break; a candidate whose request is infeasible (e.g. an unsupported objective, or a profile's minimum-window requirement not met) is reported `status="blocked"` with `rank=None` rather than aborting the whole comparison. `income_quality` always reports `unavailable` pending PR62E.

`founder.stress` (PR65) adds scenario analysis for an already-computed candidate portfolio (weights plus the aligned return matrix/covariance they were built from), returning `ScenarioResult` dataclasses rather than a new lake dataset (persistence is a documented follow-up once a concrete caller needs it). `historical_stress_scenario` replays the worst-drawdown window of a requested length, found by `detect_worst_drawdown_window` deterministically within the caller's own supplied data -- never a hardcoded or externally-asserted crash date. `distribution_cut_scenario` applies a multiplicative return shock to selected ISINs. `block_bootstrap_scenarios` resamples historical returns in contiguous, seeded blocks (`random.Random(seed)`, no numpy/scipy) to produce reproducible synthetic return paths. `correlation_convergence_scenario` blends every pairwise correlation toward 1 by a `[0, 1]` factor (representing lost diversification in a crisis) and `covariance_perturbation_scenario` uniformly scales the covariance matrix; both have no return series to replay, so they report `parametric_var_cvar` -- a hand-implemented zero-mean Gaussian VaR/CVaR using Peter Acklam's rational inverse-normal-CDF approximation -- from the stressed portfolio volatility instead of a historical VaR/CVaR. `build_sensitivity_summary` aggregates median/worst-case compounded return, max drawdown, and CVaR across every scenario result for one candidate. Alternate training windows and rebalance schedules are already covered by `founder.evaluation.build_walk_forward_backtest`/`founder.scorecard`'s existing rolling/expanding window support and are not re-implemented here.

`founder.recommendation` (PR66) compares already-computed `founder.profiles.evaluate_profile_candidate` outputs into a single deterministic report. `build_candidate_report` explains one candidate (inclusion/exclusion reasons, constraint violations, concentration as the max single weight, turnover versus an optional current-position snapshot, disadvantages) with optional `scorecard_row`/`sensitivity_summary` traceability from `founder.scorecard`/`founder.stress`. `build_recommendation_report` selects `best_defensive`/`best_diversified`/`best_income`/`best_total_return`/`best_ensemble` candidates (each `None` when no included candidate qualifies, never a fabricated pick), always includes the fixed `NO_GUARANTEE_DISCLAIMER` and `requires_user_approval=True`, and derives a deterministic `recommendation_id` from the candidate ids, the optional current-position snapshot, and `report_template_version`. `income_quality`/`cost_quality` always report `unavailable` pending PR62E/PR62D; this module never invents an excluded-instrument or data-quality-warning reason, it only propagates reasons the caller supplies from an upstream gate. `render_recommendation_markdown` produces deterministic, HTML-escaped Markdown (`<`, `>`, `&`, `|` are escaped).

`founder.multivariate_statistics.write_production_multivariate_statistics`/`ProductionMultivariateConfig` (PR70) is an additive production-mode entry point alongside the existing deterministic-baseline `write_multivariate_statistics` (PR69). It refuses (raises `ValueError`) rather than falling back to a baseline when: the selection's Silver quote history fails `founder.return_quality.evaluate_quote_quality`'s production data-quality gate (invalid prices, insufficient history, stale prices, unexplained gaps); the aligned return matrix is empty; `founder.risk_model.estimate_risk_model`'s diagnostics are not `production_eligible`; a requested `founder.profiles` candidate is `infeasible`; or a candidate's baseline comparison is empty. On success it writes weight rows for every requested profile via `founder.profiles.write_profile_candidate` -- the Balanced profile's candidate already includes True HRP, Equal Risk Contribution, and shrinkage Minimum Variance ensemble rows through the existing `build_balanced_ensemble_weights` composition, so no separate wiring was needed -- and returns a deterministic `production_adapter_id` derived from selection membership, the quality policy name, risk-model estimator/algorithm version, requested profile names, profile versions, and the constraint set.

`founder.multivariate_statistics.write_multivariate_recommendation`/`MultivariateRecommendationConfig` (PR71) runs the PR70 production adapter first, then adds `founder.scorecard` walk-forward traceability for profiles whose single underlying objective is scorecard-compatible (only `growth` -> `equal_risk_contribution` today; `defensive`'s shrinkage Minimum Variance, `income`'s Minimum CVaR, and `balanced`'s multi-objective ensemble report `scorecard_rank=None` rather than a fabricated comparison) and `founder.stress` sensitivity summaries (a historical stress replay plus seeded block-bootstrap scenarios) for every profile candidate, before comparing all candidates via `founder.recommendation.build_recommendation_report` into one deterministic report. Income quality, sustainable income, NAV erosion, and income efficiency always report `unavailable`: they require the after-tax cash-flow stack (PR62E), which remains open, and are never computed from an invented figure.

`founder.multivariate_statistics.write_multivariate_trading_handoff`/`TradingHandoffConfig` (PR72) runs the PR71 recommendation report first, then rejects (raises `ValueError`) by default unless `approved_comparison_slot` (e.g. `"best_ensemble"`) is explicitly supplied and resolves to an included candidate -- this module never infers or decides approval on the user's behalf. When approved: it includes per-ISIN current-versus-target weight differences when `current_weights` is supplied; links a deterministic Flatex export at `paths.trading_flatex_export(evaluation_id, approved_candidate_id)` (`trading/flatex/{evaluation_id}-{portfolio_id}.csv`, reusing the existing `founder.trading.prepare_flatex_orders`/`write_flatex_orders`) when `current_prices` and a positive `portfolio_value` are supplied; and reports `drift_status` (from the transition-plan deltas versus `drift_threshold`), `risk_status` (the approved profile's `risk_limits.max_cvar` versus the PR65 sensitivity summary's worst-case CVaR), and `stale_data_status` (from `founder.return_quality.evaluate_quote_quality`). `distribution_cut_status`/`nav_erosion_status` always report `unavailable` pending PR62E. The deterministic `handoff_id` derives from the recommendation id, approved candidate id, current-position snapshot, transition plan, monitoring policy id, and report template version.

`founder.multivariate_statistics.write_multivariate_statistics` supports explicit selection-cache consumption (PR75) through `MultivariateStatisticsConfig.use_selection_statistics_cache=True` and CLI flag `--use-selection-statistics-cache`. In that mode `selection_id` is required. The command writes missing/stale selected listing returns to `gold/returns`, refreshes univariate rows through the PR73 cache-aware writer, refreshes bucketed bivariate rows through the PR73 delta writer, validates the PR74 `selection_statistics_view`, reconstructs selected covariance/correlation inputs from cached univariate and bivariate rows, and then runs portfolio analytics only for that selected membership. The deterministic `portfolio_run_id` is derived from the selection id, source module, Selection Statistics View id, bivariate version, evaluation id, optimizer objectives, constraints, frontier targets, walk-forward, rebalance, transaction-cost, and tail-risk parameters. If a completed cache manifest for that id exists and every referenced artifact still exists, the command returns the existing summary with `cache_status=portfolio_reused` instead of rewriting portfolio artifacts.

Evaluation outputs should include explicit run ids, objective names, annualization settings, risk-free-rate assumptions, constraints, and input dataset identifiers so results can be compared and rebuilt deterministically.

Current portfolio evaluation writes equal-weight or explicit long-only cash-free weight results. Recomputing the same portfolio id replaces that portfolio's return and metric rows while preserving other portfolios in the same evaluation id. Current portfolio optimization writes deterministic equal-weight, constrained minimum-variance, maximum-Sharpe comparison, target-return minimum-variance, risk-parity, hierarchical-risk-parity, and maximum-diversification target weights to `weights/{objective}/{evaluation_id}.parquet`; risk-parity, HRP, and diversification runs also write focused diagnostics.

## How This Fits The Onboarding Flow

Use the three public modules to write and reuse the current contracts:

```bash
uv run founder search "UCITS ETF"
uv run founder metadata-filter --name-contains "UCITS ETF" --selection-name ucits-etf
uv run founder univariate-statistics --root lake
uv run founder bivariate-statistics --root lake
```

`metadata-filter` reads only `lake/reference/all_isins/all_isins.parquet`. At least one `--where` or `--name-contains` filter is required, and repeated filters are conjunctive:

| CLI filter | Repeatable | Applies to | Contract |
| --- | --- | --- | --- |
| `--where <field><operator><value>` | Yes | `isin`, `exchange`, `code`, `name`, `instrument_type`, `country`, `currency`, `source_exchange`, `fetched_at` | Uses the persisted `all_isins` column values without fetching or computing metrics. |
| `--name-contains <text>` | Yes | `name` | Case-insensitive substring search; equivalent to requiring the name to contain every provided fragment. |
| `--selection-name <name>` | No | Selection id | Changes the readable selection-id prefix only; membership is still determined by the filters. |
| `--root <path>` | No | Lake root | Reads reference metadata and writes `silver/metadata_filter/{selection_id}/isins.parquet` plus `manifest.json`. |
| `--debug` | No | Logs | Enables verbose command logging. |

Supported `--where` operators are `=`, `!=`, `~`, `>`, `>=`, `<`, and `<=`. The `~` operator is a case-insensitive substring match. Numeric operators parse both sides as numbers and should only be used for numeric-like metadata values.

Statistics outputs use stable listing and pair paths so later metadata selections can reuse unchanged calculations.
