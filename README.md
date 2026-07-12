# Founder

Last reviewed: 2026-07-12

Founder is a fund portfolio builder for exchange-traded funds. The project goal is to analyze EODHD end-of-day quotes for multiple thousands of ETFs and build minimum-risk fund portfolio weights.

The primary data source is the EODHD subscription for EOD Historical Data. Flatex will be used as the trading exchange/broker venue for turning portfolio weights into executable ETF trades. Local API credentials must stay in ignored environment files such as `.env.local`; never commit real tokens.

## Current Facts

- The local Python environment uses Python 3.14.5 in `.venv/`.
- The main market data source is the EODHD subscription for EOD Historical Data.
- The intended trading venue/broker is Flatex.
- EODHD Search API supports lookup by ticker, company/fund name, or ISIN through `/api/search/{query_string}`.
- EODHD Search API can filter by asset type with `type=etf` or `type=fund`, but each search response is capped at 500 results.
- A complete broad lookup for names containing `UCITS ETF` requires enumerating EODHD exchange symbol lists and filtering locally.
- The latest local EODHD enumeration checked 70 exchange codes.
- The enumeration found 8,165 unique active instruments with `UCITS ETF` in the instrument name.
- The result set contains 8,063 rows with type `ETF` and 102 rows with type `FUND`.
- The largest match counts were on `XETRA`, `LSE`, `F`, `SW`, `PA`, `AS`, and `EUFUND`.
- The generated discovery dataset is stored at `docs/eodhd_ucits_etf_matches.csv`.
- Portfolio fetches should use one canonical listing per ISIN: prefer `XETRA` when that ISIN is listed there, otherwise select a fallback exchange deterministically.
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
4. Normalize quotes into a reproducible local dataset.
5. Validate coverage, missing dates, currencies, identifiers, and duplicate listings.
6. Estimate return and risk inputs from validated quote history.
7. Build minimum-risk portfolio weights under explicit constraints.
8. Report weights, assumptions, coverage gaps, and validation results.

## Portfolio Objective

The initial optimization objective is minimum portfolio variance:

$$
\min_w \; w^T \Sigma w
$$

Subject to constraints that will be made explicit before implementation, such as:

- weights sum to 1;
- long-only or bounded weights;
- maximum concentration per ETF, issuer, currency, country, or asset class;
- minimum quote-history coverage;
- duplicate listing and duplicate ISIN handling.

## Repository Docs

- `ARCHITECTURE.md` describes project layers and boundaries.
- `RISKS.md` tracks active technical, data, and operational risks.
- `BACKLOG.md` tracks visible implementation work.
- `DECISIONS.md` records durable technical decisions.
- `AGENTS.md` stores generated project-history risk context.
- `docs/lake_contracts.md` describes the local Bronze, Silver, Gold, and Meta table contracts.

## Local Dry Run

Run the mocked end-to-end pipeline without credentials:

```bash
uv run founder dry-run --root data/dry-run
```

The dry run writes search candidates, a canonical universe, fetch plan, quote rows, fundamentals profiles, coverage manifests, and Gold return/correlation/covariance inputs under the selected local lake root.

## EODHD Request Safety

Founder spaces EODHD requests by default and retries transient failures so large fetches do not hammer the API. Tune these values in `.env.local` when the subscription limit changes:

```text
EODHD_TIMEOUT_SECONDS=30
EODHD_MAX_RETRIES=2
EODHD_MIN_REQUEST_INTERVAL_SECONDS=0.25
EODHD_RETRY_BACKOFF_SECONDS=0.5
```

HTTP `429` responses are retried when retries remain. If EODHD sends `Retry-After`, Founder waits for that duration before retrying; otherwise it uses incremental backoff.

## Quality Gates

Founder uses exactly two quality gate layers.

### PR Gate

Run this before every commit, push, or pull request update:

```bash
uv run founder-quality pr
```

The PR gate runs:

```text
ruff check
ruff format --check
mypy
pytest
Conventional Commit validation for branch commits
```

The local pre-commit hook runs this same PR gate.

### Main Gate

Run this immediately before merging to `main`:

```bash
uv run founder-quality main
```

The main gate runs the PR gate and then requires a clean tracked working tree.
For main merges, pytest must report at least 95% coverage:

```text
pytest --cov=founder --cov-report=term-missing --cov-fail-under=95
```

Both layers require Conventional Commit subjects for branch commits, using:

```text
type(optional-scope): subject
```

Allowed types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, and `test`.

The local pre-commit setup also installs a `commit-msg` hook that validates the commit subject before a commit is accepted.

GitHub protects `main` with the required `quality` status check, conversation resolution, linear history, and disabled force pushes/deletions. Same-repository PRs may be squash-merged automatically after the `quality` workflow passes.

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

## Keep This README Up To Date

Update this file whenever:

- the project goal or portfolio objective changes;
- the EODHD universe count or discovery method changes;
- quote ingestion, validation, or optimization workflows are implemented;
- tracked datasets, commands, or configuration conventions change;
- architecture, risks, backlog, or decisions add facts that affect user-facing project understanding.