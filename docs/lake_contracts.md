# Lake Contracts

Last reviewed: 2026-07-12

## Table Of Contents

- [Layers](#layers)
- [Core Tables](#core-tables)
- [How This Fits The Onboarding Flow](#how-this-fits-the-onboarding-flow)

Founder uses deterministic local lake artifacts under a `LakePaths` root. Table paths ending in `.parquet` are physical Apache Parquet files written through `founder.table_io`; JSON and CSV artifacts keep their native formats.

Read this after [ARCHITECTURE.md](../ARCHITECTURE.md) and before changing Search, Fetch, Gold, or storage code. Read [docs/search_fetch_workflow.md](search_fetch_workflow.md) for executable examples that use these contracts.

## Layers

- Bronze stores raw or near-raw EODHD search, quote, dividends, and splits payloads.
- Silver stores normalized search candidates, canonical universe rows, and quote rows partitioned by year.
- Gold stores adjusted-close returns, correlation, and covariance rows.
- Silver metadata stores the active universe pointer, fetch plans, fetch runs, coverage, errors, and dry-run summaries without adding a fourth top-level lake layer.

Bronze quote rows are partitioned by exchange and quote year, with one file per ISIN:

```text
bronze/quotes/{exchange}/{year}/{ISIN}.parquet
```

Runtime logs are intentionally outside the lake under `.logs/`. They are operational diagnostics, not dataset artifacts.

## Core Tables

- `search_candidates`: normalized discovery rows with search run id, query, endpoint, instrument identifiers, type, country, currency, ISIN, name, normalized name, and discovery timestamp.
- `canonical_universe`: one selected listing per ISIN, including selection reason and `selected_for_fetch=true`.
- `fetch_plan`: run id, ISIN, code, exchange, derived EODHD symbol, start date, and end date. In default gap-aware runs, one listing can expand into multiple gap windows.
- `quotes`: normalized OHLCV rows with adjusted close, currency, run id, and fetch timestamp. Delta writes merge into existing yearly partitions by ISIN, exchange, code, and quote date.
- `dividends` and `splits`: near-raw EODHD rows archived under `bronze/{dataset}/{exchange}/{year}/{ISIN}.parquet` for each approved listing, matching the quote partition shape.
- `coverage`: first and last quote dates, observed rows, missing periods, and next fetch start used by gap-aware Fetch planning.
- `quote_gaps`: quote gap ranges by ISIN, code, exchange, symbol, data type, gap type, start, end, and missing trading-day count. Gap-aware Fetch downloads historical gaps first, then the tail to the selected run date.
- `errors`: non-secret fetch error records.
- `returns`, `correlation`, and `covariance`: Gold risk-input tables built from validated Silver quote rows.

Gap-aware planning is currently scoped to the `quotes` data type because quote rows are dated market time series. Non-quote ISIN data types must define their own completeness contract before they participate in automatic backfills. Dividends and splits are fetched once per listing/run up to the run date and stored as dated Bronze rows beside quotes.

## How This Fits The Onboarding Flow

Use the deterministic mocked pipeline to see these contracts written end to end:

```bash
uv run founder dry-run --root lake
```

The dry run is safe to repeat and rewrites the same sample artifacts deterministically.