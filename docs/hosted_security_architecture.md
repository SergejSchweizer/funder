# Hosted Security Architecture

Last reviewed: 2026-07-19

## Purpose

This document is the PR84 baseline for the hosted multi-tenant Founder architecture. It is authoritative for the
hosted threat model until later PRs replace individual sections with implemented contracts, migrations, API routes,
or deployment evidence.

Hosted mode must preserve the local analytical core while adding authenticated, user-scoped access to provider-backed
market data and derived artifacts. Local CLI mode may keep using explicit local adapters and local secret files.

## Trust Boundaries

```text
browser
  |
  | OIDC redirects, session cookie, CSRF token
  v
web app --------------+
  |                   |
  | authenticated API | no secrets, no lake mounts
  v                   |
api service           |
  |                   |
  | transaction-local authenticated user id
  v                   |
postgresql with RLS   |
  |                   |
  | object refs, grants, runs, audit records
  v                   |
shared immutable store <---- eodhd provider
  ^
  |
external KEK / secret mount
```

Boundary ownership:

- **Browser** owns user interaction only. It must never store EODHD keys, Google tokens, session tokens, ciphertext,
  credential fingerprints, internal paths, or shared artifact ids in browser storage or URLs.
- **Web app** owns presentation and route state. It consumes API contracts and must not perform financial
  calculations, authorization decisions, provider calls, or direct lake reads.
- **API service** owns authentication enforcement, CSRF checks, input validation, audit events, entitlement checks,
  and orchestration. It may unwrap an EODHD key only immediately before a provider request.
- **PostgreSQL** owns user, identity, credential metadata, project, grant, snapshot, analysis, artifact, and audit
  catalogs. User-owned rows require Row-Level Security and transaction-local user context.
- **External key-encryption key** owns the ability to unwrap data-encryption keys. It must stay outside Git,
  PostgreSQL, container images, CI artifacts, ordinary logs, and database backups.
- **Shared immutable store** owns normalized provider observations and content-addressed analytical artifacts. Physical
  object existence never grants access.
- **EODHD** is an external provider boundary. Every hosted entitlement requires a successful request made with the
  authenticated user's active credential.

## Data Classes

| Class | Examples | Storage rule |
| --- | --- | --- |
| Authentication secrets | Google client secret, session signing key | Runtime secret only |
| Provider secrets | EODHD user key, credential validation response | Encrypted at rest; plaintext only in bounded memory |
| Key material | KEK, wrapped DEK, nonce, associated data | KEK external; wrapped DEK and nonce in PostgreSQL |
| Personal data | Google subject, email, user profile, audit actor | PostgreSQL with RLS and deletion policy |
| User ownership data | projects, selections, grants, snapshots, analysis runs | PostgreSQL with RLS and immutable references |
| Shared market data | quotes, dividends, splits, metadata observations | Immutable shared store plus catalog identities |
| Shared derived data | univariate, bivariate, multivariate, reports | Content-addressed store; visible only through user runs |
| Local-only data | local lake files, local secret config | Explicit local adapter; not hosted authorization evidence |

## PostgreSQL Catalog Baseline

PR85 introduces the catalog baseline in `founder.hosted_catalog`.

Required role boundaries:

- `founder_owner` owns database objects but is not the application runtime.
- `founder_migrator` applies migrations without `BYPASSRLS`.
- `founder_app` is the runtime role, owns no tables, and cannot bypass Row-Level Security.
- `founder_readonly` can inspect catalog tables without mutation rights.

Required catalog objects:

- user and Google external identity rows;
- server-side session rows;
- encrypted EODHD credential rows;
- projects, download runs, dataset snapshots, user grants, selections, and analysis runs;
- shared immutable market object and artifact catalogs;
- artifact input dependency closure;
- user-scoped audit events.

Every user-owned table must enable and force Row-Level Security. Hosted request handlers must bind the authenticated
internal user id through the transaction-local `founder.current_user_id` setting before repository access. The catalog
stores credential ciphertext, nonce, wrapped data key, key version, associated data, HMAC fingerprint, and masked label;
it must not contain plaintext EODHD keys or large analytical tables.

## Prohibited Designs

Hosted work must not introduce these designs:

- SQLite as the hosted primary application database.
- Session-only or browser-stored EODHD credentials.
- Plaintext EODHD keys in PostgreSQL, Git, logs, URLs, Docker layers, images, browser storage, or CI.
- A hosted endpoint that reads unrestricted Silver or Gold paths, global current-selection pointers, or local lake
  scans instead of a resolved user snapshot.
- A grant created from shared object existence without a successful current-user EODHD response.
- A cache hit that reveals, lists, or serves an artifact without authorization to every input in its dependency
  closure.
- Direct user access by filesystem path, database id, content hash, credential fingerprint, or shared artifact id.
- Public-hosted mode while provider licensing, privacy, backup, credential, and security gates are unresolved.

## User Data Snapshot Semantics

A User Data Snapshot is the only hosted input boundary for analysis. It contains the exact observation revisions that
the authenticated user may see at one point in time.

Snapshot rules:

- A new user starts with no market-data grants and an empty visible universe.
- A provider request with User A's key cannot expand User B's visible data.
- Shared physical observations may deduplicate storage, but not authorization.
- Historical corrections remain invisible to a user until that user performs a successful refresh that returned those
  revisions.
- Old analysis runs remain pinned to their original immutable snapshot.
- Account deletion removes credentials and user grants without deleting shared objects still referenced by other users.

## Artifact Reuse Semantics

Physical analytical artifacts are globally deduplicated by exact input hashes and algorithm versions. Visibility is
separate from physical identity.

Required artifact identity inputs:

- authorized immutable snapshot refs;
- selection definition and membership;
- exact quote, dividend, and split payload hashes;
- exact return-date alignment hashes for pairs;
- metric parameters, risk model settings, optimizer constraints, costs, walk-forward windows, stress settings, and
  report templates;
- dataset schema versions and algorithm versions.

## Threat Model

Primary attacker goals:

- read another user's market data, derived metrics, portfolio artifacts, projects, or reports;
- use object existence, dates, hashes, or cache ids as an oracle for inaccessible data;
- recover EODHD credentials from database dumps, logs, backups, build artifacts, browser storage, or CI;
- create grants without paying the provider request cost through the user's own key;
- widen an analysis by exploiting global current pointers or unrestricted filesystem readers;
- replay authentication callbacks, forge sessions, bypass CSRF, or use stale sessions;
- restore a database backup without the correct key material and accidentally expose credentials.

Required mitigations:

- Google-only OpenID Connect with stable `sub`, state, nonce, strict audience/issuer checks, and server-side sessions.
- PostgreSQL Row-Level Security for user-owned tables plus least-privilege roles.
- Envelope encryption for provider credentials with associated data binding to credential id, user id, provider, and
  schema version.
- User-key-backed download provenance before entitlement publication.
- Immutable User Data Snapshots before analysis.
- Scoped analytical reader ports for hosted workflows and a separate local adapter for CLI mode.
- Content-addressed caches that require exact input-hash equality and authorization to the dependency closure.
- Redaction for URLs, tokens, provider diagnostics, ciphertext metadata, internal paths, and personal data in logs.
- Separate backup paths for encrypted database/shared storage and external key recovery material.

## Backlog Mapping

| Hosted requirement | Active PR |
| --- | --- |
| Architecture decision, threat model, and prohibited designs | PR84 |
| PostgreSQL catalog, roles, migrations, and RLS | PR85 |
| Google-only OIDC and server-side sessions | PR86 |
| Encrypted EODHD credential vault and KEK rotation | PR87 |
| Shared content-addressed market observation store | PR88 |
| User grants, provenance, and immutable snapshots | PR89 |
| User-key-backed ingestion and refresh planning | PR90 |
| Scoped analytical input boundary and local adapter compatibility | PR91 |
| Content-addressed univariate and return artifact cache | PR92 |
| Content-addressed bivariate cache and exact alignment | PR93 |
| Content-addressed portfolio, backtest, and report artifacts | PR94 |
| Docker Compose hosted development runtime | PR95 |
| FastAPI user, credential, download, project, and analysis API | PR96 |
| Google-authenticated Web UI and research funnel | PR97 |
| Public-repository CI, supply-chain, and deployment hardening | PR98 |
| Licensing, privacy, retention, backup, restore, and key-rotation readiness | PR99 |
| End-to-end hosted cutover and multi-user proof | PR100 |
