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
3. Read [docs/lake_contracts.md](docs/lake_contracts.md) before changing paths, schemas, or storage formats.
4. Check [RISKS.md](RISKS.md), [DECISIONS.md](DECISIONS.md), and [BACKLOG.md](BACKLOG.md) before opening a PR-sized change.
5. Follow [AGENTS.md](AGENTS.md) for workflow rules, PR status tracking, and merge-gate policy.

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
3. Bronze end-of-day quotes for the selected canonical universe.
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
- [docs/lake_contracts.md](docs/lake_contracts.md) defines lake layers and table contracts.
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

```text
isin
exchange
code
name
instrument_type
country
currency
source_exchange
fetched_at
```

`univariate_statistics` builds reusable per-ISIN statistics from validated Silver quote files. Returns are daily log returns, `ln(P_t / P_{t-1})`, based on adjusted close:

```bash
uv run founder univariate-statistics
```

`univariate_statistics` only runs for the latest persisted `metadata_filter` selection. It does not scan every Silver quote file by default. Use `--selection-id <metadata_filter_selection_id>` only when intentionally rebuilding an older metadata selection.

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
```

`bivariate_statistics` computes reusable pairwise statistics for a persisted selection. Pair metrics are computed once per unordered ISIN pair and only on the intersection of shared return dates:

```bash
uv run founder bivariate-statistics --selection-id <selection_id>
```

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

Founder cron should call the refresh orchestration for the five-module architecture, not individual ad hoc module snippets. Keep the cron job readable by defining absolute paths once:

```cron
SHELL=/bin/bash
FOUNDER_PROJECT=/home/vcs/git/founder
FOUNDER_UV=/home/vcs/.local/bin/uv
FOUNDER_LOCK=/home/vcs/git/founder/lake/silver/runs/founder-refresh.lock
FOUNDER_LOG=/home/vcs/git/founder/.logs/cron-refresh.log

# Daily refresh at 18:00 local server time.
0 18 * * * cd "$FOUNDER_PROJECT" && /usr/bin/flock -n "$FOUNDER_LOCK" "$FOUNDER_UV" run founder refresh --root "$FOUNDER_PROJECT/lake" --concurrency 2 --debug >> "$FOUNDER_LOG" 2>&1
```

Inspect it with `crontab -l`. Cron output is appended to `.logs/cron-refresh.log`.

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

Founder uses two quality gates. [AGENTS.md](AGENTS.md) is the source of truth for branch protection and merge policy; this section only lists the commands a contributor should run locally.

### PR Gate

Run this before every commit, push, or pull request update:

```bash
uv run founder-quality pr
```

The local pre-commit hook runs this same PR gate.

### Branch Naming

Create branches as `<type>/<scope>-<short-description>` using lowercase ASCII letters, numbers, and hyphens. Allowed branch types are `feat`, `fix`, `refactor`, `docs`, and `chore`; choose the type that describes the primary purpose of the PR.

### Main Gate

Run this immediately before merging to `main`:

```bash
uv run founder-quality main
```

The main gate requires all of the following checks to pass before merge:

- Ruff lint and format checks.
- Pyright strict type checking.
- Pytest.
- At least 95% test coverage.
- Import Linter contracts.
- Dataset schema-registry validation.

It also validates Conventional Commit subjects and requires a clean tracked working tree. The coverage command is:

```text
pytest --cov=founder --cov-report=term-missing --cov-fail-under=95
```

Both layers require Conventional Commit subjects for branch commits. Pull request titles use the same format because the validated title becomes the squash-merge commit subject:

```text
type(optional-scope): subject
```

Allowed types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, and `test`.

The local pre-commit setup also installs a `commit-msg` hook that validates the commit subject before a commit is accepted. GitHub merge policy is documented in [AGENTS.md](AGENTS.md).

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
