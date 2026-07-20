from __future__ import annotations

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = REPOSITORY_ROOT / "apps" / "web" / "server.js"
WEB_PACKAGE = REPOSITORY_ROOT / "apps" / "web" / "package.json"
WEB_DOCKERFILE = REPOSITORY_ROOT / "apps" / "web" / "Dockerfile"


def _web_source() -> str:
    return WEB_SERVER.read_text(encoding="utf-8")


def test_web_shell_exposes_user_research_funnel_surfaces() -> None:
    source = _web_source()

    for expected in (
        "Google Login",
        "Google Auth",
        "EODHD Key",
        "Fetch all ISINs",
        "Projects",
        "Data",
        "Downloads",
        "Metadata",
        "Metadata Filter",
        "Univariate Statistics",
        "Univariate Filter",
        "Diversification",
        "Bivariate Statistics",
        "Multivariate Statistics",
        "Portfolio",
        "Portfolio Analysis",
        "Validation",
        "Report",
        "Delete Account Data",
    ):
        assert expected in source

    assert "Project Snapshot" in source
    assert "No project selected" in source
    assert "data-project-selector" in source
    assert "data-project-tree-items" in source
    assert "data-project-workspace hidden" in source
    assert "Project Definition" in source
    assert "Create New Project" in source
    assert 'data-form="project-definition"' in source
    assert 'data-form="eodhd-fetch"' in source
    assert "Enter an EODHD key to enable project setup." in source


def test_dashboard_shell_is_gated_until_authenticated_session() -> None:
    source = _web_source()

    assert "data-auth-gate" in source
    assert 'id="authenticated-root"' in source
    assert "renderAppShell(apiUrl, initialSession = null)" in source
    assert "${initialShell}" in source
    assert "const initialSession =" in source
    assert "initialSession && initialSession.authenticated === true" in source
    assert "brandMarkup(session = null)" in source
    assert 'class="brand-user" data-auth-user' in source
    assert "text-transform: lowercase;" in source
    assert "data-authenticated-template" in source
    assert "initializeAuthGate()" in source
    assert "mountAuthenticatedShell(session)" in source
    assert "bindAuthenticatedHandlers()" in source
    assert "[hidden] { display: none !important; }" in source
    assert 'meta[name="founder-csrf-token"]' in source
    assert "session.csrf_token" in source
    assert "Google login is required before the dashboard is shown." in source
    assert source.index("data-auth-gate") < source.index("data-authenticated-template")


def test_web_shell_defines_versioned_design_system_and_route_skeletons() -> None:
    source = _web_source()

    assert 'data-design-system-version="founder-web-shell-v1"' in source
    for token in (
        "typography",
        "spacing",
        "color",
        "radius",
        "--page-title",
        "--section-title",
        "--canvas",
        "--surface",
        "--focus",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert token in source

    assert 'id: "projects"' in source
    assert 'id: "dashboard"' not in source
    assert 'class="nav-dot"' not in source
    assert "projectNavigationMarkup()" in source
    assert 'aria-label="Project routes"' in source

    assert 'data-route-skeleton="${route.id}"' in source


def test_web_shell_uses_google_style_material_color_tokens() -> None:
    source = _web_source()

    for token in (
        "#1a73e8",
        "#202124",
        "#5f6368",
        "#dadce0",
        "#188038",
        "#f9ab00",
        "#d93025",
        "rgba(60, 64, 67",
        "#e8f0fe",
    ):
        assert token in source


def test_web_shell_models_complete_funnel_order_and_status_states() -> None:
    source = _web_source()

    positions = [
        source.index(f'id: "{step}"')
        for step in (
            "data",
            "metadata",
            "univariate",
            "filter",
            "diversification",
            "portfolio",
            "validation",
            "report",
        )
    ]
    assert positions == sorted(positions)

    for state in ("not-started", "ready", "running", "complete", "warning", "failed", "stale"):
        assert f'status: "{state}"' in source or f"funnel-step--{state}" in source


def test_web_shell_keeps_secret_inputs_write_only_and_uses_google_entrypoint() -> None:
    source = _web_source()

    assert 'action="/auth/google/start" method="get"' in source
    assert 'data-form="google-login"' in source
    assert 'type="submit" aria-label="Start Google login"' in source
    assert 'name="provider_key" type="password"' in source
    assert 'autocomplete="new-password"' in source
    assert 'data-action="fetch-all-isins"' in source
    assert "masked_label" not in source
    assert "ciphertext" not in source
    assert "fingerprint" not in source


def test_web_shell_avoids_browser_secret_persistence_and_url_token_leaks() -> None:
    source = _web_source()

    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source
    assert "access_token" not in source
    assert "api_token" not in source


def test_web_shell_consumes_api_contracts_with_csrf_and_idempotency_helpers() -> None:
    source = _web_source()

    assert 'const apiBaseUrl = "/api";' in source
    assert "fetch(apiBaseUrl + path" in source
    assert 'credentials: "include"' in source
    assert '"X-Founder-CSRF"' in source
    assert "idempotencyKey(prefix)" in source
    assert "randomUUID" in source
    for route in (
        "/session",
        "/credentials/eodhd",
        "/datasets",
        "/downloads/plan",
        "/downloads/run",
        "/projects",
        "/selections",
        "/metadata-filter/fetch-all-isins",
        "/metadata-filter/options",
        "/metadata-filter/projects",
        "/analyses",
        "/account",
    ):
        assert route in source


def test_web_shell_uses_project_scoped_navigation_and_empty_snapshot_state() -> None:
    source = _web_source()

    for expected in (
        "let projectState =",
        "metadataReady: false",
        "setProjectGateEnabled(false)",
        "setProjectGateEnabled(true)",
        "fetchAllIsinsForProjects",
        "apiRoutes.metadataFilterFetchAllIsins",
        'Fetched " + result.row_count + " ISIN listings.',
        "refreshProjects()",
        "refreshMetadataFilterOptions()",
        "normalizeProjectItems(payload)",
        "renderProjectOptions()",
        "renderProjectNavigation()",
        "selectProject(projectId)",
        "projectDefinitionPayload(form)",
        "apiRoutes.metadataFilterProjects",
        "data-metadata-option",
        'name="exchange"',
        'name="name" placeholder="UCITS ETF"',
        'name="instrument_type"',
        'name="country"',
        'name="currency"',
        "selectedProject()",
        "clientEscapeHtml(projectLabel(project))",
        'document.querySelector("[data-project-selector]")',
        'document.querySelector("[data-project-empty-state]")',
        'document.querySelector("[data-project-workspace]")',
        'document.querySelector("[data-snapshot-indicator]")',
        'document.querySelector("[data-project-navigation]")',
        "workspace.hidden = !project",
        "emptyState.hidden = Boolean(project)",
    ):
        assert expected in source

    assert (
        "bindAuthenticatedHandlers();\n  setProjectGateEnabled(false);\n  updateFetchButtonState();"
    ) in source
    assert "void refreshProjects()" not in source
    assert 'writeJson("[data-analysis-output]", { session })' not in source


def test_web_server_proxies_api_requests_same_origin_to_internal_api() -> None:
    source = _web_source()

    assert 'request.url.startsWith("/api/")' in source
    assert "proxyApiRequest(request, response)" in source
    assert 'request.url.startsWith("/auth/")' in source
    assert "proxyAuthRequest(request, response)" in source
    assert "proxyRequestToTarget" in source
    assert "clientRequest.url.replace" in source
    assert "apiBaseUrl)" in source
    assert 'process.env.FOUNDER_API_BASE_URL || "http://api:8000"' in source


def test_web_server_handles_local_google_session_same_origin_before_auth_proxy() -> None:
    source = _web_source()

    assert 'process.env.FOUNDER_AUTH_MODE || "google"' in source
    assert 'authMode === "local-dev"' in source
    assert 'authMode === "auto"' not in source
    assert 'requestUrl.pathname === "/auth/google/start"' in source
    assert 'requestUrl.pathname === "/auth/logout"' in source
    assert 'requestUrl.pathname === "/" && session === null' in source
    assert "startLocalGoogleLogin(response)" in source
    assert "logoutLocalGoogleSession(response)" in source
    assert "function cookieHeader(name, value, options = {})" in source
    assert "function parseCookies(cookieHeaderValue)" in source
    assert "function sessionFromRequest(request)" in source
    assert "const session = sessionFromRequest(request)" in source
    assert "renderAppShell(apiBaseUrl, session)" in source
    assert "founder_session_user" in source
    assert "founder_csrf" in source
    assert "FOUNDER_LOCAL_DEV_GOOGLE_EMAIL" in source
    assert "local-google-dev-user@example.test" in source
    assert 'cookieHeader(providerCookieName, "local-dev-google"' in source
    assert source.index('requestUrl.pathname === "/auth/google/start"') < source.index(
        'request.url.startsWith("/auth/")'
    )


def test_web_server_implements_real_google_oidc_runtime_flow() -> None:
    source = _web_source()

    for expected in (
        "FOUNDER_AUTH_MODE",
        "FOUNDER_GOOGLE_CLIENT_ID",
        "FOUNDER_GOOGLE_REDIRECT_URI",
        "FOUNDER_GOOGLE_CLIENT_SECRET_FILE",
        "FOUNDER_GOOGLE_ALLOWED_DOMAIN",
        "createGoogleAuthRequest()",
        "applyGooglePrivateIpDeviceParams(url)",
        'url.searchParams.set("device_id"',
        'url.searchParams.set("device_name", "Founder Research Local")',
        'url.searchParams.set("prompt", "select_account")',
        'url.searchParams.set("code_challenge_method", "S256")',
        'requestUrl.pathname === "/auth/google/callback"',
        "exchangeGoogleCode(code, pending.codeVerifier)",
        "verifyGoogleIdToken(idToken, pending.nonce)",
        'crypto.createPublicKey({ key: jwk, format: "jwk" })',
        "stableGoogleUserId(claims.sub)",
        'auth_provider: cookies[providerCookieName] || "unknown"',
    ):
        assert expected in source


def test_web_shell_binds_authenticated_handlers_once_for_client_or_server_render() -> None:
    source = _web_source()

    assert "let authenticatedHandlersBound = false;" in source
    assert "if (authenticatedHandlersBound) return;" in source
    assert "authenticatedHandlersBound = true;" in source
    assert "if (root.childElementCount === 0)" in source


def test_web_package_remains_local_container_runnable_without_external_calls() -> None:
    package = json.loads(WEB_PACKAGE.read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["scripts"]["start"] == "node server.js"
    assert package["dependencies"] == {}

    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY apps/web/package.json ./" in dockerfile
    assert "COPY apps/web/server.js ./" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
