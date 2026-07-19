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
        "Dashboard",
        "Projects",
        "Data",
        "Credentials",
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
        "Settings",
        "Delete Account Data",
    ):
        assert expected in source


def test_dashboard_shell_is_gated_until_authenticated_session() -> None:
    source = _web_source()

    assert "data-auth-gate" in source
    assert 'id="authenticated-root"' in source
    assert "data-authenticated-template" in source
    assert "initializeAuthGate()" in source
    assert "mountAuthenticatedShell(session)" in source
    assert "bindAuthenticatedHandlers()" in source
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

    for route in (
        "dashboard",
        "projects",
        "data",
        "metadata",
        "univariate",
        "filter",
        "diversification",
        "portfolio",
        "validation",
        "report",
        "settings",
    ):
        assert f'id: "{route}"' in source

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

    assert 'href="/auth/google/start"' in source
    assert 'name="provider_key" type="password"' in source
    assert 'autocomplete="new-password"' in source
    assert "masked_label" not in source
    assert "ciphertext" not in source
    assert "fingerprint" not in source


def test_web_shell_avoids_browser_secret_persistence_and_url_token_leaks() -> None:
    source = _web_source()

    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source
    assert "access_token" not in source
    assert "id_token" not in source
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
        "/analyses",
        "/account",
    ):
        assert route in source


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


def test_web_package_remains_local_container_runnable_without_external_calls() -> None:
    package = json.loads(WEB_PACKAGE.read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["scripts"]["start"] == "node server.js"
    assert package["dependencies"] == {}

    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY apps/web/package.json ./" in dockerfile
    assert "COPY apps/web/server.js ./" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
