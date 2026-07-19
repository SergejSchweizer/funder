# Founder

Last reviewed: 2026-07-13

## Table Of Contents

- [Onboarding Path](#onboarding-path)
- [Current Facts](#current-facts)
- [ETF Discovery Statistics](#etf-discovery-statistics)
- [Intended Workflow](#intended-workflow)
- [Portfolio Objective](#portfolio-objective)
- [Portfolio Analysis And Evaluation Plan](#portfolio-analysis-and-evaluation-plan)
- [Documentation Map](#documentation-map)
- [Five ISIN Module Architecture](#five-isin-module-architecture)
- [Scheduled Founder Cron](#scheduled-founder-cron)
- [EODHD Request Safety](#eodhd-request-safety)
- [Logging And Debugging](#logging-and-debugging)
- [Quality Gates](#quality-gates)
- [Documentation Refresh](#documentation-refresh)
- [Keep This README Up To Date](#keep-this-readme-up-to-date)

Founder is a fund portfolio builder for exchange-traded funds. The project goal is to analyze EODHD end-of-day quotes for multiple thousands of ETFs and build risk-aware fund portfolio weights.

The primary data source is the EODHD subscription for EOD Historical Data. Flatex will be used as the trading exchange/broker venue for turning portfolio weights into executable ETF trades. Local API credentials must stay in ignored secret files such as `.secrets/eodhd.yaml` or `.env.local`; never commit real tokens.

## Onboarding Path

New contributors should read the documentation in this order:

1. Start here to understand the goal, data source, current facts, and local commands.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the module diagram and one-paragraph purpose of each package module.
3. Read [CONTRACTS.md](CONTRACTS.md) before changing paths, schemas, or storage formats.
4. Check [RISKS.md](RISKS.md), [DECISIONS.md](DECISIONS.md), and [BACKLOG.md](BACKLOG.md) before opening a PR-sized change.
5. Follow [AGENTS.md](AGENTS.md) for workflow rules and PR status tracking; use [GATES.md](GATES.md) for quality gates and merge policy.

## Current Facts

- The local Python environment uses Python 3.14.5 in `.venv/`.
- The main market data source is the EODHD subscription for EOD Historical Data.
- The intended trading venue/broker is Flatex.
- `fetch_all_isins` enumerates EODHD exchange symbol lists and stores the complete ISIN-bearing metadata universe once under `lake/reference/all_isins/`.
- `metadata_filter` and `univariate_filter` create referencable selections from that reference metadata or from Gold univariate statistics.
- Portfolio loads should use explicit persisted selections, not ad hoc discovery files.
- EODHD HTTP requests are paced by the shared client and retry rate-limit responses with `Retry-After` support.

## ETF Discovery Statistics

The `UCITS ETF` discovery set contains EODHD listings, not yet deduplicated portfolio instruments. Multiple exchange listings can share the same ISIN, so optimization must deduplicate or choose primary listings before building weights.

- Total listings: 8,165.
- Type split: 8,063 `ETF` rows and 102 `FUND` rows.
- Exchanges represented: 26.
- Countries represented: 21.
- Currencies represented: 16.
- Rows with ISIN: 6,660.
- Rows missing ISIN: 1,505.
- Unique non-empty ISINs: 3,104.
- Canonical no-duplicate-ISIN universe: 3,104 rows.
- Canonical selections from `XETRA`: 1,759.
- Canonical fallback selections from other exchanges: 1,345.

Top exchanges by listing count:

| Exchange | Listings |
| --- | ---: |
| XETRA | 2,569 |
| LSE | 2,091 |
| F | 1,123 |
| SW | 1,038 |
| PA | 570 |
| AS | 291 |
| PINK | 107 |
| EUFUND | 102 |
| MU | 73 |
| OTCGREY | 62 |

Top countries by listing count:

| Country | Listings |
| --- | ---: |
| Germany | 3,860 |
| UK | 2,091 |
| Switzerland | 1,035 |
| France | 574 |
| Netherlands | 290 |
| USA | 170 |
| Unknown | 97 |

Top currencies by listing count:

| Currency | Listings |
| --- | ---: |
| EUR | 4,843 |
| USD | 1,613 |
| GBX | 628 |
| GBP | 594 |
| CHF | 428 |

Top canonical exchanges after one-row-per-ISIN selection:

| Exchange | Canonical ISINs |
| --- | ---: |
| XETRA | 1,759 |
| LSE | 626 |
| SW | 292 |
| PA | 230 |
| F | 114 |
| AS | 66 |

## Intended Workflow

1. Discover ETF and fund instruments from EODHD without committing credentials.
2. Deduplicate the universe to one canonical listing per ISIN, preferring `XETRA` when available.
3. Fetch Bronze end-of-day quotes for the latest `metadata_filter` selection with `fetch-all-quotes`.
4. Build Silver quotes into a reproducible local dataset.
5. Validate coverage, missing dates, currencies, identifiers, and duplicate listings.
6. Estimate return and risk inputs from validated quote history.
7. Compare risk-aware portfolio candidates and build selected target weights under explicit constraints.
8. Report weights, assumptions, coverage gaps, and validation results.
9. Export approved target weights into Flatex trade-preparation rows.

## Portfolio Objective

The initial production optimization objective is constrained minimum portfolio variance:

$$
\min_w \; w^T \Sigma w
$$

Subject to constraints that will be made explicit before implementation, such as:

- weights sum to 1;
- long-only or bounded weights;
- maximum concentration per ETF, issuer, currency, country, or asset class;
- minimum quote-history coverage;
- duplicate listing and duplicate ISIN handling.

This objective is intentionally risk-first because ETF expected-return estimates are noisy and many UCITS ETF candidates are highly correlated.

## Portfolio Analysis And Evaluation Plan

Founder aims to compare optimization techniques with reproducible Gold datasets before any target weights are used for trading. The evaluation layer consumes Gold daily adjusted-close log returns, `ln(P_t / P_{t-1})`, and should not call EODHD or mutate Bronze and Silver market data.

Portfolio analysis and evaluation computations include:

- aligned return matrices by date and listing;
- asset metrics such as observation count, mean return, annualized return, annualized volatility, downside deviation, Sharpe ratio, Sortino ratio, and historical daily-loss CVaR at an explicit confidence level;
- portfolio return series, cumulative wealth, drawdown series, maximum drawdown, drawdown duration, recovery duration, Calmar ratio, and ulcer index;
- efficient-frontier points and long-format frontier weights;
- constrained minimum-variance, maximum-Sharpe comparison, and target-return minimum-variance weights;
- risk parity and equal-risk-contribution diagnostics;
- hierarchical risk parity clusters, ordering, and weights;
- maximum-diversification ratio and target weights;
- walk-forward backtests with rolling or expanding train/test windows;
- rebalancing simulations with turnover, transaction-cost estimates, and post-cost returns;
- historical VaR, CVaR, tail scenario diagnostics, and optional CVaR-minimizing weights.

The first trusted portfolio candidates should be constrained minimum variance and risk parity, with hierarchical risk parity and maximum diversification as robust alternatives for larger ETF universes. Maximum Sharpe should be treated as a comparison technique until the expected-return model is deliberately chosen and tested out of sample.

The current refactor target keeps portfolio optimization downstream from the ISIN data modules. Portfolio optimization remains analysis work and is not exposed as a first-class module in this cut.

## Documentation Map

- [ARCHITECTURE.md](ARCHITECTURE.md) explains how modules connect and where responsibilities live.
- [CONTRACTS.md](CONTRACTS.md) defines lake layers and table contracts.
- [GATES.md](GATES.md) documents GitHub quality gates, branch protection, auto-merge, shards, and local validation commands.
- [DECISIONS.md](DECISIONS.md) records why durable technical choices were made.
- [RISKS.md](RISKS.md) tracks active project risks and mitigations.
- [BACKLOG.md](BACKLOG.md) tracks PR-sized work and implementation status.
- [AGENTS.md](AGENTS.md) defines agent workflow rules and generated project-history risks.

## Five ISIN Module Architecture

Founder's ISIN architecture target is organized around five deterministic modules:

```text
fetch_all_isins
  -> metadata_filter
  -> univariate_statistics
  -> univariate_filter
  -> bivariate_statistics
```

`fetch_all_isins` is the only source of the full EODHD ISIN universe. It refreshes an irregularly updated all-ISIN dataset and writes it once for every later module:

```bash
uv run founder fetch-all-isins
```

`fetch-all-quotes` is the quote refresh module. It reads the latest persisted `metadata_filter` selection, fetches EODHD quotes plus companion dividends and splits by default, writes Bronze inputs, rebuilds Silver quotes, and updates coverage manifests:

```bash
uv run founder fetch-all-quotes
```

Available `fetch-all-quotes` options:

```text
--debug
  Write verbose DEBUG logs.

--root <path>
  Lake root to write to. Defaults to lake.

--run-id <id>
  Optional stable run id. Defaults to fetch-all-quotes plus the end date.

--start-date <YYYY-MM-DD>
  Optional first quote date. Empty means full provider history.

--end-date <YYYY-MM-DD>
  Optional last quote date. Defaults to today.

--limit <n>
  Optional maximum approved listings to fetch.

--isin <ISIN>
  Fetch only one ISIN from the latest metadata-filter selection.

--no-gap-aware
  Disable Silver-based gap planning and request the whole requested date window.

--no-raw-datasets
  Do not fetch companion raw dividends and splits datasets.

--concurrency <workers>
  Worker thread count for EODHD requests and Silver writes. Defaults to 2.
```

`metadata_filter` reads only the all-ISIN source, applies conjunctive metadata predicates, and writes a hash-addressable selection with `isins.parquet` and `manifest.json`:

```bash
uv run founder metadata-filter --where instrument_type=ETF --where currency=EUR --where exchange=XETRA
uv run founder metadata-filter --name-contains "UCITS ETF"
```

Available `metadata-filter` options:

```text
--debug
  Write verbose DEBUG logs.

--root <path>
  Lake root to read from. Defaults to lake.

--where <predicate>
  Add one conjunctive predicate. Repeat this option for multiple predicates.

--name-contains <text>
  Case-insensitive text search in the instrument name. Repeat this option to require multiple name fragments.

--selection-name <name>
  Optional stable human-readable name used in the generated selection id.
```

At least one `--where` or `--name-contains` option is required. All filters are conjunctive.

`metadata-filter` CLI filter reference:

| CLI filter | Repeatable | Applies to | Semantics | Example |
| --- | --- | --- | --- | --- |
| `--where <field><operator><value>` | Yes | Any `all_isins` metadata field listed below. | Adds one predicate; all predicates must match. Text comparisons are exact except `~`; numeric operators parse both sides as numbers. | `--where instrument_type=ETF` |
| `--name-contains <text>` | Yes | `name` | Case-insensitive substring search. Repeating it requires every fragment to occur in the name. Equivalent to adding `name~<text>` predicates. | `--name-contains "UCITS ETF"` |
| `--selection-name <name>` | No | Selection id only | Stable human-readable prefix for the generated selection id. It does not change membership. | `--selection-name ucits-etf` |
| `--root <path>` | No | Lake location | Reads `reference/all_isins/all_isins.parquet` below this root and writes the selection below `silver/metadata_filter/`. | `--root lake` |
| `--debug` | No | Logging | Enables verbose DEBUG logs for the command. | `--debug` |

Supported predicate operators:

```text
field=value      exact text match
field!=value     exact text mismatch
field~value      case-insensitive substring match
field>value      numeric greater-than
field>=value     numeric greater-than-or-equal
field<value      numeric less-than
field<=value     numeric less-than-or-equal
```

Filterable metadata fields are the `all_isins` columns:

| Field | Type | Typical use with `metadata-filter` |
| --- | --- | --- |
| `isin` | Text | Select one ISIN or exclude a known ISIN: `--where isin=IE0000000001`. |
| `exchange` | Text | Restrict to one listing exchange: `--where exchange=XETRA`. |
| `code` | Text | Restrict to one exchange-local symbol/code: `--where code=SXR8`. |
| `name` | Text | Filter by fund or instrument name; prefer `--name-contains` or `--where name~UCITS`. |
| `instrument_type` | Text | Restrict instrument class, for example `--where instrument_type=ETF`. |
| `country` | Text | Restrict country metadata when EODHD provides it: `--where country=DE`. |
| `currency` | Text | Restrict listing currency: `--where currency=EUR`. |
| `source_exchange` | Text | Restrict the EODHD exchange list that produced the row: `--where source_exchange=XETRA`. |
| `fetched_at` | ISO timestamp text | Audit or advanced snapshot filtering. Text operators work; numeric operators are not appropriate. |

`univariate_statistics` builds reusable per-ISIN statistics from validated Silver quote files. Returns are daily log returns, `ln(P_t / P_{t-1})`, based on adjusted close:

```bash
uv run founder univariate-statistics
```

`univariate_statistics` only runs for the latest persisted `metadata_filter` selection. It does not scan every Silver quote file by default. Use `--selection-id <metadata_filter_selection_id>` only when intentionally rebuilding an older metadata selection.

Univariate Statistics parallelizes per-listing work across all CPU cores visible to the system by default. Use `--concurrency <workers>` to cap worker processes, for example `--concurrency 1` for deterministic single-process debugging.

`univariate_filter` reads the univariate statistics table, applies conjunctive metric predicates, and writes the same referencable selection shape as `metadata_filter`:

```bash
uv run founder univariate-filter --where sharpe_ratio>0 --where sortino_ratio>0 --where max_drawdown>-0.3
```

Available `univariate-filter` options:

```text
--debug
  Write verbose DEBUG logs.

--root <path>
  Lake root to read from. Defaults to lake.

--where <predicate>
  Required. Add one conjunctive predicate. Repeat this option for multiple predicates.

--selection-name <name>
  Optional stable human-readable name used in the generated selection id.
```

Supported predicate operators are the same as `metadata-filter`:

```text
field=value      exact text match
field!=value     exact text mismatch
field~value      case-insensitive substring match
field>value      numeric greater-than
field>=value     numeric greater-than-or-equal
field<value      numeric less-than
field<=value     numeric less-than-or-equal
```

Filterable univariate fields are the `univariate_statistics` columns:

```text
isin
exchange
code
confidence_level
first_quote_date
last_quote_date
quote_observation_count
first_return_date
last_return_date
return_observation_count
start_adjusted_close
end_adjusted_close
total_return
cagr
cumulative_log_return
mean_log_return
median_log_return
min_log_return
max_log_return
mean_simple_return
median_simple_return
min_simple_return
max_simple_return
daily_log_return_std
daily_simple_return_std
annualized_return
annualized_log_return
annualized_simple_return
annualized_geometric_return
annualized_volatility
realized_variance
realized_volatility
downside_deviation
sharpe_ratio
sortino_ratio
var
expected_shortfall
tail_observation_count
max_drawdown
positive_day_ratio
log_price_slope
trend_r_squared
availability_reason
distribution_frequency
distribution_events_per_year
last_distribution_date
distribution_observation_count
```

Univariate feature semantics, ranges, and units. The empirical column is computed from the current local `lake/gold/univariate_statistics` snapshot with 1,759 rows. It is a descriptive `mean +/- 3 std` band and is not clipped to the valid technical range:

| Feature | Meaning | Range | Unit | Empirical mean [mean - 3 std, mean + 3 std] |
| --- | --- | --- | --- | --- |
| `isin` | Instrument ISIN identifier. | Text. | Identifier | n/a |
| `exchange` | Listing exchange code. | Text. | Identifier | n/a |
| `code` | EODHD listing code/ticker. | Text. | Identifier | n/a |
| `confidence_level` | Tail-risk confidence level used for `var` and `expected_shortfall`. | `0 < x < 1`; default `0.975`. | Ratio | `0.975000 [0.975000, 0.975000]` |
| `first_quote_date` | First adjusted-close quote date used. | ISO date or empty only if input is invalid. | Date | n/a |
| `last_quote_date` | Last adjusted-close quote date used. | ISO date or empty only if input is invalid. | Date | n/a |
| `quote_observation_count` | Number of quote rows for the listing. | Integer `>= 1`. | Rows | `2142.04 [-2257.06, 6541.13]` |
| `first_return_date` | First daily return date after the first quote. | ISO date, or empty when no return exists. | Date | n/a |
| `last_return_date` | Last daily return date. | ISO date, or empty when no return exists. | Date | n/a |
| `return_observation_count` | Number of daily return observations. | Integer `>= 0`. | Rows | `2141.04 [-2258.06, 6540.13]` |
| `start_adjusted_close` | First adjusted close in the quote window. | Price value; normally `> 0`. | Quote currency | `36.4431 [-243.38, 316.27]` |
| `end_adjusted_close` | Last adjusted close in the quote window. | Price value; normally `> 0`. | Quote currency | `71.1315 [-313.50, 455.76]` |
| `total_return` | Full-period simple return, `end_adjusted_close / start_adjusted_close - 1`. | `[-1, +inf)` for positive start prices; `0` when start price is non-positive. | Return ratio | `1.1820 [-5.7049, 8.0689]` |
| `cagr` | Compound annual growth rate from `total_return` and elapsed calendar days. | `[-1, +inf)` in normal cases; `0` when elapsed days are invalid. | Return ratio per year | `0.077467 [-0.278795, 0.433729]` |
| `cumulative_log_return` | Sum of daily log returns. | `(-inf, +inf)`. | Log-return | `0.536784 [-1.6418, 2.7154]` |
| `mean_log_return` | Arithmetic mean of daily log returns. | `(-inf, +inf)`. | Log-return per trading day | `0.000214 [-0.006451, 0.006879]` |
| `median_log_return` | Median daily log return. | `(-inf, +inf)`. | Log-return per trading day | `0.000491 [-0.002391, 0.003372]` |
| `min_log_return` | Worst daily log return. | `(-inf, +inf)`. | Log-return per trading day | `-0.106668 [-1.1257, 0.912378]` |
| `max_log_return` | Best daily log return. | `(-inf, +inf)`. | Log-return per trading day | `0.075366 [-0.354978, 0.505709]` |
| `mean_simple_return` | Arithmetic mean of daily simple returns. | `[-1, +inf)` for positive prices. | Return ratio per trading day | `0.000996 [-0.082198, 0.084191]` |
| `median_simple_return` | Median daily simple return. | `[-1, +inf)` for positive prices. | Return ratio per trading day | `0.000491 [-0.002360, 0.003343]` |
| `min_simple_return` | Worst daily simple return. | `[-1, +inf)` for positive prices. | Return ratio per trading day | `-0.083130 [-0.344142, 0.177882]` |
| `max_simple_return` | Best daily simple return. | `[-1, +inf)` for positive prices. | Return ratio per trading day | `0.179605 [-12.4563, 12.8155]` |
| `daily_log_return_std` | Sample standard deviation of daily log returns. | `[0, +inf)`. | Log-return per trading day | `0.011412 [-0.061499, 0.084322]` |
| `daily_simple_return_std` | Sample standard deviation of daily simple returns. | `[0, +inf)`. | Return ratio per trading day | `0.017311 [-0.845750, 0.880371]` |
| `annualized_return` | Alias of `annualized_log_return`. | `(-inf, +inf)`. | Log-return per year | `0.053898 [-1.6257, 1.7335]` |
| `annualized_log_return` | Mean daily log return multiplied by `252`. | `(-inf, +inf)`. | Log-return per year | `0.053898 [-1.6257, 1.7335]` |
| `annualized_simple_return` | Mean daily simple return multiplied by `252`. | `(-inf, +inf)`. | Return ratio per year | `0.251049 [-20.7140, 21.2161]` |
| `annualized_geometric_return` | `exp(annualized_log_return) - 1`. | `[-1, +inf)`. | Return ratio per year | `0.078848 [-0.280280, 0.437976]` |
| `annualized_volatility` | Daily log-return standard deviation multiplied by `sqrt(252)`. | `[0, +inf)`. | Log-return volatility per year | `0.181154 [-0.976263, 1.3386]` |
| `realized_variance` | Sum of squared daily log returns over the observed window. | `[0, +inf)`. | Squared log-return | `1.5105 [-136.76, 139.78]` |
| `realized_volatility` | Square root of `realized_variance`. | `[0, +inf)`. | Log-return | `0.498391 [-2.8729, 3.8697]` |
| `downside_deviation` | Annualized downside deviation from negative daily log returns. | `[0, +inf)`. | Log-return downside volatility per year | `0.133032 [-0.884647, 1.1507]` |
| `sharpe_ratio` | `annualized_log_return / annualized_volatility`; risk-free rate is not subtracted. | `(-inf, +inf)`; `0` when denominator is `0`. | Unitless ratio | `0.556117 [-2.0657, 3.1780]` |
| `sortino_ratio` | `annualized_log_return / downside_deviation`; risk-free rate is not subtracted. | `(-inf, +inf)`; `0` when denominator is `0`. | Unitless ratio | `0.864118 [-5.1227, 6.8509]` |
| `var` | Historical loss quantile from negative daily log returns at `confidence_level`. | `(-inf, +inf)` technically; positive values are losses, negative values are gains at the quantile. | Daily log-return loss | `0.020483 [-0.016485, 0.057450]` |
| `expected_shortfall` | Mean historical loss in the tail at or beyond `var`. | `(-inf, +inf)` technically; positive values are tail losses. | Daily log-return loss | `0.033034 [-0.202473, 0.268540]` |
| `tail_observation_count` | Number of return observations in the tail used for expected shortfall. | Integer `>= 0`. | Rows | `54.0119 [-56.0055, 164.03]` |
| `max_drawdown` | Worst peak-to-trough adjusted-close drawdown. | `[-1, 0]` for positive prices. | Return ratio | `-0.304281 [-0.861031, 0.252469]` |
| `positive_day_ratio` | Share of daily log returns greater than `0`. | `[0, 1]`. | Ratio | `0.524554 [0.418500, 0.630608]` |
| `log_price_slope` | Linear-regression slope of `ln(adjusted_close)` over quote index. | `(-inf, +inf)`. | Log-price change per quote row | `0.000253 [-0.001997, 0.002502]` |
| `trend_r_squared` | R-squared of the log-price trend regression. | `[0, 1]` in normal cases. | Unitless ratio | `0.642729 [-0.291661, 1.5771]` |
| `availability_reason` | Basic availability status for the statistic row. | `ok` or `insufficient_returns`. | Category | n/a |
| `distribution_frequency` | Inferred dividend distribution cadence from Bronze dividend dates. | `monthly`, `quarterly`, `semiannual`, `annual`, `irregular`, `accumulating`, or `unknown`. | Category | `accumulating=1104`, `irregular=349`, `quarterly=94`, `semiannual=91`, `annual=77`, `unknown=24`, `monthly=20` |
| `distribution_events_per_year` | Annualized event rate from first to last positive dividend event. | `[0, +inf)`. | Events per year | `1.0295 [-4.8443, 6.9032]` |
| `last_distribution_date` | Latest positive dividend event date. | ISO date, or empty when no dividend event exists. | Date | n/a |
| `distribution_observation_count` | Number of positive dividend events used for distribution inference. | Integer `>= 0`. | Rows | `8.7322 [-43.8037, 61.2681]` |

`bivariate_statistics` computes reusable pairwise statistics for the latest persisted `univariate_filter` selection by default. Pair metrics are computed once per unordered ISIN pair and only on the intersection of shared return dates:

```bash
uv run founder bivariate-statistics
```

Use `--selection-id <selection_id>` only when intentionally rebuilding a specific `univariate_filter` or `metadata_filter` selection.

Bivariate Statistics parallelizes pair work across all CPU cores visible to the system by default. Use `--concurrency <workers>` to cap worker processes.

`multivariate_statistics` computes portfolio-level analytics for the latest persisted `univariate_filter` selection by default. It filters Silver quotes to the selected listings, builds selected Gold risk inputs, writes an aligned return matrix and asset metrics, and runs Equal Weight, Minimum Variance, Maximum Sharpe, Risk Parity, HRP, Maximum Diversification, efficient-frontier, walk-forward, rebalance, and tail-risk outputs:

```bash
uv run founder multivariate-statistics
```

Multivariate Statistics parallelizes the selected Gold input build across all CPU cores visible to the system by default, and cache mode also passes the same worker count to univariate and bivariate cache refreshes. Use `--concurrency <workers>` to cap worker processes, for example `--concurrency 1` for deterministic single-process debugging. Use `--use-selection-statistics-cache` to consume reusable selection statistics views and reuse unchanged portfolio runs.

Module outputs are intentionally reusable:

```text
lake/reference/all_isins/
lake/silver/metadata_filter/{selection_id}/
lake/gold/univariate_statistics/{exchange}/{ISIN}.parquet
lake/silver/univariate_filter/{selection_id}/
lake/gold/bivariate_statistics/{left_exchange}/{left_ISIN}/{left_code}/{right_exchange}__{right_ISIN}__{right_code}.parquet
```

Statistic paths deliberately do not include a selection id. Later metadata or univariate selections can therefore reuse already computed per-ISIN and pair statistics for unchanged listings and unchanged pairs instead of recomputing them.

## Scheduled Founder Cron

Founder cron should call the `fetch-all-quotes` module for quote updates, not individual ad hoc Bronze/Silver snippets. Keep the cron job readable by defining absolute paths once:

```cron
SHELL=/bin/bash
FOUNDER_PROJECT=/home/vcs/git/founder
FOUNDER_UV=/home/vcs/.local/bin/uv
FOUNDER_LOCK=/home/vcs/git/founder/lake/silver/runs/founder-fetch-all-quotes.lock
FOUNDER_LOG=/home/vcs/git/founder/.logs/cron-fetch-all-quotes.log

# Daily quote fetch at 18:00 local server time.
0 18 * * * cd "$FOUNDER_PROJECT" && /usr/bin/flock -n "$FOUNDER_LOCK" "$FOUNDER_UV" run founder fetch-all-quotes --root "$FOUNDER_PROJECT/lake" --concurrency 2 --debug >> "$FOUNDER_LOG" 2>&1
```

Inspect it with `crontab -l`. Cron output is appended to `.logs/cron-fetch-all-quotes.log`.

The dry run writes discovery candidates, a canonical universe, bronze plan, quote rows, coverage manifests, and Gold return/correlation/covariance/feature inputs under the selected local lake root.

## EODHD Request Safety

Founder spaces EODHD requests by default and retries transient failures so large loads do not hammer the API. Bronze is safe for unattended cron execution with bounded EODHD parallelism capped at a default concurrency of `2`. Cron runs preserve request pacing, respect `Retry-After`, use stable run ids, resume safely after partial failures, and avoid overlapping writes for the same lake root.

Prefer `.secrets/eodhd.yaml` for the API token:

```yaml
eodhd:
  api_key: "your-token"
```

`.env.local` remains supported for non-secret local tuning and fallback token loading. Tune these values there when the subscription limit changes:

```text
EODHD_TIMEOUT_SECONDS=30
EODHD_MAX_RETRIES=2
EODHD_MIN_REQUEST_INTERVAL_SECONDS=0.25
EODHD_RETRY_BACKOFF_SECONDS=0.5
```

HTTP `429` responses are retried when retries remain. If EODHD sends `Retry-After`, Founder waits for that duration before retrying; otherwise it uses incremental backoff.

## Logging And Debugging

Founder writes uniformly formatted logs under `.logs/`. Plain log files are kept for seven days, then zipped; zipped logs older than one month are deleted. `.logs/` is ignored by Git.

Target module commands should support `--debug` for more detailed module logs:

```bash
uv run founder fetch-all-isins --debug
uv run founder metadata-filter --debug
uv run founder univariate-statistics --debug
uv run founder univariate-filter --debug
uv run founder bivariate-statistics --debug
```

The log format is consistent across Founder modules:

```text
YYYY-MM-DDTHH:MM:SSZ LEVEL logger.name message
```

## Quality Gates

[GATES.md](GATES.md) is the source of truth for GitHub quality gates, branch protection, auto-merge, shard layout, coverage policy, and local validation commands.

## Hosted Development Runtime

The hosted development runtime is defined in [compose.yaml](compose.yaml). It starts internal PostgreSQL, the API container, and the Web container with named persistent PostgreSQL and shared-data volumes. Runtime secret file paths come from `.env.example` variables and must point to absolute host paths outside this repository.

```bash
docker compose --env-file .env.local up --build
```

The hosted API is exposed by `founder.hosted_api` and mounted in the API container. It provides user-scoped session, credential, download, dataset, project, selection, analysis, metrics, returns, weights, report, and account-deletion routes for the Web UI.

The hosted Web container serves the local research workspace from `apps/web/server.js`. It provides the production shell baseline with versioned design tokens, responsive navigation, project snapshot indicator, and the persisted funnel routes `Data -> Metadata -> Univariate -> Filter -> Diversification -> Portfolio -> Validation -> Report`. The dashboard shell is mounted only after the Web surface verifies an authenticated session through its same-origin `/api/session` proxy. Browser state is derived from API responses, and the Web surface must not store EODHD keys, Google tokens, session tokens, ciphertext, fingerprints, or sensitive API responses in `localStorage`, `sessionStorage`, URLs, analytics, logs, or rendered error output.

Hosted public deployment readiness is described by `docs/security/hosted_readiness.json` and `docs/security/hosted_readiness.md`. Normal quality gates require complete readiness records while local-only mode remains available. Public-hosted release cutover must additionally pass `uv run python -m founder.hosted_readiness --require-public-hosted`.

Run the deterministic hosted cutover proof with:

```bash
uv run python -m founder.hosted_cutover
```

Install dependencies with:

```bash
uv sync --dev
```

Install the pre-commit hook with:

```bash
uv run pre-commit install
```

Run all hooks manually with:

```bash
uv run pre-commit run --all-files
```

## Documentation Refresh

Generate the tracked documentation review report with:

```bash
uv run founder-docs-refresh
```

The command writes `docs/docs_refresh_report.json` and reports which top-level project docs are present and whether their `Last reviewed:` marker is current enough to inspect manually.

## Keep This README Up To Date

Update this file whenever:

- the project goal or portfolio objective changes;
- the EODHD universe count or discovery method changes;
- quote ingestion, validation, or optimization workflows are implemented;
- tracked datasets, commands, or configuration conventions change;
- architecture, risks, backlog, or decisions add facts that affect user-facing project understanding.
