# Hosted Security Architecture

Last reviewed: 2026-07-19

## Purpose

This document is the PR84 baseline for the hosted multi-tenant Camovar architecture. It is authoritative for the
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

PR85 introduces the catalog baseline in `camovar.hosted_catalog`.

Required role boundaries:

- `camovar_owner` owns database objects but is not the application runtime.
- `camovar_migrator` applies migrations without `BYPASSRLS`.
- `camovar_app` is the runtime role, owns no tables, and cannot bypass Row-Level Security.
- `camovar_readonly` can inspect catalog tables without mutation rights.

Required catalog objects:

- user and Google external identity rows;
- server-side session rows;
- encrypted EODHD credential rows;
- projects, download runs, dataset snapshots, user grants, selections, and analysis runs;
- shared immutable market object and artifact catalogs;
- artifact input dependency closure;
- user-scoped audit events.

Every user-owned table must enable and force Row-Level Security. Hosted request handlers must bind the authenticated
internal user id through the transaction-local `camovar.current_user_id` setting before repository access. The catalog
stores credential ciphertext, nonce, wrapped data key, key version, associated data, HMAC fingerprint, and masked label;
it must not contain plaintext EODHD keys or large analytical tables.

## Google Authentication Baseline

PR86 introduces the Google-only OIDC and session baseline in `camovar.hosted_auth`.

Required OIDC behavior:

- Use authorization-code flow with PKCE S256, state, and nonce.
- Validate the exact configured redirect URI during token exchange.
- Verify Google ID-token issuer, audience, expiry, nonce, subject, and verified email before session creation.
- Use Google's stable `sub` claim as the identity key; email and display name are mutable metadata.
- Keep optional hosted-domain allowlisting disabled by default.

Required session behavior:

- Issue opaque session and CSRF tokens only after a verified Google callback.
- Store only HMAC hashes server-side, never browser tokens in plaintext persistence.
- Enforce HttpOnly, Secure, SameSite cookies at the web/API boundary that consumes these contracts.
- Reject expired, revoked, missing, replayed, and CSRF-invalid sessions.
- Permit concurrent sessions for one user while allowing individual session revocation and rotation.
- Never log or return Google tokens after session establishment.

## Encrypted EODHD Credential Vault Baseline

PR87 introduces the credential vault baseline in `camovar.hosted_credentials`.

Required credential behavior:

- Persist at most one logical active EODHD credential per user.
- Encrypt provider keys with a random per-credential data-encryption key.
- Wrap the data-encryption key with a versioned KEK loaded from external runtime secret material.
- Bind ciphertext to credential id, user id, provider, and schema version as authenticated associated data.
- Store only ciphertext, nonce, wrapped data key, wrap nonce, KEK version, associated data, HMAC fingerprint, masked
  label, and lifecycle status.
- Return only masked client-safe status metadata.
- Fail closed on wrong user context, tampering, unavailable KEK version, revoked/deleted credentials, or failed
  authenticated decryption.
- Support KEK rotation by rewrapping from an authenticated unwrap without requiring provider-key re-entry.

Plaintext provider keys may exist only in bounded process memory during set, validation, unwrap-for-provider-call, and
rotation. They must never be persisted, logged, returned to clients, or passed to workers that do not perform provider
access.

## Shared Market Observation Store Baseline

PR88 introduces the shared immutable observation store in `camovar.shared_observations`.

Required shared-store behavior:

- Normalize provider observations into canonical payload ordering.
- Reject shared payloads containing `user_id`, `credential_id`, `session_token`, or credential fingerprint fields.
- Derive observation ids from provider, dataset type, listing identity, business key, payload hash, and schema version.
- Retain corrected historical values as new content identities instead of overwriting prior observations.
- Deduplicate identical observations and identical segments by content hash.
- Publish Parquet segments through temporary writes and atomic rename.
- Write deterministic segment manifests with row count, segment hash, storage URI, and observation ids.
- Validate segment hashes when reading previously published shared content.

Shared storage paths, segment hashes, and observation ids are catalog identities only. They must not be accepted as
authorization credentials and must not be returned from unauthenticated endpoints.

## User Entitlement And Snapshot Baseline

PR89 introduces entitlement and immutable snapshot contracts in `camovar.entitlements`.

Required entitlement behavior:

- A new user starts with no visible provider observations.
- A grant may be created only from a `succeeded` provider-backed download run for the same authenticated user.
- Failed, partial, planned, running, or empty provider runs cannot publish grants.
- Shared object existence, listing identity, date range, or content hash never creates access.
- User Data Snapshots contain the exact sorted observation ids visible to the user under a revision policy.
- Snapshot hashes are deterministic and independent of grant publication order.
- Old snapshots remain immutable when later refreshes add observations.
- Account deletion removes user grants and current pointers without deleting shared physical observations still
  referenced by other users.

## User-Key-Backed Ingestion Baseline

PR90 introduces user-scoped provider planning in `camovar.user_ingestion`.

Required ingestion behavior:

- Plans are derived from authenticated user id, credential id, dataset type, requested listings, capability tier,
  requested as-of date, and optional prior snapshot.
- Free and paid capabilities bound symbol counts and whether gap refresh is allowed.
- Plaintext provider keys are unwrapped only immediately before the outbound provider call.
- Provider errors are redacted before they cross the ingestion boundary.
- Rate-limited, partial, failed, or empty responses cannot publish grants or snapshots.
- Existing shared physical observations can deduplicate writes, but the current user's provider request must still run
  before access is granted.
- Usage accounting records successful provider requests.

## Scoped Analytical Input Baseline

PR91 introduces scoped analytical input contracts in `camovar.scoped_inputs`.

Required scoped-input behavior:

- Hosted analytical workflows receive `ScopedMarketInputs`, not unrestricted lake readers.
- `UserDataSnapshotRef` binds user id, snapshot id, and snapshot hash.
- `SelectionInputRef` binds selection id, selection hash, and exact member observation ids.
- Hosted readers reject selections outside the user-owned snapshot.
- Extra global rows cannot influence analytics unless the user's snapshot and selection authorize them.
- Local CLI compatibility is preserved through explicit local readers over provided files or rows.

## Return And Univariate Artifact Cache Baseline

PR92 introduces the first shared analytical cache in `camovar.artifact_cache`; PR93 extends the same authorization
boundary to bivariate pair artifacts; PR94 extends it to portfolio-level downstream artifacts and user-owned analysis
runs.

Required cache behavior:

- Return artifact ids include listing id, quote snapshot hash, dividend snapshot hash, date window, return parameters,
  quality-policy version, and algorithm version.
- Univariate artifact ids include the exact return artifact id, metric parameters, confidence level, quality-policy
  version, and algorithm version.
- Physical artifacts are globally deduplicated by exact input hash.
- User-visible artifact references are separate from physical artifacts.
- Direct artifact ids or paths are not authorization evidence.
- A univariate artifact can be created only when the user has a visible reference to its return artifact dependency.
- Bivariate artifact ids include the canonical unordered pair of return artifact ids, the exact common-date alignment
  hash, metric parameters, minimum-observation policy, and algorithm version.
- Bivariate alignment hashes include aligned dates and both return values, so same-count date windows with corrected
  values or newly common dates produce different artifacts.
- A bivariate artifact can be created only when the user has visible references to both return artifact dependencies.
- Bucketed pair storage must fail closed when the expected bivariate artifact id is absent from the resolved bucket.
- Portfolio artifact ids include sorted authorized listing-input artifact ids, selection definition and membership,
  return matrix, risk model, constraints, optimizer settings, costs, walk-forward windows, stress settings,
  recommendation template, and algorithm versions.
- Portfolio physical artifact keys must not include `user_id`, `project_id`, or run ids.
- Portfolio responses resolve through user/project-owned analysis runs, not direct shared artifact ids.
- Cross-project run access and stale project snapshot pointers fail closed before a portfolio artifact is returned.

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
