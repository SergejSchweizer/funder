# Founder UI Local Docker Execution Contract

Last reviewed: 2026-07-19

## Status And Scope

This document is a mandatory execution amendment to the Founder Research Funnel UI stack PR101 through PR108 in `BACKLOG.md`.

All UI implementation, integration, visual review, and acceptance testing must run against the repository's local Docker Compose topology. The canonical development host is the UGREEN NAS checkout operated by the trusted `vcs` user, which is a member of the Docker group. Host-installed Node.js, Python, PostgreSQL, or ad hoc development servers may be used for isolated debugging only; they are not accepted as proof that a UI PR works.

## Canonical Command Surface

Every UI PR must document and validate the equivalent of:

```bash
docker compose --env-file .env.local config --quiet
docker compose --env-file .env.local up --build -d
docker compose --env-file .env.local ps
docker compose --env-file .env.local exec api <api-test-command>
docker compose --env-file .env.local exec web <web-test-command>
docker compose --env-file .env.local logs --no-color --tail=200 api web postgres
```

The exact test commands may evolve with the Web implementation, but they must execute inside the containers or from a dedicated Compose test service attached to the same networks and dependencies.

## Required Development Properties

1. The browser connects to the Compose-managed Web service, not a host process.
2. The Web service connects to the Compose-managed API service by service name.
3. The API connects to the Compose-managed PostgreSQL service and shared-data volume through the declared runtime contract.
4. Development secrets are mounted from absolute external host paths through Docker secrets and are never copied into the repository or images.
5. Source-code bind mounts, watch mode, and hot reload may be added in a development override, but the base production-oriented images must remain buildable without them.
6. Named PostgreSQL and shared-data volumes must survive ordinary container recreation.
7. Tests must not depend on another developer's host-level Node modules, Python virtual environment, localhost database, or globally installed package versions.
8. The `vcs` user may operate Docker because Docker-group access is intentionally trusted and treated as root-equivalent access on the NAS.

## PR101-PR108 Amendment

### PR101 — Design System And Application Shell

Build and serve the real Web application from the Compose `web` service. Component tests, screenshot tests, responsive shell tests, and health checks run in the Web image or a Compose test target. Acceptance requires reaching the shell through the published Compose Web port after a clean image build.

### PR102 — Dashboard, Onboarding, And Funnel State

Exercise onboarding and persisted project-state scenarios through the Compose Web and API services. Restart tests must recreate the containers while retaining the named volumes and verify that the browser resumes the same user-owned state.

### PR103 — Data Coverage And Metadata Universe Builder

Run server-backed filtering, pagination, refresh progress, and large-fixture tests against the Compose API and PostgreSQL services. Browser tests must not replace API behavior with a second client-side implementation.

### PR104 — Univariate Research And Metric Filter

Generate analytical fixtures through the API/container boundary, then verify tables, charts, exclusions, and stale-state behavior in the Compose Web service. Host-side precomputed JSON is not sufficient acceptance evidence.

### PR105 — Diversification And Pair Inspector

Validate sparse/top-k pair APIs, cluster views, and large pair sets inside the Compose topology. Test data must pass through the same service and authorization boundaries used by the browser.

### PR106 — Portfolio Model And Constraint Workbench

Execute portfolio requests in the API container against scoped inputs and persist user-owned runs through the configured catalog adapter. Browser code may render results but may not calculate or silently repair portfolio weights.

### PR107 — Validation, Reports, And Trade Preparation

Create reports and Flatex-oriented exports through authorized API routes in the Compose runtime. Download tests must verify content, ownership, redaction, persistence, and the absence of automatic broker execution.

### PR108 — Production UI Cutover

Provide one clean-host command path starting from the repository checkout and external synthetic secret files. The full browser funnel, accessibility tests, visual regression tests, performance fixtures, restart recovery, multi-user isolation, and account deletion must pass against the Compose stack before the Node placeholder or other transitional UI is removed.

## Required Test Layers

```text
source change
    |
    v
container image build
    |
    v
Compose config validation
    |
    v
unit/component tests in container
    |
    v
API + PostgreSQL integration in Compose
    |
    v
browser E2E against Compose Web port
    |
    v
visual/accessibility/performance evidence
    |
    v
container restart and persistence proof
```

A UI PR is incomplete if it passes only mocked component tests while failing against the running Compose services.

## Security

- Never mount `/var/run/docker.sock` into Founder application or test containers.
- Never run the Founder Web or API container as a privileged container.
- Docker-group membership is limited to trusted NAS administrators such as `vcs`.
- Browser traces, screenshots, videos, reports, logs, and test artifacts must be scanned for provider keys, session tokens, ciphertext, fingerprints, internal paths, and cross-user data.
- Synthetic Google and EODHD credentials are used in automated tests; production credentials are not required or permitted.

## Determinism

Images, package lockfiles, browser versions, locale, time zone, viewport sizes, synthetic fixtures, and test seeds must be pinned or explicitly recorded. Identical source, images, fixtures, and settings must produce the same route state, screenshots within approved tolerances, analytical references, and test outcome.

## Idempotency

Repeated `docker compose up --build`, page reloads, browser retries, container recreation, and E2E reruns against unchanged inputs must not create duplicate users, credentials, downloads, snapshots, selections, analyses, reports, or exports. Ordinary `docker compose down` must not delete named data volumes; destructive volume removal is always explicit.
