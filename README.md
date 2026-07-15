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
- [Run The Three Modules](#run-the-three-modules)
- [Scheduled Founder Cron](#scheduled-founder-cron)
- [EODHD Request Safety](#eodhd-request-safety)
- [Logging And Debugging](#logging-and-debugging)
- [Quality Gates](#quality-gates)
- [Documentation Refresh](#documentation-refresh)
- [Keep This README Up To Date](#keep-this-readme-up-to-date)

Founder is a fund portfolio builder for exchange-traded funds. The project goal is to analyze EODHD end-of-day quotes for multiple thousands of ETFs and build risk-aware fund portfolio weights.

The primary data source is the EODHD subscription for EOD Historical Data. Flatex will be used as the trading exchange/broker venue for turning portfolio weights into executable ETF trades. Local API credentials must stay in ignored environment files such as `.env.local`; never commit real tokens.

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
- EODHD Search API supports lookup by ticker, company/fund name, or ISIN through `/api/search/{query_string}`.
- EODHD Search API can filter by asset type with `type=etf` or `type=fund`, but each search response is capped at 500 results.
- A complete broad lookup for names containing `UCITS ETF` requires enumerating EODHD exchange symbol lists and filtering locally.
- The generated discovery dataset is stored at `docs/eodhd_ucits_etf_matches.csv`.
- Portfolio loads should use one canonical listing per ISIN: prefer `XETRA` when that ISIN is listed there, otherwise select a fallback exchange deterministically.
- The canonical no-duplicate-ISIN dataset is stored at `docs/eodhd_ucits_etf_canonical_isins.csv`.
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

The current refactor keeps the public CLI focused on Search plus reusable univariate and bivariate statistics. Portfolio optimization remains downstream analysis work and is not exposed as a first-class module in this cut.

## Documentation Map

- [ARCHITECTURE.md](ARCHITECTURE.md) explains how modules connect and where responsibilities live.
- [docs/lake_contracts.md](docs/lake_contracts.md) defines lake layers and table contracts.
- [DECISIONS.md](DECISIONS.md) records why durable technical choices were made.
- [RISKS.md](RISKS.md) tracks active project risks and mitigations.
- [BACKLOG.md](BACKLOG.md) tracks PR-sized work and implementation status.
- [AGENTS.md](AGENTS.md) defines agent workflow rules and generated project-history risks.

## Run The Three Modules

Founder currently exposes three CLI modules: `search`, `univariate-statistics`, and `bivariate-statistics`.

First run Search with the string to find. By default this reads `docs/eodhd_ucits_etf_matches.csv`, writes to `lake`, generates a search run id, and approves the canonical universe:

```bash
uv run founder search "UCITS ETF"
```

Then build reusable per-listing statistics from existing Silver quote files:

```bash
uv run founder univariate-statistics
```

Then build reusable pairwise statistics from the same Silver quote files:

```bash
uv run founder bivariate-statistics
```

Univariate statistics are stored by stable listing key:

```text
lake/gold/univariate_statistics/{exchange}/{ISIN}.parquet
```

Bivariate statistics are stored by stable pair key:

```text
lake/gold/bivariate_statistics/{left_exchange}/{left_ISIN}/{left_code}/{right_exchange}__{right_ISIN}__{right_code}.parquet
```

Those paths deliberately do not include a search run id. A later Search list can therefore reuse already computed statistics for unchanged listings and unchanged listing pairs instead of recomputing them.

## Scheduled Founder Cron

The `vcs` user crontab should call only the three public modules. Keep the cron job readable by defining absolute paths once:

```cron
SHELL=/bin/bash
FOUNDER_PROJECT=/home/vcs/git/founder
FOUNDER_UV=/home/vcs/.local/bin/uv
FOUNDER_LOG=/home/vcs/git/founder/.logs/cron-statistics.log

# Daily statistics rebuild at 18:00 local server time.
0 18 * * * cd "$FOUNDER_PROJECT" && "$FOUNDER_UV" run founder univariate-statistics --root "$FOUNDER_PROJECT/lake" --debug >> "$FOUNDER_LOG" 2>&1
5 18 * * * cd "$FOUNDER_PROJECT" && "$FOUNDER_UV" run founder bivariate-statistics --root "$FOUNDER_PROJECT/lake" --debug >> "$FOUNDER_LOG" 2>&1
```

Inspect it with `crontab -l`. Cron output is appended to `.logs/cron-statistics.log`.

The dry run writes search candidates, a canonical universe, bronze plan, quote rows, coverage manifests, and Gold return/correlation/covariance/feature inputs under the selected local lake root.

## EODHD Request Safety

Founder spaces EODHD requests by default and retries transient failures so large loads do not hammer the API. Bronze is safe for unattended cron execution with bounded EODHD parallelism capped at a default concurrency of `2`. Cron runs preserve request pacing, respect `Retry-After`, use stable run ids, resume safely after partial failures, and avoid overlapping writes for the same lake root.

Tune these values in `.env.local` when the subscription limit changes:

```text
EODHD_TIMEOUT_SECONDS=30
EODHD_MAX_RETRIES=2
EODHD_MIN_REQUEST_INTERVAL_SECONDS=0.25
EODHD_RETRY_BACKOFF_SECONDS=0.5
```

HTTP `429` responses are retried when retries remain. If EODHD sends `Retry-After`, Founder waits for that duration before retrying; otherwise it uses incremental backoff.

## Logging And Debugging

Founder writes uniformly formatted logs under `.logs/`. Plain log files are kept for seven days, then zipped; zipped logs older than one month are deleted. `.logs/` is ignored by Git.

All CLI commands support `--debug` for more detailed module logs:

```bash
uv run founder search "UCITS ETF" --debug
uv run founder univariate-statistics --debug
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
