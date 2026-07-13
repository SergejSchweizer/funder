# Search And Fetch Workflow

Last reviewed: 2026-07-12

## Table Of Contents

- [Purpose](#purpose)
- [Connection Diagram](#connection-diagram)
- [Quick Mental Model](#quick-mental-model)
- [Module Responsibilities](#module-responsibilities)
- [How To Run Both Modules](#how-to-run-both-modules)
- [Prerequisites](#prerequisites)
- [Search Module](#search-module)
- [Fetch Module](#fetch-module)
- [End-To-End Example](#end-to-end-example)
- [Artifacts](#artifacts)
- [Common Failure Modes](#common-failure-modes)
- [Update Rules](#update-rules)

## Purpose

This guide explains how to use the Search and Fetch modules directly from Python. It is written for someone who needs to produce a reviewed ETF universe, fetch quote inputs, normalize them, and inspect coverage without first learning the whole codebase.

## Connection Diagram

```text
EODHD search or exchange-symbol-list rows
        |
        v
    +---------------+
    | search        |
    | normalize,    |
    | deduplicate,  |
    | approve       |
    +-------+-------+
        |
        | canonical_universe + current_universe pointer
        v
    +-------+-------+
    | fetch         |
    | plan symbols, |
    | archive raw,  |
    | normalize     |
    +-------+-------+
        |
        | Silver quotes + coverage + errors
        v
    +-------+-------+
    | gold and      |
    | portfolio     |
    | risk inputs   |
    +---------------+
```

## Quick Mental Model

- Search finds and normalizes instrument candidates.
- Search selects one canonical listing per non-empty ISIN.
- Search approval writes the active universe pointer.
- Fetch reads only the approved canonical universe contract.
- Fetch plans symbols, archives raw or near-raw Bronze data, normalizes quotes, and writes coverage manifests.

Search must not fetch historical quote payloads. Fetch must not perform fuzzy discovery. The handoff is the `canonical_universe` table and the `current_universe.json` pointer.

## Module Responsibilities

`founder.search` is the module to use when the input is still an instrument discovery result. It accepts raw EODHD-style candidate rows, normalizes names and identifiers, excludes rows without ISIN from fetch input, chooses one canonical listing per ISIN, writes a human-review CSV, and approves the final universe by writing `current_universe.json`.

`founder.fetch` is the module to use after a universe has been approved. It reads the canonical-universe contract, validates required fields, derives EODHD symbols, writes a fetch plan, archives quote, dividends, and splits data into Bronze, normalizes quote rows into Silver, writes Gold risk inputs, writes coverage manifests, and logs fetch errors to the run log.

`founder.paths` is the module to use when code needs artifact locations. It keeps Search and Fetch from hard-coding lake paths and makes dry runs, tests, and local workspaces deterministic.

`founder.schemas` is the module to use when code needs to validate table shape. It defines the required fields that Search and Fetch must preserve when moving rows between Bronze, Silver, Gold, metadata, and coverage.

`founder.table_io` is the module to use for reading and writing current table artifacts. It hides physical Parquet reads/writes behind simple helpers so Search and Fetch do not embed storage-engine details.

## How To Run Both Modules

Search and Fetch have separate CLI calls. Use them when you want to run only the discovery-to-canonical-universe step or only the approved-universe-to-fetch-artifacts step.

### Run Search

Run Search with the string to find. The default input is `docs/eodhd_ucits_etf_matches.csv`, the default root is `lake`, the run id is generated automatically, and the canonical universe is approved by default:

```bash
uv run founder search "UCITS ETF"
```

For the checked-in dataset, this finds 8,165 candidate rows and selects 3,104 canonical ISIN rows.

To use another local source, pass `--input`. The file can be a CSV with EODHD-style columns, a JSON list of EODHD-style rows, or a JSON object with a `responses` or `candidates` list:

```json
[
    {
        "Code": "EXAMPLE",
        "Exchange": "XETRA",
        "Type": "ETF",
        "Country": "DE",
        "Currency": "EUR",
        "Isin": "IE0000000001",
        "Name": "Example UCITS ETF"
    }
]
```

Run Search and approve its canonical universe for Fetch:

```bash
uv run founder search \
    "UCITS ETF" \
    --input docs/example_candidates.json \
    --root lake
```

This writes raw candidates, normalized candidates, the canonical universe, a review CSV, a search summary, and `current_universe.json`. Add `--no-approve` only when you want to review the canonical universe without making it the Fetch input yet.

### Run Fetch

Run Fetch against the approved universe. By default, `founder fetch` calls EODHD for live end-of-day quotes with gap-aware planning and archives the additional dated EODHD listing datasets currently supported by Founder. For first-time ISINs, quote fetching requests the full available history up to the run date by omitting `from` and sending `to=<run-date>`:

```bash
uv run founder fetch
```

The planned Bronze-only Fetch refactor will make Fetch safe for unattended cron execution. Live EODHD fetching should use bounded parallelism with default concurrency `2`, while still honoring shared request pacing, retry backoff, and `Retry-After`. Cron execution should use stable run ids, be resumable after partial failures, and prevent or clearly report overlapping runs for the same lake root and run id.

`--mock` writes deterministic local quote, Silver, Gold, and coverage outputs without using an EODHD token:

```bash
uv run founder fetch --mock
```

Without `--mock`, `founder fetch` writes the fetch plan, archives live Bronze quote, dividend, and split rows through the same planned windows, normalizes Silver quotes, derives Gold returns/correlation/covariance from accumulated Silver quotes, and writes coverage rows. With `--mock`, it writes deterministic local quote, Silver, Gold, coverage, and fetch-run metadata. Optional flags such as `--root`, `--run-id`, `--start-date`, `--end-date`, `--run-date`, `--limit`, and `--isin` are available for reproducible custom runs, but they are not required.

Pass `--start-date` and/or `--end-date` only when you want to restrict the EODHD history window:

```bash
uv run founder fetch --start-date 2020-01-01 --end-date 2026-07-12
```

After an initial full-history fetch, later live fetches inspect already stored Silver quotes before downloading. The planner coalesces missing quote dates into one backfill window per ISIN, then fetches through the selected run date so repeated small historical holes do not create hundreds of API calls:

```bash
uv run founder fetch
```

When you pass `--start-date`, Fetch uses that manual date window instead of automatic gap planning for quotes, dividends, and splits. ISINs without existing local quotes are still included and fetch full history up to the selected end date. Quote gaps are written to `lake/silver/coverage/quote_gaps.parquet`; after a successful gap backfill this table should shrink or become empty for the covered ISINs.

Automatic gap discovery is driven by stored Silver quote dates because quotes are the dense dated market series. The resulting fetch windows are applied to quotes, dividends, and splits through shared EODHD dataset strategies. Dividends and splits are archived as dated Bronze Parquet rows under `lake/bronze/{dataset}/{exchange}/{year}/{ISIN}.parquet`, matching the quote path shape. Any future ISIN data type, such as holdings, NAV, or factor series, should define its own strategy, coverage fields, gap table, and merge key before being added to automatic gap planning.

Use `--limit N` to restrict Fetch to the first `N` approved canonical ISINs, or `--isin` to restrict Fetch to one exact approved canonical ISIN. These two selectors are mutually exclusive:

```bash
uv run founder fetch --limit 10 --mock
uv run founder fetch --isin IE0000000001 --mock
```

Add `--debug` to either module command when you need more detailed logs under `.logs/`:

```bash
uv run founder search "UCITS ETF" --debug
uv run founder fetch --mock --debug
```

### Run The Full Mocked Pipeline

Use the dry run when you want Search, Fetch, and Gold together from built-in sample data:

```bash
uv run founder dry-run --root lake
```

The dry run writes candidates, a canonical universe, an approved universe pointer, a fetch plan, quote rows, coverage, and Gold inputs under the selected root.

### Run From Python

Use Python when you need custom fetchers or want to embed Search and Fetch in another workflow. This copy-paste command uses mocked quote payloads, so it does not need an EODHD token:

```bash
uv run python - <<'PY'
from datetime import UTC, date, datetime
from pathlib import Path

from founder.fetch import (
    fetch_quotes_to_bronze,
    normalize_quote_rows,
    write_fetch_manifests,
    write_fetch_plan,
    write_silver_quotes,
)
from founder.paths import LakePaths
from founder.search import (
    approve_universe,
    resolve_current_universe,
    write_canonical_universe,
    write_search_run,
)

paths = LakePaths(root=Path("lake"))
search_run_id = "search-demo"
fetch_run_id = "fetch-demo"
run_date = date(2026, 7, 12)

raw_candidates = [
    {
        "Code": "EXAMPLE",
        "Exchange": "XETRA",
        "Type": "ETF",
        "Country": "DE",
        "Currency": "EUR",
        "Isin": "IE0000000001",
        "Name": "Example UCITS ETF",
    }
]

write_search_run(
    raw_candidates,
    paths=paths,
    search_run_id=search_run_id,
    query="UCITS ETF",
    run_date=run_date,
    found_at=datetime(2026, 7, 12, tzinfo=UTC),
)
write_canonical_universe(paths, search_run_id)
approve_universe(paths, search_run_id)

plan = write_fetch_plan(
    paths,
    resolve_current_universe(paths),
    run_id=fetch_run_id,
    start_date=date(2026, 7, 10),
    end_date=run_date,
)

fetch_quotes_to_bronze(
    paths,
    plan,
    run_date=run_date,
    fetcher=lambda item: [
        {"date": "2026-07-10", "close": 100.0, "adjusted_close": 100.0},
        {"date": "2026-07-11", "close": 101.0, "adjusted_close": 101.0},
    ],
)
raw_by_symbol = {
    item["symbol"]: [
        {"date": "2026-07-10", "close": 100.0, "adjusted_close": 100.0},
        {"date": "2026-07-11", "close": 101.0, "adjusted_close": 101.0},
    ]
    for item in plan
}
quotes = normalize_quote_rows(
    plan,
    raw_by_symbol,
    fetched_at=datetime(2026, 7, 12, tzinfo=UTC),
    currency_by_isin={"IE0000000001": "EUR"},
)
write_silver_quotes(paths, quotes)
coverage = write_fetch_manifests(paths, run_id=fetch_run_id, quote_rows=quotes)

print({"plan_rows": len(plan), "quote_rows": len(quotes), "coverage_rows": len(coverage)})
PY
```

For real EODHD quote calls, replace the mocked `fetcher=lambda ...` with `eodhd_quote_fetcher(EodhdClient(load_eodhd_config()))` after setting `EODHD_API_TOKEN` in an ignored local environment file.

## Prerequisites

Use a `LakePaths` root to keep all generated artifacts in one deterministic local lake:

```python
from pathlib import Path

from founder.paths import LakePaths

paths = LakePaths(root=Path("data/local-run"))
```

The current table writer emits physical Apache Parquet files at `.parquet` table-contract paths. JSON pointers and review CSV files keep their native formats.

## Search Module

Use `founder.search` when you have raw EODHD search or exchange symbol-list rows and need a fetchable canonical universe.

### Normalize And Write Candidates

```python
from datetime import UTC, date, datetime

from founder.search import write_search_run

raw_candidates = [
    {
        "Code": "EXAMPLE",
        "Exchange": "XETRA",
        "Type": "ETF",
        "Country": "DE",
        "Currency": "EUR",
        "Isin": "IE0000000001",
        "Name": "Example UCITS ETF",
    }
]

candidates = write_search_run(
    raw_candidates,
    paths=paths,
    search_run_id="search-2026-07-12",
    query="UCITS ETF",
    run_date=date(2026, 7, 12),
    found_at=datetime(2026, 7, 12, tzinfo=UTC),
)
```

This writes:

- Bronze raw payloads under `lake/bronze/eodhd/search/run_date=YYYY-MM-DD/`.
- Silver normalized candidates under `lake/silver/search/search_run_id=.../candidates.parquet`.

### Select And Review The Canonical Universe

```python
from founder.search import approve_universe, write_canonical_universe

canonical = write_canonical_universe(paths, "search-2026-07-12")
pointer = approve_universe(paths, "search-2026-07-12")
```

`write_canonical_universe` selects one row per non-empty ISIN. It prefers `XETRA`; otherwise it chooses a deterministic fallback by exchange and code. Rows without ISIN are excluded from fetch input and counted in `search_summary.json`.

`approve_universe` writes `lake/silver/universe/current_universe.json`. That pointer is the formal handoff from Search to Fetch.

## Fetch Module

Use `founder.fetch` after Search has produced and approved a canonical universe.

### Build A Fetch Plan

```python
from datetime import date

from founder.fetch import write_fetch_plan
from founder.search import resolve_current_universe

canonical_path = resolve_current_universe(paths)
plan = write_fetch_plan(
    paths,
    canonical_path,
    run_id="fetch-2026-07-12",
    start_date=date(2020, 1, 1),
    end_date=date(2026, 7, 12),
)
```

Planning validates the canonical rows, rejects duplicate ISINs, rejects missing required fields, and derives EODHD symbols in `CODE.EXCHANGE` form. It does not call EODHD.

### Fetch Quotes To Bronze

```python
from founder.config import load_eodhd_config
from founder.fetch import eodhd_quote_fetcher, fetch_quotes_to_bronze
from founder.http import EodhdClient

config = load_eodhd_config()
client = EodhdClient(config)
fetcher = eodhd_quote_fetcher(client)

successes, errors = fetch_quotes_to_bronze(
    paths,
    plan,
    run_date=date(2026, 7, 12),
    fetcher=fetcher,
)
```

For tests or dry runs, pass a local function instead of `eodhd_quote_fetcher(client)`. Failed symbols are written as non-secret error rows and do not stop the whole batch.

### Build Silver Quotes And Write Coverage

```python
from datetime import UTC, datetime

from founder.fetch import build_coverage, normalize_quote_rows, write_fetch_manifests, write_silver_quotes

raw_by_symbol = {
    "EXAMPLE.XETRA": [
        {"date": "2026-07-10", "close": 100.0, "adjusted_close": 100.0},
        {"date": "2026-07-11", "close": 101.0, "adjusted_close": 101.0},
    ]
}

quotes = normalize_quote_rows(
    plan,
    raw_by_symbol,
    fetched_at=datetime(2026, 7, 12, tzinfo=UTC),
    currency_by_isin={"IE0000000001": "EUR"},
)
write_silver_quotes(paths, quotes)
coverage = write_fetch_manifests(paths, run_id="fetch-2026-07-12", quote_rows=quotes)
```

The Silver quote build deduplicates by `(isin, exchange, code, date)`, defaults missing OHLC values from `close`, and writes UTC timestamps. Coverage records first and last quote dates, observed rows, missing calendar periods, and the next fetch start with an overlap window.

## End-To-End Example

The fastest way to see the full Search-to-Fetch-to-Gold path is the mocked dry run:

```bash
uv run founder dry-run --root lake
```

The dry run requires no EODHD token. It writes deterministic sample artifacts and is safe to repeat.

## Artifacts

| Step | Main writer | Important outputs |
| --- | --- | --- |
| Search candidates | `write_search_run` | Bronze search payload, Silver candidates |
| Canonical universe | `write_canonical_universe` | `canonical_universe`, `search_summary.json`, review CSV |
| Approval | `approve_universe` | `current_universe.json` |
| Fetch plan | `write_fetch_plan` | Metadata fetch plan |
| Quote archive | `fetch_quotes_to_bronze` | Bronze quote payloads, error rows |
| Quote normalization | `normalize_quote_rows`, `write_silver_quotes` | Silver quote files under `silver/quotes/{exchange}/{ISIN}.parquet` |
| Gold inputs | `write_gold_inputs` | Gold return, correlation, and covariance files under `gold/{dataset}/{exchange}/{ISIN}.parquet` |
| Additional EODHD data | `fetch_raw_eodhd_datasets_to_bronze` | Bronze dividends and splits rows using the same planned windows as quotes |
| Coverage | `write_fetch_manifests` | Coverage rows, fetch-run manifest, coverage CSV |

## Common Failure Modes

- Missing ISINs are not fetchable. Review Search summaries before approval.
- Duplicate ISINs in canonical input are rejected by Fetch.
- Missing `code`, `exchange`, or other canonical fields are rejected before planning.
- EODHD `429` responses should go through `EodhdClient`, which handles pacing, retries, and `Retry-After`.
- Coverage gaps are visible in `coverage` rows; do not publish weights before reviewing them.

## Update Rules

Update this guide whenever:

- Search or Fetch function signatures change.
- A new Search-to-Fetch contract field becomes required.
- Storage paths, schema names, or lake artifact semantics change.
- The CLI gains standalone Search or Fetch commands.
