# Lake Contracts

Last reviewed: 2026-07-13

## Table Of Contents

- [Layers](#layers)
- [Core Tables](#core-tables)
- [Portfolio Evaluation Outputs](#portfolio-evaluation-outputs)
- [How This Fits The Onboarding Flow](#how-this-fits-the-onboarding-flow)

Founder uses deterministic local lake artifacts under a `LakePaths` root. Table paths ending in `.parquet` are physical Apache Parquet files written through `founder.table_io`; JSON and CSV artifacts keep their native formats.

Read this after [ARCHITECTURE.md](../ARCHITECTURE.md) and before changing Search, Bronze, Gold, or storage code. Read [docs/search_bronze_workflow.md](search_bronze_workflow.md) for executable examples that use these contracts.

## Layers

- Bronze stores raw or near-raw EODHD search, quote, dividends, and splits payloads.
- Silver stores normalized search candidates, canonical universe rows, and quote rows with one file per exchange and ISIN.
- Gold stores adjusted-close returns, correlation, covariance, portfolio evaluation, and target-weight rows.
- Silver also stores operational datasets for active universe pointers, bronze plans, bronze runs, coverage, errors, and dry-run summaries.

Bronze quote rows are partitioned by exchange and quote year, with one file per ISIN:

```text
bronze/quotes/{exchange}/{year}/{ISIN}.parquet
```

Silver and Gold remove the year directory so all years for an ISIN stay in one file:

```text
silver/quotes/{exchange}/{ISIN}.parquet
gold/returns/{exchange}/{ISIN}.parquet
gold/correlation/{exchange}/{ISIN}.parquet
gold/covariance/{exchange}/{ISIN}.parquet
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
- `returns`, `correlation`, and `covariance`: Gold risk-input tables built from validated Silver quote rows and written as per-ISIN files without year partitions.

Gap-aware planning discovers missing windows from the `quotes` data type because quote rows are the dense dated market series. Bronze applies those planned windows to quotes, dividends, and splits through dataset strategies, and stores dividends and splits as dated Bronze rows beside quotes.

## Portfolio Evaluation Outputs

Portfolio evaluation datasets belong in Gold because they are derived from validated Gold risk inputs and are intended for analysis, comparison, and target-weight selection. They should be reproducible without EODHD credentials and should not mutate Bronze or Silver market data.

Planned Gold evaluation datasets include:

- `evaluation/asset_metrics.parquet`: observation counts, first and last return dates, annualized return, annualized volatility, downside deviation, Sharpe ratio, and Sortino ratio by listing.
- `evaluation/portfolio_returns/{run_id}.parquet`: weighted portfolio return series for candidate portfolios.
- `evaluation/drawdowns/{portfolio_id}.parquet`: cumulative wealth, running peak, drawdown, drawdown duration, and recovery state by date.
- `evaluation/portfolio_metrics/{run_id}.parquet`: portfolio-level return, volatility, Sharpe, Sortino, maximum drawdown, Calmar ratio, ulcer index, turnover, and post-cost metrics.
- `evaluation/frontier_points/{run_id}.parquet`: target return, expected return, volatility, Sharpe ratio, feasibility status, and optimizer diagnostics for efficient-frontier points.
- `evaluation/frontier_weights/{run_id}.parquet`: long-format ISIN, exchange, and weight rows for each efficient-frontier point.
- `evaluation/backtests/{run_id}.parquet`: walk-forward train/test windows, fitted objective, realized out-of-sample metrics, and drawdown metrics.
- `evaluation/rebalance_events/{run_id}.parquet`: rebalance dates, pre-trade weights, target weights, turnover, transaction-cost estimates, and post-cost returns.
- `evaluation/tail_risk/{run_id}.parquet`: VaR, CVaR, confidence level, tail observation count, and tail scenario diagnostics.
- `weights/{objective}/{run_id}.parquet`: selected target weights for objectives such as equal weight, constrained minimum variance, risk parity, hierarchical risk parity, maximum diversification, and CVaR.

Evaluation outputs should include explicit run ids, objective names, annualization settings, risk-free-rate assumptions, constraints, and input dataset identifiers so results can be compared and rebuilt deterministically.

## How This Fits The Onboarding Flow

Use the deterministic mocked pipeline to see these contracts written end to end:

```bash
uv run founder dry-run --root lake
```

The dry run is safe to repeat and rewrites the same sample artifacts deterministically.