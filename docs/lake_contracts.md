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
- `univariate_statistics`: one Gold row per ISIN listing, written to a stable listing path that does not include the search run id. Rows include return, volatility, downside, drawdown, trend, and tail-risk summaries that can be reused when later search lists include the same listing. Rows also include `quarantined_price_count`, `non_positive_price_detected`, `duplicate_date_detected`, `stale_price_detected`, `unexplained_gap_detected`, `meets_min_history_252/504/756`, `production_eligible`, and `data_quality_reason` from the shared `founder.return_quality` gate.
- `bivariate_statistics`: one Gold row per pair of distinct ISIN listings, written to deterministic `version`/`bucket` Parquet files (`bucket = left_id % bucket_count`) instead of one file per pair, so file count grows sublinearly with pair count. Rows include stable listing keys, stable pair key, the `version` and `bucket` they were written under, common-date range, common observation count, Pearson correlation, Spearman correlation, covariance, each side's variance, and directional beta values. A universe whose theoretical pair count exceeds an explicit `max_pair_count` guard (default 500,000) is rejected before any pair is enumerated or submitted to a worker, and default worker count is capped by policy (default 4) rather than scaling with all visible CPU cores. Pair-plan diagnostics (listing count, theoretical pair count, mode, chunk size, worker count, bucket count, and rejection reason if any) are persisted as a `bivariate-statistics-plan` job manifest for every call. A bucket file is only rewritten when at least one of its pairs changed or was added/removed; unaffected buckets are left untouched, and a bucket whose stored `bucket` field does not match its own file position is treated as corrupt and never used as a cache hit. `founder.bivariate_statistics.read_legacy_bivariate_pair` remains available to read historical pre-C03 one-file-per-pair artifacts (`gold/bivariate_statistics/{left_exchange}/{left_ISIN}/{left_code}/{right_exchange}__{right_ISIN}__{right_code}.parquet`) during the migration window; new writes never use that layout.
- `correlation_edges`: Gold pair-search table for scalable correlation filtering. Rows store one upper-triangle pair where `left_id < right_id`, the listing identifiers, metric name, input version, common date range, common observation count, and correlation value. Same-ISIN pairs are skipped even when the listings use different exchanges or codes. Supported metrics are `pearson` and `spearman`; Pearson values are computed with an incremental online correlation algorithm, and Spearman values use an approximative online rank-score correlation. Edge values use only the common date intersection of the two return series. Bucket files are grouped by `left_id % bucket_count` so later DuckDB or Polars scans can filter relevant partitions instead of opening a dense matrix. Building edges without a `min_abs_correlation`/`top_k_per_left` filter (dense mode) is subject to the same `max_pair_count` scale guard as `bivariate_statistics`.
- `features`: per-listing Gold asset feature rows with first and last quote dates, quote and return observation counts, total return, mean return, volatility, and maximum drawdown.
- `gold_runs`: per-listing Gold completion manifest with status, input last quote date, global input snapshot date, listing count, and completion time. Gold uses this to resume the per-ISIN job without reprocessing completed listings when the input snapshot has not changed.

Bronze, Silver, and Gold default to concurrency `2`. Silver writes per-listing quote files with two worker threads by default, while Gold uses two worker processes for heavier per-ISIN risk outputs.

Gold input builds are designed for large ETF universes. The CLI defaults to two parallel Gold workers, processes one ISIN listing per worker task, and computes each symmetric correlation/covariance pair only once before writing per-left-listing files. If any listing date or the listing count changes, the global input snapshot changes and Gold recomputes the affected matrix outputs instead of trusting stale pair statistics.

Gap-aware planning discovers missing windows from the `quotes` data type because quote rows are the dense dated market series. Bronze applies those planned windows to quotes, dividends, and splits through dataset strategies, and stores dividends and splits as dated Bronze rows beside quotes.

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
- `clusters/hierarchical_risk_parity/{evaluation_id}.parquet`: deterministic HRP split rows with cluster variance, allocation, and ordering metadata.
- `metrics/maximum_diversification/{evaluation_id}.parquet`: diversification ratio, portfolio volatility, and weighted asset-volatility diagnostics.

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
