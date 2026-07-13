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
- [Run Search And Fetch](#run-search-and-fetch)
- [Local Dry Run](#local-dry-run)
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
3. Read [docs/search_fetch_workflow.md](docs/search_fetch_workflow.md) before changing Search or Fetch behavior.
4. Read [docs/lake_contracts.md](docs/lake_contracts.md) before changing paths, schemas, or storage formats.
5. Check [RISKS.md](RISKS.md), [DECISIONS.md](DECISIONS.md), and [BACKLOG.md](BACKLOG.md) before opening a PR-sized change.
6. Follow [AGENTS.md](AGENTS.md) for workflow rules, PR status tracking, and merge-gate policy.

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
3. Fetch end-of-day quotes for the selected canonical universe.
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

Founder aims to compare optimization techniques with reproducible Gold datasets before any target weights are used for trading. The evaluation layer should consume Gold returns, correlation, and covariance inputs; it should not call EODHD or mutate Fetch and Silver market data.

Planned portfolio analysis and evaluation computations include:

- aligned return matrices by date and listing;
- asset metrics such as observation count, annualized return, annualized volatility, downside deviation, Sharpe ratio, and Sortino ratio;
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

## Documentation Map

- [ARCHITECTURE.md](ARCHITECTURE.md) explains how modules connect and where responsibilities live.
- [docs/search_fetch_workflow.md](docs/search_fetch_workflow.md) shows how to use Search and Fetch from Python.
- [docs/lake_contracts.md](docs/lake_contracts.md) defines lake layers and table contracts.
- [DECISIONS.md](DECISIONS.md) records why durable technical choices were made.
- [RISKS.md](RISKS.md) tracks active project risks and mitigations.
- [BACKLOG.md](BACKLOG.md) tracks PR-sized work and implementation status.
- [AGENTS.md](AGENTS.md) defines agent workflow rules and generated project-history risks.

## Run Search And Fetch

Search and Fetch have separate CLI calls. First run Search with the string to find. By default this reads `docs/eodhd_ucits_etf_matches.csv`, writes to `lake`, generates a search run id, and approves the canonical universe for Fetch:

```bash
uv run founder search "UCITS ETF"
```

Then run Fetch from the approved universe pointer. By default this loads live EODHD quotes with gap-aware planning, writes Fetch quote/dividend/split rows, and writes Silver operational fetch metadata. For first-time ISINs, quote loading requests the full available history up to the run date by omitting `from` and sending `to=<run-date>`:

```bash
uv run founder fetch
```

Build Silver quotes and Gold risk inputs explicitly after Fetch:

```bash
uv run founder silver
uv run founder gold
```

Use the refresh command when you want the three phases in one cron-friendly command:

```bash
uv run founder refresh
```

After a full-history run has written local quotes, later live loads check for per-ISIN quote gaps before downloading. They backfill historical gaps first, then ingest the fresh tail up to the run date:

```bash
uv run founder fetch
```

Gap-aware Fetch reads existing Silver quote dates, expands each ISIN into the missing quote windows, and keeps first-time ISINs in the plan for full-history loading. The resulting windows are used for quotes, dividends, and splits. Remaining quote gaps are recorded in `lake/silver/coverage/quote_gaps.parquet`.

The gap-aware approach currently discovers windows from quote history, then applies those windows to all supported EODHD time-series datasets. Dividends and splits are archived beside quotes as dated Bronze Parquet rows under `lake/bronze/dividends/{exchange}/{year}/{ISIN}.parquet` and `lake/bronze/splits/{exchange}/{year}/{ISIN}.parquet`. Additional time-series data types should get their own strategy, coverage fields, and gap table before being added to automatic gap planning.

Use `--mock` for a local no-token Fetch run that writes deterministic Fetch quote and operational metadata artifacts:

```bash
uv run founder fetch --mock
```

Limit Fetch to the first `N` approved canonical ISINs, or to one exact ISIN, when testing a small batch. `--limit` and `--isin` are mutually exclusive:

```bash
uv run founder fetch --limit 10 --mock
uv run founder fetch --isin IE0000000001 --mock
```

Pass `--start-date` and/or `--end-date` only when you want to restrict the live EODHD history window.

For full input format details and Python usage examples, see [docs/search_fetch_workflow.md](docs/search_fetch_workflow.md#how-to-run-both-modules).

## Local Dry Run

Run the mocked end-to-end pipeline without credentials:

```bash
uv run founder dry-run --root lake
```

The dry run writes search candidates, a canonical universe, fetch plan, quote rows, coverage manifests, and Gold return/correlation/covariance inputs under the selected local lake root.

## EODHD Request Safety

Founder spaces EODHD requests by default and retries transient failures so large loads do not hammer the API. Fetch is safe for unattended cron execution with bounded EODHD parallelism capped at a default concurrency of `2`. Cron runs preserve request pacing, respect `Retry-After`, use stable run ids, resume safely after partial failures, and avoid overlapping writes for the same lake root.

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
uv run founder fetch --mock --debug
uv run founder dry-run --debug
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

### Main Gate

Run this immediately before merging to `main`:

```bash
uv run founder-quality main
```

The main gate runs the PR gate, requires a clean tracked working tree, and enforces at least 95% test coverage:

```text
pytest --cov=founder --cov-report=term-missing --cov-fail-under=95
```

Both layers require Conventional Commit subjects for branch commits, using:

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