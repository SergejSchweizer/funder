# Architecture

Last reviewed: 2026-07-19

## Table Of Contents

- [Purpose](#purpose)
- [Read This First: What Founder Is Today](#read-this-first-what-founder-is-today)
- [System At A Glance](#system-at-a-glance)
- [Repository Map](#repository-map)
- [Execution Mode 1: Local CLI And Data Lake](#execution-mode-1-local-cli-and-data-lake)
- [Local Research Funnel](#local-research-funnel)
- [Local Lake Layout](#local-lake-layout)
- [Analytical And Portfolio Stack](#analytical-and-portfolio-stack)
- [Execution Mode 2: Hosted Development Runtime](#execution-mode-2-hosted-development-runtime)
- [Hosted Authorization Model](#hosted-authorization-model)
- [Shared Storage And Artifact Reuse](#shared-storage-and-artifact-reuse)
- [Docker Compose Topology](#docker-compose-topology)
- [Current Hosted Wiring Status](#current-hosted-wiring-status)
- [Security Boundaries](#security-boundaries)
- [Module Catalogue](#module-catalogue)
- [Dependency Direction](#dependency-direction)
- [Determinism, Idempotency, And Concurrency](#determinism-idempotency-and-concurrency)
- [Quality And Release Gates](#quality-and-release-gates)
- [Where A New Contributor Should Make Changes](#where-a-new-contributor-should-make-changes)
- [Known Current Limitations](#known-current-limitations)
- [Documentation Map](#documentation-map)
- [Update Rules](#update-rules)

## Purpose

Founder is a risk-aware ETF and fund research system built around EODHD end-of-day market data. It discovers and filters instruments, ingests and validates market history, computes reusable statistics, compares portfolio construction methods, produces explainable recommendations, and prepares Flatex-oriented trade rows without executing broker orders.

This document describes the architecture that exists on `main` now. It deliberately separates:

- code that is the active runtime;
- code that is an implemented and tested contract or adapter boundary;
- code that is not yet connected to the active runtime.

That distinction is essential because Founder currently contains both a mature local analytical pipeline and a hosted multi-tenant architecture whose security contracts are further developed than its production runtime wiring.

## Read This First: What Founder Is Today

Founder has two related execution modes.

```text
+-----------------------------------------------------------------------+
|                         Founder repository                            |
+-----------------------------------------------------------------------+
|                                                                       |
|  1. LOCAL ANALYTICAL MODE              2. HOSTED DEVELOPMENT MODE     |
|                                                                       |
|  Python CLI                            Browser research workspace      |
|       |                                      |                         |
|       v                                      v                         |
|  File-based lake                       Node Web container              |
|  Bronze / Silver / Gold                     |                         |
|       |                                      v                         |
|       v                                 FastAPI container              |
|  Statistics / portfolio                     |                         |
|  recommendation / CSV                       +--> in-memory API state   |
|                                             +--> PostgreSQL container  |
|                                                  exists, but is not    |
|                                                  the active API store  |
|                                                                       |
+-----------------------------------------------------------------------+
```

### Current-state summary

| Area | Status on `main` | What that means |
| --- | --- | --- |
| Local CLI research pipeline | Active | The primary end-to-end analytical implementation uses deterministic files under `lake/`. |
| Bronze, Silver, and Gold storage | Active | Parquet and JSON artifacts are the local source of truth. |
| Portfolio, backtest, stress, recommendation, and Flatex export logic | Active | These are Python library and CLI workflows; they do not execute broker orders. |
| Docker Compose topology | Active development runtime | PostgreSQL, API, and Web containers start with health checks and hardened mounts. |
| Hosted FastAPI route surface | Active local-development API | It currently uses deterministic in-memory repositories and development request headers. |
| Hosted browser workspace | Active local-development UI | It is served by `apps/web/server.js`, not Next.js or React. |
| PostgreSQL schema, roles, migrations, and RLS | Implemented contract | `founder.hosted_catalog` defines and tests them, but the active FastAPI state is not yet backed by PostgreSQL. |
| Google OIDC and server-side sessions | Implemented contract | `founder.hosted_auth` is tested, but it is not yet connected to the active Web/API request flow. |
| Encrypted EODHD credential vault | Implemented contract and local adapter | The API uses a deterministic in-memory development vault, not a production secret-manager-backed repository. |
| Shared observations, entitlements, scoped inputs, and artifact cache | Implemented contracts and proofs | They are tested independently and by the hosted cutover proof, but are not fully connected to the active API runtime. |
| Public production service | Not equivalent to current Compose runtime | Security/readiness gates and a deterministic cutover proof exist; live production adapters still require integration. |

A new contributor should therefore avoid two common mistakes:

1. Do not treat the local lake as a multi-user authorization mechanism.
2. Do not treat the presence of PostgreSQL and Google/OIDC contracts as proof that the active API already uses them.

## System At A Glance

```text
                                      EODHD
                                        |
                    +-------------------+-------------------+
                    |                                       |
                    v                                       v
          LOCAL CONFIG + HTTP                    HOSTED CREDENTIAL CONTRACT
                    |                             + USER INGESTION CONTRACT
                    v                                       |
       +--------------------------+                          v
       | Local discovery and lake |                SHARED OBSERVATION CONTRACT
       +--------------------------+                          |
                    |                                       v
                    v                              USER ENTITLEMENT SNAPSHOT
       REFERENCE -> BRONZE -> SILVER                          |
                    |                                       v
                    v                               SCOPED MARKET INPUTS
          UNIVARIATE STATISTICS                              |
                    |                                       v
                    v                              CONTENT-ADDRESSED ARTIFACTS
          UNIVARIATE FILTER                                  |
                    |                                       v
                    v                               USER-OWNED ANALYSIS RUN
          BIVARIATE STATISTICS                               |
                    |                                       v
                    +-------------------+-------------------+
                                        |
                                        v
                         MULTIVARIATE / PORTFOLIO CORE
                                        |
                 +----------------------+----------------------+
                 |                      |                      |
                 v                      v                      v
             SCORECARD               STRESS             PROFILE CANDIDATES
                 +----------------------+----------------------+
                                        |
                                        v
                                RECOMMENDATION
                                        |
                                        v
                         FLATEX TRADE PREPARATION CSV
                              no broker API execution
```

The mathematical core is shared conceptually by both modes. The local mode supplies explicit files. The hosted architecture is designed to supply already-authorized immutable rows. Hosted authorization must remain outside the mathematical functions.

## Repository Map

```text
founder/
|
|-- apps/
|   |-- api/
|   |   `-- Dockerfile              API container image
|   `-- web/
|       |-- Dockerfile              Web container image
|       |-- package.json            Minimal Node package
|       `-- server.js               Current browser workspace and client code
|
|-- src/founder/
|   |-- local pipeline modules      discovery, lake, statistics, portfolio
|   |-- hosted_* modules            hosted contracts, API, readiness, cutover
|   |-- portfolio_parts/            internal optimizer implementations
|   |-- evaluation_parts/           internal evaluation implementations
|   `-- cli.py                      local command-line entry point
|
|-- tests/                          unit, integration, security, and governance tests
|-- docs/
|   |-- hosted_security_architecture.md
|   |-- security/                   machine-readable hosted policy/readiness records
|   `-- backlog/                    detailed future-work design documents
|
|-- compose.yaml                    development topology
|-- compose.prod.example.yaml       production hardening example
|-- pyproject.toml                  package, dependencies, scripts, import rules
|-- CONTRACTS.md                    persisted data and table contracts
|-- GATES.md                        CI, branch protection, and quality gates
|-- DECISIONS.md                    durable architecture decisions
|-- RISKS.md                        active risks and mitigations
|-- BACKLOG.md                      PR-sized implementation plan and history
`-- AGENTS.md                       contributor and coding-agent workflow
```

The Python package targets Python 3.14. Core runtime dependencies are intentionally small: PyArrow for physical tables, FastAPI/Uvicorn for the hosted API, Psycopg for PostgreSQL integration, and Cryptography for hosted credential encryption.

## Execution Mode 1: Local CLI And Data Lake

The local pipeline is the most complete execution path. It uses explicit commands, deterministic selection artifacts, and a file-based lake.

### CLI boundary

`founder.cli` parses commands and delegates to `founder.workflows`. Business logic should not be added directly to argument parsing.

Current primary commands are:

```text
founder search
founder fetch-all-isins
founder metadata-filter
founder fetch-all-quotes
founder univariate-statistics
founder univariate-filter
founder bivariate-statistics
founder multivariate-statistics
```

The intended research sequence is:

```text
fetch-all-isins
      |
      v
metadata-filter
      |
      v
fetch-all-quotes
      |
      v
Bronze + Silver quote build
      |
      v
univariate-statistics
      |
      v
univariate-filter
      |
      v
bivariate-statistics
      |
      v
multivariate-statistics
      |
      v
portfolio comparison -> recommendation -> optional Flatex export
```

### Two discovery paths

Founder currently contains two discovery mechanisms:

```text
Legacy/local fixture path                 Current live metadata path
-------------------------                 --------------------------
founder search                            founder fetch-all-isins
checked-in CSV/JSON input                 EODHD exchange symbol lists
        |                                         |
        v                                         v
search candidates and                     reference/all_isins
canonical universe                                 |
                                                  v
                                           metadata-filter
```

`founder.search` remains useful for deterministic samples and compatibility. `founder.fetch_all_isins` is the live EODHD metadata reference path used by the newer five-stage ISIN workflow.

## Local Research Funnel

### 1. Instrument reference

`founder.fetch_all_isins` enumerates EODHD exchange symbol lists and stores ISIN-bearing listing metadata once under the reference area. This stage does not download full quote history and does not compute financial statistics.

### 2. Metadata selection

`founder.metadata_filter` reads the all-ISIN reference and applies conjunctive predicates. It writes an immutable selection directory containing:

```text
isins.parquet
manifest.json
```

A local convenience pointer identifies the latest selection. That pointer is acceptable for single-user local mode but is never authorization evidence for hosted mode.

### 3. Quote ingestion

`founder.fetch_all_quotes` and `founder.workflows.run_fetch_all_quotes_workflow` read an explicit or latest metadata selection, create a Bronze plan, call EODHD through the shared HTTP client, write quotes and companion raw dividends/splits, rebuild Silver quotes, and update coverage manifests.

The path is deliberately split:

```text
selection
    |
    v
Bronze plan
    |
    v
EODHD requests
    |
    +--> raw quote files
    +--> raw dividend files
    +--> raw split files
    |
    v
Silver quote normalization
    |
    v
coverage + gap information
```

### 4. Univariate statistics

`founder.univariate_statistics` calculates reusable metrics for each selected listing from validated Silver history. `founder.return_quality` is shared with Gold generation and prevents invalid prices from becoming fabricated zero returns.

### 5. Univariate filtering

`founder.univariate_filter` applies metric predicates to already-computed statistics. It does not recalculate statistics. The output is another persisted selection with stable membership and provenance.

### 6. Bivariate statistics

`founder.bivariate_statistics` computes one record per unordered listing pair. It:

- aligns both series on the exact common return dates;
- avoids duplicate symmetric work;
- skips duplicate same-ISIN listings by default;
- uses partitioned/bucketed storage for scale;
- can process pairs across all visible CPU cores unless a concurrency cap is supplied.

### 7. Selection statistics views

`founder.statistics_views` maps an existing metadata or univariate selection to the generic cached univariate and bivariate rows that belong to it. It never silently computes missing rows or returns an incomplete result as complete.

### 8. Multivariate and portfolio analysis

`founder.multivariate_statistics` has several entry points:

```text
write_multivariate_statistics
    deterministic baseline/research path

write_production_multivariate_statistics
    fail-closed data-quality and risk-model path

write_multivariate_recommendation
    production candidates + scorecard + stress + explanation

write_multivariate_trading_handoff
    explicit user-approved recommendation slot -> trade preparation
```

The browser and hosted API must eventually call these same core boundaries through scoped inputs. They must not reimplement formulas in JavaScript or API route handlers.

## Local Lake Layout

`founder.paths.LakePaths` is the single path-construction authority. Modules must not embed alternative lake layouts.

```text
lake/
|
|-- reference/
|   `-- all_isins/
|       |-- all_isins.parquet
|       `-- manifest.json
|
|-- bronze/
|   |-- quotes/<exchange>/<year>/<isin>.parquet
|   |-- dividends/<exchange>/<year>/<isin>.parquet
|   |-- splits/<exchange>/<year>/<isin>.parquet
|   `-- eodhd/search/run_date=<date>/...
|
|-- silver/
|   |-- quotes/<exchange>/<isin>.parquet
|   |-- metadata_filter/
|   |   |-- selection_id=<id>/isins.parquet
|   |   |-- selection_id=<id>/manifest.json
|   |   `-- current_selection.json
|   |-- univariate_filter/
|   |   |-- selection_id=<id>/isins.parquet
|   |   |-- selection_id=<id>/manifest.json
|   |   `-- current_selection.json
|   |-- plans/bronze_plans/<run>.parquet
|   |-- coverage/
|   |-- runs/
|   `-- search/search_run_id=<id>/...
|
|-- gold/
|   |-- returns/<exchange>/<isin>.parquet
|   |-- univariate_statistics/<exchange>/<isin>.parquet
|   |-- bivariate_statistics/version=<v>/bucket=<n>.parquet
|   |-- correlation_edges/...
|   |-- covariance/...
|   |-- features/...
|   |-- evaluation/
|   |   |-- return_matrices/
|   |   |-- asset_metrics/
|   |   |-- portfolio_returns/
|   |   |-- drawdowns/
|   |   |-- portfolio_metrics/
|   |   |-- frontier_points/
|   |   |-- frontier_weights/
|   |   |-- backtests/
|   |   |-- rebalance_events/
|   |   `-- tail_risk/
|   |-- weights/<objective>/...
|   |-- risk_contributions/<objective>/...
|   |-- clusters/...
|   `-- metrics/...
|
`-- trading/
    `-- flatex/<evaluation>-<portfolio>.csv
```

### Layer semantics

- **Reference** is a reusable instrument catalogue.
- **Bronze** is raw or near-raw provider material and ingestion provenance.
- **Silver** is normalized market data, selections, coverage, plans, and operational state.
- **Gold** is reusable statistics, evaluation inputs, optimizer outputs, and portfolio diagnostics.
- **Trading** contains explicit preparation exports, never broker execution state.

`founder.table_io` isolates JSON, Parquet, and review-CSV serialization. `founder.schemas` and [CONTRACTS.md](CONTRACTS.md) define the logical row contracts.

## Analytical And Portfolio Stack

The analytical stack is downstream-only. It does not call EODHD.

```text
Silver quotes
     |
     v
return_quality
     |
     +--> valid returns + quality diagnostics
     |
     v
gold / univariate_statistics / bivariate_statistics
     |
     v
aligned return matrix + covariance/correlation inputs
     |
     +-------------------+-------------------+
     |                   |                   |
     v                   v                   v
risk_model           evaluation          portfolio solvers
     |                   |                   |
     +-------------------+-------------------+
                         |
                         v
                      profiles
                         |
              +----------+----------+
              |                     |
              v                     v
           scorecard               stress
              +----------+----------+
                         |
                         v
                  recommendation
                         |
                         v
              explicit approval boundary
                         |
                         v
                      trading
```

### Return and quality semantics

- Portfolio wealth compounds simple returns.
- Statistical metrics can consume log returns where specified.
- Non-positive prices, duplicate dates, stale runs, and unexplained gaps are reported rather than converted to artificial returns.
- Production eligibility is explicit and includes observation-history thresholds.

### Risk models

`founder.risk_model` owns covariance estimation and diagnostics. Production-oriented paths can use shrinkage covariance and must report stability/eligibility diagnostics rather than silently accepting any matrix.

### Portfolio methods currently represented

The package includes or composes:

- Equal Weight;
- Inverse Volatility;
- constrained Minimum Variance;
- Maximum Sharpe as a comparison method;
- target-return Minimum Variance;
- Risk Parity and Equal Risk Contribution;
- true Hierarchical Risk Parity;
- Maximum Diversification;
- historical Minimum CVaR;
- profile-specific and ensemble candidates.

`founder.portfolio` is the public optimization surface. `founder.portfolio_parts` contains internal solver-focused modules. Solver diagnostics and constraint validation are part of the result contract.

### Profiles

`founder.profiles` defines versioned Defensive, Balanced, Income, and Growth contracts. The Balanced candidate combines True HRP, Equal Risk Contribution, and shrinkage Minimum Variance and then projects the aggregate weights back onto the permitted simplex.

Expected fail-closed conditions are represented as `infeasible` candidates with reasons, not unexplained crashes or silently relaxed constraints.

### Validation and recommendation

- `founder.scorecard` compares candidates on identical walk-forward windows and costs.
- Ranking uses out-of-sample evidence, not highest in-sample return.
- `founder.stress` provides deterministic historical, bootstrap, distribution-cut, correlation, and covariance scenarios.
- `founder.recommendation` explains inclusion, exclusion, constraints, disadvantages, and uncertainty.
- Every recommendation requires user approval and includes a no-guaranteed-return disclaimer.

### Tax, costs, and cash flow

`founder.tax`, `founder.costs`, `founder.cashflow`, and `founder.calculation_status` currently provide jurisdiction-neutral contracts and registries.

They do **not** yet provide verified production tax rates or real broker fee schedules. EU countries are known registry entries but remain explicitly unsupported until sourced and reviewed adapters are added. Missing values must remain `unavailable` or `unsupported`; they must never silently become zero.

### Trading boundary

`founder.trading` converts approved target weights and current prices into deterministic Flatex-oriented rows. It does not:

- choose the portfolio objective;
- approve a recommendation;
- authenticate with Flatex;
- place, modify, or cancel orders.

## Execution Mode 2: Hosted Development Runtime

The hosted architecture is designed around user-key-backed entitlements and shared physical data. Its complete threat model and prohibited designs are documented in [docs/hosted_security_architecture.md](docs/hosted_security_architecture.md).

### Intended hosted trust boundaries

```text
                            Internet / user device
                                      |
                                      v
+---------------------+       +---------------------+
| Browser             | HTTPS | Web app             |
| no provider secrets +------>| presentation only   |
+---------------------+       +----------+----------+
                                         |
                                         | API requests
                                         v
                              +----------+----------+
                              | API service         |
                              | auth + orchestration|
                              +----+------------+---+
                                   |            |
                         SQL + RLS |            | authorized object access
                                   v            v
                         +---------+---+   +----+----------------+
                         | PostgreSQL |   | Shared immutable     |
                         | catalogue  |   | observations/artifacts|
                         +---------+-+   +----+----------------+
                                   |          ^
                                   |          |
                                   |          | provider results
                                   |          |
                                   v          |
                         +---------+----------+--+
                         | External services     |
                         | Google OIDC + EODHD   |
                         +-----------------------+

Host secret files / secret manager
        |
        +--> PostgreSQL password
        +--> session secret
        +--> EODHD key-encryption key
        `--> Google client secret
```

The key rule is:

> Physical storage and cache hits can reduce duplicate writes and calculations, but they can never create user visibility.

## Hosted Authorization Model

The hosted data model follows an explicit chain.

```text
Google subject
     |
     v
internal user
     |
     v
encrypted EODHD credential
     |
     v
successful provider-backed download run
     |
     v
user grants to exact returned observation revisions
     |
     v
immutable User Data Snapshot
     |
     v
user-owned project + persisted selection
     |
     v
ScopedMarketInputs
     |
     v
return / univariate / bivariate / portfolio artifacts
     |
     v
user-owned analysis run reference
     |
     v
API response
```

### Why snapshots exist

A User Data Snapshot freezes the exact observation ids and revisions a user was authorized to see at one point in time. It prevents later downloads by another user from changing an old analysis.

A new user begins with no grants. An object already present in shared storage does not become visible until that user's own successful EODHD request returned it.

### Scoped analytical inputs

`founder.scoped_inputs` defines:

- `UserDataSnapshotRef`;
- `SelectionInputRef`;
- `ScopedMarketInputs`;
- `SnapshotReader` ports;
- a hosted entitlement-aware reader;
- a local file adapter.

The mathematical core receives rows and deterministic hashes. It does not receive database credentials, an unrestricted lake root, or permission to broaden the input universe.

## Shared Storage And Artifact Reuse

### Shared market observations

`founder.shared_observations` normalizes provider rows and derives stable content identities. Identical normalized observations can be stored once. Corrections create new revisions rather than overwriting the historical identity.

Shared payloads must not contain:

- user ids;
- session tokens;
- credential ids;
- credential fingerprints;
- plaintext provider keys.

### Shared analytical artifacts

`founder.artifact_cache` separates physical reuse from user visibility.

```text
Exact inputs + parameters + algorithm versions
                    |
                    v
          content-addressed artifact id
                    |
           +--------+--------+
           |                 |
           v                 v
 one physical artifact   dependency closure
           |                 |
           +--------+--------+
                    |
                    v
       authorized user/project/run reference
                    |
                    v
               API visibility
```

Physical cache keys exclude `user_id`. Authorization references include user, project, snapshot, and run context.

Return and univariate keys include exact snapshot hashes, date windows, parameters, quality-policy versions, and algorithm versions. Pair keys additionally include both return artifacts and the exact common-date alignment hash. Portfolio keys include selection membership, return matrix, risk model, constraints, costs, walk-forward windows, stress settings, recommendation template, and algorithm versions.

A direct artifact id or filesystem path is never sufficient authorization.

## Docker Compose Topology

`compose.yaml` starts three services and two named volumes.

```text
                    founder-public network

Browser
   |
   | :3000
   v
+------------------+        :8000        +------------------+
| web              +-------------------->| api              |
| Node server.js   |                     | Uvicorn/FastAPI  |
| no secrets       |                     | API secrets      |
| no data volume   |                     | shared-data vol  |
+------------------+                     +---------+--------+
                                                  |
                                                  | founder-internal
                                                  v
                                        +---------+--------+
                                        | postgres         |
                                        | PostgreSQL 17    |
                                        | internal only    |
                                        | postgres volume  |
                                        +------------------+

Named volumes:
  founder-postgres-data
  founder-shared-data
```

### Container hardening already present

- non-root API and Web images;
- read-only root filesystems where configured;
- writable temporary directories through `tmpfs`;
- `no-new-privileges`;
- all Linux capabilities dropped;
- service health checks and startup ordering;
- PostgreSQL not published to the host by default;
- external secret file paths supplied through Docker secrets;
- explicit CPU and memory limits.

### Secret ownership

```text
postgres_password  -> PostgreSQL only
session_secret     -> API only
eodhd_kek          -> API only
google_client_secret -> API only

Web receives none of these secrets.
```

## Current Hosted Wiring Status

This section is the most important description of the actual hosted runtime.

### Web container: active

`apps/web/server.js` is a dependency-free Node HTTP server. It renders a responsive HTML/CSS/JavaScript research workspace containing:

- session status;
- credential entry and deletion;
- download planning and submission;
- visible coverage;
- metadata filter controls;
- univariate, bivariate, and multivariate workflow controls;
- portfolio analysis and weights;
- report loading;
- logout and account deletion.

It calls the API with cookies, CSRF headers, and generated idempotency keys. It does not store provider keys or tokens in `localStorage` or `sessionStorage`.

It is **not** currently a Next.js or React application.

### API container: active local-development boundary

`founder.hosted_runtime` starts Uvicorn with `founder.hosted_api:app`.

`founder.hosted_api` exposes route groups for:

- health and session status;
- EODHD credential status/set/delete;
- download plan/run/status;
- visible datasets;
- projects;
- selections;
- analyses;
- metrics, returns, weights, and reports;
- account deletion.

Mutating routes require CSRF. Retry-sensitive routes accept idempotency keys. User-owned resources are checked against the current API user before they are returned.

However, the active API state is `HostedApiState`, an in-memory repository set intended for deterministic tests and local development. It currently uses:

- request headers such as `X-Founder-User` for development identity;
- a fixed development CSRF contract;
- an in-memory credential store and deterministic development KEK;
- in-memory projects, selections, downloads, analyses, audit events, and idempotency references;
- deterministic local responses rather than the full local analytical pipeline.

API state is therefore lost when the API process restarts, even though the PostgreSQL and shared-data Docker volumes persist.

### PostgreSQL: running infrastructure plus implemented schema contract

The PostgreSQL container is active in Compose. `founder.hosted_catalog` defines:

- deterministic migrations and checksums;
- owner, migrator, application, and read-only roles;
- forced Row-Level Security concepts;
- transaction-local authenticated user context;
- tables for users, external identities, sessions, credentials, projects, download runs, market objects, dataset snapshots, user grants, selections, analysis runs, artifacts, artifact inputs, and audit events.

The current FastAPI runtime does **not** yet use PostgreSQL repositories for `HostedApiState`.

### Google OIDC: implemented contract, not active request wiring

`founder.hosted_auth` implements and tests:

- authorization-code flow contracts;
- PKCE;
- state and nonce;
- injected token exchange and ID-token verification;
- stable Google `sub` identity mapping;
- opaque server-side sessions;
- CSRF, expiry, rotation, and revocation.

The current Web/API development path does not yet execute the real Google callback and cookie-session lifecycle. The visible Google Login link is therefore a UI surface, not proof of a live OIDC integration.

### Hosted EODHD ingestion: implemented contract, not active API provider call

`founder.user_ingestion` implements capability-aware plans, credential unwrapping boundaries, provider error redaction, usage accounting, shared observation publication, and snapshot publication rules.

The current API download route uses deterministic local observation identities for development. It is not yet connected to a live EODHD call through `founder.user_ingestion`.

### Entitlements, scoped inputs, and artifacts: implemented and proven, not fully API-wired

`founder.entitlements`, `founder.scoped_inputs`, and `founder.artifact_cache` are exercised by focused tests and by `founder.hosted_cutover`. The cutover proof creates multiple users, overlapping observations, snapshots, scoped inputs, and artifacts; verifies cross-user denial and idempotent reuse; deletes one user's entitlements; and checks browser-storage and local-CLI invariants.

This is a deterministic local proof. It does not call Google, EODHD, a broker, a cloud service, or production secret storage.

### Readiness and security gates: active validation

`founder.security_gates` validates repository and CI hardening from committed policy.

`founder.hosted_readiness` validates versioned licensing, privacy, retention, backup, restore, key rotation, role, incident-response, and broker-execution decisions.

These gates validate evidence and policy. They do not replace missing runtime adapters.

## Security Boundaries

### Credential lifecycle

```text
provider key entered
        |
        v
bounded plaintext in API process
        |
        v
random data-encryption key
        |
        +--> AES-GCM credential ciphertext
        |
        v
versioned external KEK wraps data key
        |
        v
PostgreSQL-compatible encrypted record

External KEK is not stored in Git, PostgreSQL, images, logs, or CI.
```

`founder.hosted_credentials` binds ciphertext to credential id, user id, provider, and schema version through authenticated associated data. Stored status responses are masked.

### Database boundary

The schema contract separates object ownership from application use. The runtime application role must not own tables and must not receive `BYPASSRLS`. User context is intended to be set transaction-locally before user-scoped queries.

### Browser boundary

The browser is presentation and orchestration only. It must not:

- receive the credential KEK;
- receive database credentials;
- mount shared storage;
- calculate portfolio recommendations independently;
- authorize artifact access;
- persist provider or Google tokens in browser storage;
- infer access from a guessed id or path.

### Shared-store boundary

Shared object existence is an optimization fact, not an authorization fact.

### Trading boundary

No current module automatically executes broker orders. The final action is an export or structured handoff requiring explicit approval.

## Module Catalogue

The catalogue below groups modules by responsibility. Public modules should depend toward the shared infrastructure and analytical core, not back toward CLI or provider orchestration.

### Shared infrastructure

| Module | Responsibility |
| --- | --- |
| `founder.__init__` | Import-safe package/version surface. |
| `founder.config` | Local EODHD configuration, timeouts, retries, spacing, and backoff. |
| `founder.http` | Tokenized EODHD requests, pacing, retry, `Retry-After`, and redaction. |
| `founder.logging` | Uniform logs and retention. |
| `founder.paths` | Deterministic local lake and export paths. |
| `founder.schemas` | Dataset registry, versions, fields, owners, and sort keys. |
| `founder.contracts` | Typed cross-module local contracts. |
| `founder.table_io` | JSON, Parquet, and CSV serialization boundary. |
| `founder.run_state` | Deterministic job manifests and resume metadata. |
| `founder.run_locks` | Per-root/per-layer operating-system locks. |
| `founder.selection_filters` | Shared predicate parsing and comparison semantics. |

### Discovery, selection, and ingestion

| Module | Responsibility |
| --- | --- |
| `founder.search` | Deterministic discovery over supplied candidate files and canonical-universe compatibility flow. |
| `founder.fetch_all_isins` | Live full EODHD metadata reference refresh. |
| `founder.metadata_filter` | Metadata-only persisted selections. |
| `founder.bronze` | Provider plans, raw quote/dividend/split writes, resumability, and coverage inputs. |
| `founder.silver` | Bronze-to-Silver normalized quote files. |
| `founder.fetch_all_quotes` | Standalone quote-refresh entry point. |
| `founder.universe_review` | Missing ISIN, currency, duplicate, and survivorship review. |
| `founder.workflows` | Operational composition behind the CLI. |

### Statistics and data quality

| Module | Responsibility |
| --- | --- |
| `founder.return_quality` | Shared price/return validation and production-history labels. |
| `founder.gold` | Generic returns, covariance, correlation, edges, and feature inputs. |
| `founder.univariate_statistics` | Per-listing statistics. |
| `founder.univariate_filter` | Metric-based persisted selections. |
| `founder.bivariate_statistics` | Exact common-date pair statistics and bucketed cache. |
| `founder.statistics_views` | Selection views over reusable statistic caches. |
| `founder.multivariate_statistics` | Selected portfolio-level orchestration, production adapter, recommendation, and handoff. |

### Evaluation, optimization, and decisions

| Module | Responsibility |
| --- | --- |
| `founder.evaluation` / `evaluation_parts` | Return matrices, asset/portfolio metrics, drawdowns, frontier, walk-forward, rebalancing, and tail-risk evaluation. |
| `founder.risk_model` | Covariance estimators and diagnostics. |
| `founder.portfolio` / `portfolio_parts` | Constraints, solver-backed objectives, weights, risk contributions, HRP, diversification, and CVaR. |
| `founder.profiles` | Defensive, Balanced, Income, and Growth candidate contracts. |
| `founder.scorecard` | Common out-of-sample model comparison. |
| `founder.stress` | Historical, bootstrap, and covariance sensitivity scenarios. |
| `founder.recommendation` | Explainable candidate comparison and deterministic report rendering. |
| `founder.trading` | Flatex-oriented preparation rows and CSV output. |
| `founder.tax` | Jurisdiction-neutral tax contracts and country registry. |
| `founder.costs` | Broker/venue/execution/FX/recurring-cost contracts and registry. |
| `founder.cashflow` | Neutral after-tax/after-cost cash-flow result contract. |
| `founder.calculation_status` | Exact/estimate/unavailable/unsupported status vocabulary. |

### Hosted boundaries

| Module | Responsibility | Current active wiring |
| --- | --- | --- |
| `founder.hosted_catalog` | PostgreSQL schema, roles, RLS, migrations. | Contract implemented; not backing active API state. |
| `founder.hosted_auth` | Google OIDC and server-side session contracts. | Contract implemented; not wired to active requests. |
| `founder.hosted_credentials` | Envelope-encrypted EODHD credential lifecycle. | In-memory development adapter used by API. |
| `founder.shared_observations` | Content-addressed immutable market objects. | Implemented/tested; not active API store. |
| `founder.entitlements` | Provider-run provenance, grants, and snapshots. | In-memory development implementation used by API/proofs. |
| `founder.user_ingestion` | User-key-backed provider orchestration. | Implemented/tested; not called by current API download route. |
| `founder.scoped_inputs` | Hosted/local snapshot readers and authorized inputs. | Implemented/tested; used by proof, not full API analysis path. |
| `founder.artifact_cache` | Exact reusable derived artifacts plus user references. | In-memory proof implementation; not full API persistence. |
| `founder.hosted_api` | FastAPI route and local-dev repository boundary. | Active. |
| `founder.hosted_runtime` | Container health and Uvicorn startup. | Active. |
| `founder.security_gates` | Repository/CI security-policy validator. | Active in quality gates. |
| `founder.hosted_readiness` | Hosted release evidence validator. | Active validation. |
| `founder.hosted_cutover` | Deterministic multi-user integration proof. | Active proof command/tests. |

### Delivery and governance

| Module | Responsibility |
| --- | --- |
| `founder.cli` | Local command parsing only. |
| `founder.pipeline` | Deterministic fixture/dry-run composition used by local verification. |
| `founder.quality` | Local equivalents of PR and main quality gates. |
| `founder.architecture_checks` | Import and architecture-boundary validation. |
| `founder.schema_validation` | Dataset registry consistency validation. |
| `founder.docs_refresh` | Documentation review-date report generation. |

## Dependency Direction

The preferred dependency direction is:

```text
CLI / Web / API
      |
      v
workflow and application services
      |
      v
selection / ingestion / analytics / portfolio services
      |
      v
contracts / schemas / paths / table I/O / logging
```

Forbidden or dangerous directions include:

```text
evaluation  -X->  EODHD HTTP or Bronze ingestion
portfolio   -X->  CLI parsing
shared infrastructure -X-> workflow modules
Web         -X->  direct PostgreSQL or shared filesystem access
math core   -X->  database credentials or user authorization decisions
hosted API  -X->  unrestricted global Silver/Gold scans
```

Import Linter currently enforces that evaluation does not depend on ingestion modules and that shared infrastructure does not depend on workflow modules.

## Determinism, Idempotency, And Concurrency

### Determinism

Founder uses stable ids and canonical ordering so that unchanged inputs produce unchanged logical outputs. Relevant identities include:

- selection ids from definitions and membership;
- job/run ids;
- snapshot hashes;
- observation ids and segment hashes;
- return, univariate, pair, and portfolio artifact ids;
- profile candidate ids;
- scorecard, stress, and recommendation ids.

Algorithm versions, quality policies, settings, constraints, and date windows belong in identities whenever they can change results.

### Idempotency

Repeated work should either return the existing valid result or calculate only missing deltas.

Examples:

- repeated identical provider rows do not create duplicate physical observations;
- repeated snapshot publication for one successful response returns the same logical snapshot;
- repeated statistic requests reuse exact artifacts;
- API idempotency keys prevent duplicate write operations in local development;
- repeated Flatex export generation does not create duplicate order rows.

### Local concurrency

```text
Provider and I/O-heavy stages:
  Bronze / Silver default concurrency = 2

CPU-heavy statistics stages:
  Univariate / Bivariate / Multivariate default = visible CPU cores

Safety:
  per-root module/layer locks prevent overlapping writers
  deterministic sorting removes worker-completion-order effects
```

### Hosted concurrency contract

Hosted ingestion is designed to serialize requests per credential, deduplicate shared objects, and publish grants/snapshots atomically only after complete successful responses.

The current in-memory API is suitable for deterministic local testing, not multi-process production concurrency or restart persistence.

## Quality And Release Gates

[GATES.md](GATES.md) is the source of truth. At a high level:

```text
feature branch or PR
        |
        v
+-----------------------------+
| pr-quality                  |
| lint + format               |
| strict typing               |
| unit/integration shards     |
| security policy             |
| commit/PR-title validation  |
+-------------+---------------+
              |
              v
      squash merge to main
              |
              v
+-----------------------------+
| merge-gate                  |
| full post-merge validation  |
| combined coverage >= 95%    |
| architecture checks         |
| schema validation           |
| hosted security/readiness   |
+-----------------------------+
```

Useful local commands include:

```bash
uv run founder-quality pr
uv run founder-quality merge
uv run python -m founder.security_gates
uv run python -m founder.hosted_readiness
uv run python -m founder.hosted_cutover
```

Tests should prove behavior at the module that owns the contract. Broad integration tests should compose public boundaries rather than bypassing them.

## Where A New Contributor Should Make Changes

| Change | Primary files/modules | Also review |
| --- | --- | --- |
| Add or change instrument metadata fields | `fetch_all_isins`, `metadata_filter`, `schemas`, `contracts` | `paths`, selection tests, `CONTRACTS.md` |
| Add an EODHD raw dataset | `bronze`, `http`, `workflows` | Silver normalization, coverage, redaction tests |
| Change quote normalization | `silver`, `return_quality` | Gold/statistics regression tests |
| Add a univariate metric | `univariate_statistics` or `gold` | schema, filter vocabulary, artifact version |
| Add a pair metric | `bivariate_statistics` | alignment identity, bucket schema, scale tests |
| Add an optimizer | `portfolio_parts`, `portfolio` | diagnostics, profiles, evaluation, recommendation |
| Add a risk estimator | `risk_model` | production eligibility and artifact identity |
| Change portfolio profiles | `profiles` | scorecard, stress, recommendation, constraints |
| Add verified country tax logic | `tax` adapter | source references, validity dates, calculation status |
| Add real broker costs | `costs` profile | sourced schedule, dates, cash-flow composition |
| Change Flatex export | `trading` | explicit approval and no-execution boundary |
| Add a hosted endpoint | `hosted_api` | auth, CSRF, idempotency, ownership, redaction tests |
| Wire PostgreSQL into API | new repository adapters around `hosted_catalog` | RLS transaction context, migrations, restart tests |
| Wire real Google login | `hosted_auth`, Web/API callback routes | cookie flags, state/nonce, token redaction |
| Wire hosted EODHD downloads | `user_ingestion`, credentials, shared observations, entitlements | quota, partial failures, snapshot publication |
| Change current Web UI | `apps/web/server.js` | API contracts, browser-storage security tests |
| Change persisted paths or rows | `paths`, `schemas`, `table_io`, `CONTRACTS.md` | migrations/compatibility and schema validation |
| Change CI or merge policy | workflow files, `quality`, `GATES.md` | governance tests and action pinning |

## Known Current Limitations

These are architectural facts, not hidden implementation details:

1. The active hosted API is in-memory and loses state on API restart.
2. The active hosted API does not yet use the PostgreSQL schema or RLS policies defined in `founder.hosted_catalog`.
3. The active hosted request path uses development identity headers rather than the implemented Google OIDC/session contracts.
4. The current Google Login link is not a complete live OAuth callback flow.
5. The hosted API download route does not yet call EODHD through `founder.user_ingestion`.
6. The hosted API does not yet persist shared observations, user snapshots, or analytical artifacts to the Compose volumes and PostgreSQL catalogue.
7. The hosted analysis route surface is a deterministic development boundary and is not yet the complete local analytical engine behind scoped inputs.
8. The Web application is a Node-rendered workspace, not Next.js/React.
9. Concrete country tax adapters, verified tax rates, and real Flatex fee profiles are not implemented in the neutral contract layer.
10. Income-quality, sustainable-income, distribution-cut, and NAV-erosion outputs remain unavailable where their required verified data stack is absent.
11. Founder prepares trades but does not execute broker orders.
12. The hosted cutover proof validates contracts with local deterministic adapters; it is not a live external-service deployment test.

Do not remove these distinctions from the documentation until the corresponding active runtime wiring and persistence tests exist.

## Documentation Map

- [README.md](README.md): product orientation and command usage.
- [ARCHITECTURE.md](ARCHITECTURE.md): current system structure and dependency boundaries.
- [CONTRACTS.md](CONTRACTS.md): persisted datasets, rows, versions, and paths.
- [docs/hosted_security_architecture.md](docs/hosted_security_architecture.md): hosted trust model, prohibited designs, and detailed authorization architecture.
- [GATES.md](GATES.md): quality gates, branch protection, sharding, coverage, and auto-merge.
- [DECISIONS.md](DECISIONS.md): durable decisions and their rationale.
- [RISKS.md](RISKS.md): risks, impact, and mitigation status.
- [BACKLOG.md](BACKLOG.md): active and completed PR-sized work.
- [AGENTS.md](AGENTS.md): contributor and coding-agent rules.
- `docs/security/hosted_security_policy.json`: machine-readable public-repository security policy.
- `docs/security/hosted_readiness.json`: machine-readable hosted readiness evidence.

## Update Rules

Update this file whenever a change alters any of the following:

- an active runtime adapter or persistence mechanism;
- the distinction between implemented contracts and active wiring;
- a module boundary or dependency direction;
- a CLI command or hosted route group;
- dataset ownership, naming, schema, or lake paths;
- Docker services, networks, volumes, health checks, or secret mounts;
- authentication, authorization, credential, entitlement, snapshot, or artifact semantics;
- portfolio methods, quality gates, recommendation logic, or trade-preparation boundaries;
- concurrency, idempotency, restart, backup, or restore behavior;
- quality gates, architecture checks, or required release commands.

Before merging architecture changes, also update `CONTRACTS.md`, `DECISIONS.md`, `RISKS.md`, `BACKLOG.md`, or hosted security documentation when their source-of-truth statements changed.