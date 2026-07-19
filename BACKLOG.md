# Backlog

Last reviewed: 2026-07-19

## Table Of Contents

- [Backlog Policy](#backlog-policy)
- [Completed PR History](#completed-pr-history)
- [Current Architectural Decision](#current-architectural-decision)
- [Hosted Multi-Tenant Founder PR Stack](#hosted-multi-tenant-founder-pr-stack)
- [Series Completion Gate](#series-completion-gate)
- [Update Rules](#update-rules)

## Backlog Policy

This file tracks active PR-sized work and completed PR history. Completed PR entries are kept as an audit trail so
merged scope, PR numbers, and historical identifiers remain visible without reading Git history first.

The previously open backlog entries are superseded by the stack below. Their PR numbers, branch plans, dependency chains, and acceptance criteria must not be treated as active work unless listed in the active stack. New work starts at PR84 so historical identifiers are never reused.

Every active item must contain `Branch`, `Git status`, `PR`, `Priority`, `Depends on`, `Scope`, `Acceptance`, `Security`, `Determinism`, and `Idempotency`. Branches are stacked in the declared dependency order until their predecessors merge.

Completed or implemented entries must not be deleted from this file. If a finished entry is superseded, keep it in
the completed-history section with its final status and link the replacing PR or decision.

## Completed PR History

These entries are historical and not active work. They are kept to preserve completed scope, PR links, and stable
backlog identifiers.

| ID | Title | Final status |
| --- | --- | --- |
| PR01 | Project Package And Quality Baseline | merged. PR: https://github.com/SergejSchweizer/founder/pull/1 |
| PR02 | Shared Configuration, HTTP, And Contract Primitives | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR03 | Simple Bronze/Silver/Gold Lake Layout Contract | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR04 | Search Module: EODHD Query And Raw Candidate Capture | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR05 | Search Module: Canonical ISIN Selection Contract | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR06 | Search Module: Review Artifacts And Active Universe Pointer | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR07 | Bronze Module: Input Contract Validation And Planning | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR08 | Bronze Module: EOD Quote Download To Bronze | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR09 | Silver Quote Build Baseline | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR10 | Bronze Module: Identifier Mapping Capture | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR11 | Bronze Module: Coverage, Errors, And Monthly Refresh Behavior | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR12 | Gold Inputs: Returns, Correlation, And Covariance Baseline | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR13 | Finalization: End-To-End Dry Run, Docs, And Release Checklist | merged. PR: https://github.com/SergejSchweizer/founder/pull/3 |
| PR14 | Bronze Process: Cron-Safe Bronze Ingestion And Medallion Builds | merged. PR: https://github.com/SergejSchweizer/founder/pull/13 |
| PR15 | Gold Evaluation Dataset Contracts And Paths | merged. PR: https://github.com/SergejSchweizer/founder/pull/20 |
| PR16 | Evaluation Module: Return Matrix And Asset Metrics | merged. PR: https://github.com/SergejSchweizer/founder/pull/21 |
| PR17 | Evaluation Module: Portfolio Returns And Drawdown Metrics | merged. PR: https://github.com/SergejSchweizer/founder/pull/24 |
| PR18 | Portfolio Module: Core Optimization Objectives And Target Weights | merged. PR: https://github.com/SergejSchweizer/founder/pull/26 |
| PR19 | Portfolio Module: Risk Parity And Equal Risk Contribution | merged. PR: https://github.com/SergejSchweizer/founder/pull/32 |
| PR20 | Evaluation Module: Walk-Forward Backtesting | merged. PR: https://github.com/SergejSchweizer/founder/pull/34 |
| PR21 | Evaluation Module: Rebalancing Simulation | merged. PR: https://github.com/SergejSchweizer/founder/pull/34 |
| PR22 | Portfolio Module: Hierarchical Risk Parity | merged. PR: https://github.com/SergejSchweizer/founder/pull/34 |
| PR23 | Portfolio Module: Maximum Diversification Objective | merged. PR: https://github.com/SergejSchweizer/founder/pull/34 |
| PR24 | Evaluation Module: Efficient Frontier Generator | merged. PR: https://github.com/SergejSchweizer/founder/pull/34 |
| PR25 | Portfolio Module: CVaR And Tail-Risk Optimization | merged. PR: https://github.com/SergejSchweizer/founder/pull/34 |
| PR26 | Evaluation CLI And Dry-Run Integration | merged. PR: https://github.com/SergejSchweizer/founder/pull/34 |
| PR27 | Gold Correlation Edge Dataset Baseline | merged. PR: https://github.com/SergejSchweizer/founder/pull/28 |
| PR28 | Gold Spearman Correlation Edges | merged. PR: https://github.com/SergejSchweizer/founder/pull/30 |
| PR29 | Gold Correlation Edges: Skip Same-ISIN Pairs | merged. PR: https://github.com/SergejSchweizer/founder/pull/40 |
| PR30 | Gold Pair Statistics Boundary Refactor | merged. PR: https://github.com/SergejSchweizer/founder/pull/44 |
| PR31 | Dataset Contract Registry Refactor | merged. PR: https://github.com/SergejSchweizer/founder/pull/44 |
| PR32 | Evaluation And Portfolio Package Boundary Refactor | merged. PR: https://github.com/SergejSchweizer/founder/pull/44 |
| PR33 | Unified Run State And Job Manifest Refactor | merged. PR: https://github.com/SergejSchweizer/founder/pull/44 |
| PR34 | Production Optimizer Interface And Diagnostics Refactor | merged. PR: https://github.com/SergejSchweizer/founder/pull/44 |
| PR35 | Enforce Real Evaluation And Portfolio Package Boundaries | merged. PR: https://github.com/SergejSchweizer/founder/pull/46 |
| PR36 | Extract Scalable Gold Pair Statistics Engine | merged. PR: https://github.com/SergejSchweizer/founder/pull/46 |
| PR37 | Type Critical Dataset Rows And Contract Validation | merged. PR: https://github.com/SergejSchweizer/founder/pull/46 |
| PR38 | Split CLI Parsing From Workflow Execution | merged. PR: https://github.com/SergejSchweizer/founder/pull/46 |
| PR39 | Add Import-Boundary And Scale-Guard Quality Gates | merged. PR: https://github.com/SergejSchweizer/founder/pull/46 |
| PR40 | Three-Module Boundaries And Public Contract Skeleton | merged. PR: https://github.com/SergejSchweizer/founder/pull/51 |
| PR41 | Refresh Catalog Contracts And Stable Instrument Identities | merged. PR: https://github.com/SergejSchweizer/founder/pull/51 |
| PR42 | Selection Predicate And Metric-Requirement Contracts | merged. PR: https://github.com/SergejSchweizer/founder/pull/51 |
| PR43 | Selection Identity, Candidate And Final Membership Contracts | merged. PR: https://github.com/SergejSchweizer/founder/pull/51 |
| PR44 | Update Contracts, Pinned Inputs, And Shared Work Planner | merged. PR: https://github.com/SergejSchweizer/founder/pull/51 |
| PR45 | Refresh Complete EODHD Catalog Synchronization | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR46 | Refresh All-ISIN Market Data And Versioned Inputs | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR47 | Refresh Service, Standalone CLI, And Atomic Publication | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR48 | Selection Service, Current Pointer, And Standalone CLI | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR49 | Update Incremental Per-ISIN Metric Cache | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR50 | Update Screening Classifications And Selection Finalization | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR51 | Update Selection Calendar And Comparable Metric Cache | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR52 | Update Incremental Pair Metric Cache | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR53 | Update Evaluation Profiles And Selection Analysis Manifests | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR54 | Update Service, Standalone CLI, And Atomic Publication | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR55 | Three-Module Cutover, Legacy Migration, And Documentation | merged. PR: https://github.com/SergejSchweizer/founder/pull/53 |
| PR56 | Return Semantics And Data-Quality Gate | merged. PR: https://github.com/SergejSchweizer/founder/pull/83 |
| PR57 | Instrument-Level Rebalancing Drift And Cost Basis | merged. PR: https://github.com/SergejSchweizer/founder/pull/85 |
| PR58 | Risk Model Package And Covariance Diagnostics | merged. PR: https://github.com/SergejSchweizer/founder/pull/89 |
| PR59 | Production Numerical Solver Boundary | addressed; no dedicated PR under this branch name |
| PR60 | Production Minimum Variance And Equal Risk Contribution | merged. PR: https://github.com/SergejSchweizer/founder/pull/101 |
| PR61 | True HRP And Minimum CVaR Optimizers | merged. PR: https://github.com/SergejSchweizer/founder/pull/104 and https://github.com/SergejSchweizer/founder/pull/109 |
| PR62A | Jurisdiction-Neutral Tax, Cost, And Cash-Flow Contracts | merged. PR: https://github.com/SergejSchweizer/founder/pull/112 |
| PR63 | Portfolio Profile Contracts And Balanced Ensemble Candidate | merged. PR: https://github.com/SergejSchweizer/founder/pull/113 |
| PR64 | Walk-Forward Model Comparison Scorecard | merged. PR: https://github.com/SergejSchweizer/founder/pull/114 |
| PR65 | Stress, Bootstrap, And Sensitivity Analysis | merged. PR: https://github.com/SergejSchweizer/founder/pull/115 |
| PR66 | Explainable Recommendation Report | merged. PR: https://github.com/SergejSchweizer/founder/pull/116 |
| PR69 | Multivariate Statistics Baseline Module And CLI | merged. PR: https://github.com/SergejSchweizer/founder/pull/79 |
| PR70 | Multivariate Production Portfolio Adapter | merged. PR: https://github.com/SergejSchweizer/founder/pull/117 |
| PR71 | Multivariate Income And Recommendation Outputs | merged. PR: https://github.com/SergejSchweizer/founder/pull/118 |
| PR72 | Multivariate Trading And Monitoring Handoff | merged. PR: https://github.com/SergejSchweizer/founder/pull/119 |
| PR73 | Generic Listing And Pair Statistics Cache | merged. PR: https://github.com/SergejSchweizer/founder/pull/80 |
| PR74 | Selection Statistics Views | merged. PR: https://github.com/SergejSchweizer/founder/pull/120 |
| PR75 | Multivariate Selection Cache Consumption | merged. PR: https://github.com/SergejSchweizer/founder/pull/121 |

## Current Architectural Decision

Founder remains a public open-source repository, while the hosted deployment is a private runtime environment.

The target system has these non-negotiable properties:

- Google is the only end-user authentication provider.
- PostgreSQL is the primary application database for users, identities, encrypted provider credentials, projects, download provenance, entitlements, selections, analysis runs, and artifact catalogs.
- EODHD keys are encrypted at rest with envelope encryption. The key-encryption key is never stored in Git, PostgreSQL, container images, build artifacts, logs, or GitHub Actions.
- Runtime secrets live outside the repository checkout and are mounted only into services that require them.
- EODHD market observations are stored once in a shared, content-addressed, immutable physical store.
- A user can see only observations that were returned by an EODHD request executed with that user's own stored key.
- Existing shared observations may prevent a duplicate physical write, but may never create a user entitlement without a successful user-key-backed provider request.
- New observations downloaded by one user do not become visible to another user until that other user performs a successful refresh with their own key.
- Every user analysis is pinned to an immutable User Data Snapshot containing the exact observations and revisions visible to that user.
- Univariate, bivariate, multivariate, portfolio, backtest, and report artifacts are globally deduplicated by exact input hashes and algorithm versions, while visibility is granted only through user-owned analysis runs.
- Hosted analytical code must consume resolved scoped inputs and must never scan unrestricted global Silver or Gold data.
- The local CLI and analytical core remain usable without Google authentication or PostgreSQL through explicit local adapters.
- Public hosting remains blocked until provider licensing, privacy, backup, credential, and security readiness gates pass.

## Hosted Multi-Tenant Founder PR Stack

Priority policy: security and authorization boundaries precede UI work. No endpoint may expose market or derived data before identity, credential encryption, user entitlement snapshots, and scoped analytical input enforcement exist. Every PR must use synthetic credentials and mocked provider responses in tests.

### PR84. Hosted Architecture Decision, Threat Model, And Active-Backlog Reset

Branch: `docs/hosted-multitenant-security-architecture`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/127.

Priority: P0 governance and security foundation.

Depends on: current `main`.

Scope: Record the PostgreSQL-first hosted architecture, Google-only authentication, encrypted persistent EODHD credentials, shared content-addressed market and statistics stores, per-user entitlements, immutable User Data Snapshots, and local-mode compatibility. Add trust boundaries, data-flow diagrams, attacker model, credential lifecycle, account deletion semantics, backup boundaries, provider-licensing assumptions, and explicit prohibited designs. Update `ARCHITECTURE.md`, `DECISIONS.md`, `RISKS.md`, `GOALS.md`, and documentation checks so future hosted work cannot silently revert to SQLite, session-only keys, global current pointers, or unrestricted lake reads.

Acceptance: Documentation tests verify that every hosted goal maps to an active PR; the architecture identifies Web, API, PostgreSQL, shared storage, external secret storage, Google, and EODHD trust boundaries; all secrets and personal data are classified; unresolved licensing blocks public-hosted readiness; and the local CLI path remains documented.

Security: The decision explicitly forbids secrets in Git, database plaintext, container images, CI artifacts, URLs, browser storage, client analytics, or logs. It requires an external key-encryption key and separates database backups from key recovery backups.

Determinism: Architecture and readiness status derive from versioned static decision records, not the deployment environment or live provider calls.

Idempotency: Re-running documentation validation against unchanged records produces no repository or runtime changes.

### PR85. PostgreSQL Application Catalog, Migrations, Roles, And Row-Level Security

Branch: `feat/postgres-multitenant-catalog`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/128.

Priority: P0 persistence and isolation foundation.

Depends on: PR84.

Scope: Add PostgreSQL dependencies, migration tooling, repository interfaces, and schema for users, external identities, sessions, provider credentials, projects, download runs, market objects, dataset snapshots, user grants, selections, analysis runs, artifacts, artifact inputs, and audit events. Create separate owner, migration, application, and read-only roles. Enable and force Row-Level Security on user-owned tables, pass the authenticated user id through transaction-local PostgreSQL settings, and prevent the application role from owning tables or bypassing RLS.

Acceptance: Migration tests start from an empty database, upgrade to head, exercise downgrade policy where supported, and prove uniqueness, foreign-key, lifecycle, and immutability constraints. Isolation tests prove User A cannot select, insert, update, or delete User B's rows even through repository mistakes. The schema records immutable artifact references without storing EODHD plaintext keys or large analytical tables in PostgreSQL.

Security: Database URLs and passwords are loaded from secret files outside the checkout. PostgreSQL is not published to the public host interface by default. The application role is non-superuser, has no `BYPASSRLS`, and cannot alter security policies.

Determinism: Migration order, constraint names, normalized identifiers, and serialized JSON fields are versioned and stable.

Idempotency: Re-applying migrations to the same schema is a no-op; retries do not duplicate identities, grants, projects, runs, or artifacts.

### PR86. Google-Only OpenID Connect And Server-Side Session Security

Branch: `feat/google-oidc-authentication`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/129.

Priority: P0 authenticated user boundary.

Depends on: PR85.

Scope: Add Google OpenID Connect using authorization code flow with PKCE, state, nonce, strict redirect URI validation, server-side token exchange, issuer/audience/signature/expiry checks, and Google's stable `sub` claim as the external identity key. Create short-lived, rotating server-side sessions with opaque HttpOnly, Secure, SameSite cookies; CSRF protection for state-changing requests; session revocation; login/logout/status routes; and optional domain allowlisting disabled by default.

Acceptance: Tests cover first login, repeat login after months, changed Google email with unchanged `sub`, invalid issuer/audience/signature/nonce/state, replayed callback, expired session, revoked session, CSRF failure, logout, and concurrent sessions. A new user begins with no market-data grants, selections, projects, or analysis access.

Security: Google client secrets, session signing or hashing keys, and callback configuration are runtime secrets or deployment configuration, never committed values. Tokens are never logged or returned after session establishment.

Determinism: One `(provider, subject)` identity resolves to one internal user regardless of mutable email or display-name fields.

Idempotency: Repeated valid login for the same Google `sub` updates permitted profile metadata without creating duplicate users or identities.

### PR87. Encrypted EODHD Credential Vault With External Key Management

Branch: `feat/encrypted-eodhd-credential-vault`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/130.

Priority: P0 credential confidentiality.

Depends on: PR86.

Scope: Persist one EODHD credential per user using envelope encryption: a random per-credential data-encryption key encrypts the provider key with authenticated encryption; the data key is wrapped by a versioned Founder key-encryption key supplied from a file or secret manager outside Git and PostgreSQL. Bind ciphertext to credential id, user id, provider, and schema version as associated data. Add set, replace, validate, status, revoke, delete, unwrap, and key-rotation services. Return only masked status metadata to clients.

Acceptance: Tests cover encrypt/decrypt round trips, wrong user or associated-data rejection, tampering, wrong key version, replacement, revocation, deletion, KEK rotation without provider-key re-entry, unavailable KEK fail-closed behavior, and redaction in structured logs and exceptions. Database dumps and shared storage contain no plaintext or reversible material without the external KEK.

Security: Plaintext provider keys exist only in bounded process memory during validation and provider calls. The KEK is never exposed to Web, PostgreSQL, CI, test reports, exception payloads, or ordinary application logs. Credential fingerprints use a separate keyed HMAC and are never returned in full.

Determinism: Ciphertext is intentionally nondeterministic; logical credential identity and status transitions are deterministic from user, provider, and versioned lifecycle rules.

Idempotency: Re-submitting the same valid key updates permitted metadata or reuses the logical credential without creating multiple active credentials.

### PR88. Shared Content-Addressed Market Observation Store

Branch: `feat/shared-market-observation-store`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/131.

Priority: P0 shared physical data foundation.

Depends on: PR85.

Scope: Add immutable normalized market observations and append-only Parquet segments for EODHD quotes, dividends, splits, metadata, and later supported datasets. Define a stable business key and payload hash per observation; retain corrected historical values as new revisions rather than overwriting prior observations. Add atomic temporary-write, validation, content-hash, fsync, rename, and PostgreSQL catalog publication. Store segment and manifest paths outside user-specific directories.

Acceptance: Tests cover identical responses, overlapping date ranges, appended dates, corrected rows with unchanged row count and end date, deleted provider rows, duplicate response rows, interrupted publication, corrupt segments, and concurrent writers. Identical normalized observations result in one physical observation and one catalog identity.

Security: Shared physical presence grants no user access. Storage paths and content hashes are not accepted directly as authorization credentials. Parquet data contains no user id, provider key, session token, or credential fingerprint.

Determinism: Observation ids derive from provider, dataset type, listing identity, business key, normalized payload, and schema version. Segment manifests are canonical and independent of worker completion order.

Idempotency: Re-ingesting identical observations produces no duplicate physical rows or catalog objects; retries publish at most one valid object.

### PR89. User Data Entitlements, Download Provenance, And Immutable Snapshots

Branch: `feat/user-data-entitlement-snapshots`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/132.

Priority: P0 authorization semantics.

Depends on: PR87 and PR88.

Scope: Model successful provider-backed download runs, exact returned observation sets, user grants, snapshot manifests, parent snapshots, revision selection, current project snapshot pointers, revocation, account deletion, and garbage-collection references. A grant may be created only after a successful EODHD response using the authenticated user's active credential. Build an entitlement resolver that creates an immutable User Data Snapshot containing the exact observations and revisions visible to that user at that point in time.

Acceptance: Tests prove a new user sees zero data; User A cannot see later observations downloaded by User B; overlapping physical data is shared without shared entitlement; User A gains the newer range only after their own successful refresh; historical corrections from another user's request remain invisible until an own refresh; old analyses retain old snapshots; and account deletion removes credentials and grants without deleting objects still referenced by other users.

Security: Every grant is linked to authenticated user, credential, provider request, normalized response, and immutable snapshot. No API or service may infer access from object existence, listing identity, date range, content hash, or another user's run.

Determinism: Snapshot hashes derive from canonically ordered observation ids and revision rules, not grant timestamps or filesystem order.

Idempotency: Replaying the same successful response for the same user resolves to the same logical snapshot and does not duplicate grants or manifests.

### PR90. User-Key-Backed EODHD Ingestion And Refresh Planner

Branch: `feat/user-scoped-eodhd-ingestion`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/133.

Priority: P0 usable BYOK download path.

Depends on: PR89.

Scope: Refactor EODHD workflows to accept an injected authenticated credential context rather than loading a global token. Add user-scoped full and gap-aware download planning, Free versus paid capability discovery, usage accounting, resumable runs, provider rate-limit handling, per-credential request serialization, shared-object deduplication, and atomic entitlement publication. Even when all requested observations already exist physically, execute the provider request with the current user's key before granting access.

Acceptance: Mocked integration tests cover Free and paid keys, invalid and revoked keys, quota exhaustion, retries, partial symbol failure, resume, overlapping user requests, existing shared objects, newer end dates, corrections, and concurrent identical requests. A successful run publishes a new User Data Snapshot; a partial or failed run cannot grant unreturned data.

Security: Provider URLs, headers, tokens, request diagnostics, and error bodies are centrally redacted. Decryption is performed immediately before the outbound request, and plaintext credentials are never passed to workers that do not perform provider access.

Determinism: Run plans derive from explicit requested scope, prior user snapshot, provider capability contract, and requested as-of date. Operational retry timing cannot affect data identities.

Idempotency: Resuming a run requests only incomplete work, deduplicates shared observations, and publishes no duplicate grants or snapshots.

### PR91. Scoped Analytical Input Boundary And Local Adapter Compatibility

Branch: `refactor/scoped-analytical-inputs`.

Git status: pushed. PR: https://github.com/SergejSchweizer/founder/pull/134.

Priority: P0 prevention of cross-user analytical leakage.

Depends on: PR90.

Scope: Introduce typed `ScopedMarketInputs`, `UserDataSnapshotRef`, `SelectionInputRef`, and snapshot-reader ports. Refactor hosted workflows so univariate, bivariate, multivariate, production portfolio, backtest, recommendation, and report paths receive already authorized immutable inputs and never call unrestricted `read_silver_quotes`, global current-selection files, or filesystem scans. Preserve current local CLI behavior through a `LocalLakeSnapshotReader`; add a hosted `EntitledSnapshotReader` backed by PostgreSQL and shared manifests.

Acceptance: Architecture tests fail when hosted services import unrestricted lake readers. Multi-user tests inject extra global observations and prove they cannot influence another user's returns, statistics, data-quality checks, optimization, backtests, or recommendations. Local CLI regression tests retain current commands and outputs.

Security: `user_id`, project ownership, snapshot ownership, and selection ownership are checked before resolving physical objects. The mathematical core receives no database credentials and cannot broaden the authorized scope.

Determinism: Scoped input identities derive from immutable snapshot, selection, dataset schema, and revision-policy ids.

Idempotency: Re-resolving unchanged authorized inputs returns the same immutable input references without copying market rows.

### PR92. Content-Addressed Univariate And Return Artifact Cache

Branch: `feat/content-addressed-univariate-cache`.

Git status: not started. PR: TBD.

Priority: P1 reusable analytical cache.

Depends on: PR91.

Scope: Replace hosted cache validity based only on listing, observation counts, and date bounds with exact input fingerprints. Create shared return and univariate artifact identities from listing, quote snapshot hash, dividend snapshot hash, date window, metric parameters, quality-policy version, and algorithm version. Store each artifact once and create user-visible analysis references only after verifying access to every input snapshot.

Acceptance: Tests cover identical inputs across users, different end dates, same row count with corrected historical values, changed dividend payload, changed confidence level, changed quality policy, corrupt artifact, and concurrent computation. Identical input hashes reuse one artifact; any material input change produces a distinct artifact.

Security: Cache discovery never grants access. Artifact reads require a user-owned run or authorized input proof; direct artifact ids and paths are insufficient.

Determinism: Artifact ids derive from canonical input and parameter hashes and produce stable row ordering.

Idempotency: Concurrent or repeated requests compute or publish one artifact and create separate user run references without rewriting valid shared content.

### PR93. Content-Addressed Bivariate Cache And Exact Alignment Identity

Branch: `feat/content-addressed-bivariate-cache`.

Git status: not started. PR: TBD.

Priority: P1 pair-statistics reuse without leakage.

Depends on: PR92.

Scope: Key pair artifacts by ordered input return-artifact ids, exact common-date alignment hash, metric parameters, minimum-observation policy, and algorithm version. Preserve unordered-pair canonicalization, same-ISIN rules, bucketed storage, sparse/top-k modes, and scale guards. Replace hosted cache checks based only on date range and observation count.

Acceptance: Tests cover identical pairs across users, reversed pair order, differing user date ranges, same common-date count with changed values, newly common dates, corrections, no-common-date cases, algorithm upgrades, bucket corruption, and concurrent requests. An artifact is reusable only when both input artifacts and exact alignment identity match.

Security: A user may reuse a pair artifact only when authorized for both underlying return inputs. Pair metadata must not reveal inaccessible listing histories through unauthenticated endpoints.

Determinism: Pair orientation, alignment rows, common-date hash, bucket assignment, and artifact id are independent of selection order and worker scheduling.

Idempotency: Repeated overlapping selections reuse existing pair artifacts and calculate only missing exact keys once.

### PR94. Content-Addressed Multivariate, Portfolio, Backtest, And Report Artifacts

Branch: `feat/content-addressed-portfolio-artifacts`.

Git status: not started. PR: TBD.

Priority: P1 portfolio-level reuse.

Depends on: PR93.

Scope: Build shared multivariate and downstream artifact identities from the sorted authorized listing-input artifact ids, selection definition and membership, return matrix, risk model, constraints, optimizer settings, costs, walk-forward windows, stress settings, recommendation template, and algorithm versions. Store physical artifacts globally while creating separate user-owned analysis runs and project references. Remove user id from physical cache keys and include it only in authorization and provenance records.

Acceptance: Two users with identical authorized snapshots and settings reuse one physical artifact while retaining separate runs. Different visible end dates, revisions, selections, constraints, costs, risk models, or algorithm versions produce distinct artifacts. Direct artifact-id access, cross-project run access, and stale project pointers are rejected.

Security: Every response resolves through an authenticated user-owned analysis run; no endpoint serves shared artifact paths directly. Artifact dependency closure is checked before reuse.

Determinism: Artifact ids and reports derive only from exact immutable inputs, explicit settings, and versioned algorithms.

Idempotency: Repeated identical analyses return the existing completed result or join the active computation without duplicate artifacts, portfolio rows, or reports.

### PR95. Docker Compose PostgreSQL, API, Web, And Shared Runtime Storage

Branch: `chore/docker-compose-postgres-hosted-runtime`.

Git status: not started. PR: TBD.

Priority: P1 reproducible hosted development environment.

Depends on: PR87 and PR91.

Scope: Add root Docker Compose configuration and Dockerfiles for PostgreSQL, FastAPI, and Next.js. Mount separate persistent PostgreSQL and shared-data volumes; keep PostgreSQL internal; expose only Web and development API ports; add health checks, startup ordering, migration execution, non-root containers, read-only filesystems where feasible, resource limits, and explicit development versus production overrides. Runtime secret source paths must be absolute host paths outside the repository and mounted as Docker secrets only into required services.

Acceptance: Compose validation and smoke tests prove database and shared data persist across restart, `docker compose down` does not erase named data without an explicit volume removal, Web cannot mount shared data or credential secrets, PostgreSQL is not externally published by default, and missing external secrets fail startup clearly.

Security: No real secret appears in Compose, `.env.example`, image layers, build arguments, command lines, logs, or CI artifacts. Production examples require TLS termination and protected host permissions.

Determinism: Service names, ports, volume contracts, image inputs, health checks, and configuration names are explicit and versioned.

Idempotency: Re-running Compose with unchanged source reuses persistent state and does not reset migrations, credentials, grants, snapshots, or artifacts.

### PR96. FastAPI User, Credential, Download, Dataset, Project, And Analysis API

Branch: `feat/hosted-fastapi-service`.

Git status: not started. PR: TBD.

Priority: P1 hosted application service.

Depends on: PR94 and PR95.

Scope: Add `apps/api` with authenticated routes for session status, credential set/status/delete, download plan/run/status, visible datasets, projects, selections, analyses, metrics, returns, weights, reports, and account deletion. Route all data access through repositories with RLS and entitlement services. Add request validation, bounded pagination, opaque public ids, structured errors, audit events, rate limits, and asynchronous-compatible run status while allowing initially small work to execute synchronously.

Acceptance: API tests cover authentication, CSRF, ownership, empty new-user state, credential lifecycle, successful and failed downloads, snapshot visibility, selection creation, analysis cache hit, cross-user ids, pagination, error redaction, account deletion, and restart persistence. No route accepts a storage path or shared artifact id as proof of access.

Security: Sensitive routes require recent authenticated sessions where appropriate. Responses never include provider ciphertext, nonce, wrapped data key, fingerprint, database ids, internal paths, or secret configuration.

Determinism: Public responses use stable opaque run and project identities plus deterministic analytical payload ordering.

Idempotency: Idempotency keys and logical request hashes prevent duplicate credential updates, download grants, projects, selections, or analysis submissions after retries.

### PR97. Google-Authenticated Web UI And User-Scoped Research Funnel

Branch: `feat/hosted-web-user-research-funnel`.

Git status: not started. PR: TBD.

Priority: P2 end-user workflow.

Depends on: PR96.

Scope: Add `apps/web` with Google login, dashboard, credential settings, data-download workflow, visible-data coverage, metadata filtering, univariate statistics/filtering, bivariate statistics, multivariate portfolio analysis, report views, and logout/account-deletion flows. The browser consumes API-produced data and performs no financial calculations or authorization decisions. The credential form accepts a new key but never redisplays the stored key.

Acceptance: UI tests cover first login with empty state, repeat login with persisted state, credential replacement and deletion, Free versus paid capability messaging, progress and partial failure, user-visible date coverage, no visibility of another user's newer data, statistics funnel navigation, cached analysis reuse, responsive layouts, accessibility, and API error handling.

Security: No EODHD key, Google token, session token, ciphertext, fingerprint, or sensitive response is stored in localStorage/sessionStorage, placed in URLs, sent to client analytics, or rendered into logs and error pages.

Determinism: UI state is derived from API contracts and stable route parameters; fixtures never call Google or EODHD.

Idempotency: Page refresh and navigation reload existing runs and snapshots without submitting new downloads or analyses.

### PR98. Public-Repository CI, Supply-Chain, Secret-Scanning, And Deployment Hardening

Branch: `chore/public-repo-security-hardening`.

Git status: not started. PR: TBD.

Priority: P0 before public deployment.

Depends on: PR95 and PR96.

Scope: Harden the public repository and CI: add secret scanners and custom EODHD patterns, pre-commit scanning, repository push-protection documentation, dependency and container scanning, SBOM generation, full-SHA pinning for GitHub Actions, least-privilege workflow permissions, fork-safe PR workflows without production secrets, protected deployment environments, dependency update policy, signed release guidance, and checks preventing secret-like files or runtime data from entering Git. Prohibit privileged `pull_request_target` execution of untrusted fork code.

Acceptance: Tests intentionally inject synthetic secret patterns and fail; fork PR simulation receives no protected secret; Actions are SHA-pinned; workflow permissions are explicit; container and dependency findings are reported; and `.gitignore` plus policy checks reject databases, Parquet runtime data, backups, `.env` files, and secret directories.

Security: GitHub Actions never receives user EODHD keys or the production KEK. NAS deployment uses trusted commits and runtime host secrets; any future cloud deployment uses short-lived OIDC credentials rather than long-lived deployment keys where supported.

Determinism: Security checks use pinned tool versions and committed policy configuration.

Idempotency: Re-running scans against unchanged source produces the same policy result apart from explicitly non-authoritative vulnerability-database timestamps.

### PR99. Licensing, Privacy, Retention, Backup, Restore, And Key-Rotation Gate

Branch: `docs/hosted-readiness-security-gate`.

Git status: not started. PR: TBD.

Priority: P0 public-hosting release gate.

Depends on: PR98.

Scope: Add machine-checkable hosted readiness records for EODHD storage, personal-license boundaries, shared physical deduplication, user-key-backed grants, derived-data display, redistribution, retention, account deletion, GDPR rights, audit retention, incident response, encrypted backups, restore drills, KEK recovery, KEK rotation, session-key rotation, database-role review, and no automatic broker execution. Public-hosted mode remains disabled unless every mandatory decision is approved.

Acceptance: The gate fails for missing or expired legal/security review, plaintext or co-located key backups, untested restore, unresolved provider display/redistribution rights, absent deletion procedure, unsupported country privacy requirements, or any endpoint capable of bypassing user entitlements. A documented local-only mode remains available while hosted readiness is blocked.

Security: Database/shared-store backups and KEK recovery material are encrypted and stored separately. Restore procedures fail closed when the correct KEK version is unavailable and never export decrypted provider keys.

Determinism: Readiness is computed from versioned decision and evidence records with explicit review dates and statuses.

Idempotency: Re-running the gate does not mutate production data, rotate keys, or alter readiness records.

### PR100. End-To-End Multi-User Isolation, Reproducibility, And Hosted Cutover

Branch: `feat/hosted-multitenant-cutover`.

Git status: not started. PR: TBD.

Priority: P0 final integration and release proof.

Depends on: PR97 and PR99.

Scope: Integrate Google identity, encrypted credentials, EODHD ingestion, shared observation storage, user snapshots, scoped selections, shared statistical caches, portfolio artifacts, API, Web, security gates, and recovery procedures. Add complete multi-user scenarios, migration tooling for existing local lake data as administrator-owned local artifacts without inventing user entitlements, operational runbooks, rollback, observability with redaction, and explicit feature flags for local-only versus hosted modes.

Acceptance: End-to-end tests create at least three users with overlapping and non-overlapping provider responses; prove exact date/revision visibility; prove physical market and statistics deduplication; prove uni/bi/multivariate calculations consume only each user's snapshot; prove identical authorized inputs reuse artifacts; reject every cross-user project, run, artifact, and snapshot attempt; survive restart; rotate KEK; restore encrypted backups; delete an account; and preserve local CLI behavior. The hosted feature flag cannot enable public mode unless PR99's gate is green.

Security: Add a final threat-model review, authorization matrix, penetration-test checklist, dependency review, secret scan, and incident-response verification. No production key is required or permitted in CI.

Determinism: Replaying identical user snapshots, selections, settings, and algorithm versions produces identical analytical artifact ids and values across restart and restore.

Idempotency: Retrying the complete workflow creates no duplicate users, credentials, observations, grants, snapshots, calculations, analyses, or reports.

## Series Completion Gate

Final branch: `feat/hosted-multitenant-cutover`.

Squash rule: Every PR title and final squash commit subject must use `type(optional-scope): subject`. Branches PR85 through PR100 are stacked on their declared dependencies and must be restacked after predecessor merges.

Required main merge gate: Ruff lint and format, Pyright strict, Pytest with at least 95% coverage, import-boundary checks, dataset-schema validation, migration tests, PostgreSQL RLS isolation tests, credential cryptography tests, secret-redaction tests, shared-store deduplication tests, snapshot entitlement tests, exact-hash cache tests, API/Web contract tests, fork-safe CI policy checks, backup/restore tests, and hosted-readiness validation.

The series is incomplete while any of these conditions remains true:

- a provider key or KEK can enter Git, PostgreSQL plaintext, images, logs, browser storage, URLs, or CI;
- shared physical data existence can create access without a successful user-key-backed request;
- a hosted analytical workflow can read outside the authenticated user's immutable snapshot;
- a statistics or portfolio cache can be reused without exact input-hash equality and authorization to its dependency closure;
- direct artifact paths or ids can bypass a user-owned analysis run;
- a new user can see pre-existing provider data;
- one user's refresh can silently expand another user's visible date range or revision set;
- public-hosted mode can start while licensing, privacy, credential, backup, or security gates are unresolved.

## Update Rules

Update this file whenever:

- a PR is opened, pushed, merged, blocked, split, or superseded;
- a security or licensing decision changes the dependency order;
- a new secret, external provider, user-data category, dataset, or authorization path is introduced;
- an implementation discovers that an acceptance criterion cannot be met safely;
- a production incident, restore drill, or threat-model review creates follow-up work.
