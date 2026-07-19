from __future__ import annotations

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = REPOSITORY_ROOT / "apps" / "web" / "server.js"
WEB_PACKAGE = REPOSITORY_ROOT / "apps" / "web" / "package.json"


def _web_source() -> str:
    return WEB_SERVER.read_text(encoding="utf-8")


def test_web_shell_exposes_user_research_funnel_surfaces() -> None:
    source = _web_source()

    for expected in (
        "Google Login",
        "Dashboard",
        "Credentials",
        "Downloads",
        "Metadata Filter",
        "Univariate Statistics",
        "Univariate Filter",
        "Bivariate Statistics",
        "Multivariate Statistics",
        "Portfolio Analysis",
        "Delete Account Data",
    ):
        assert expected in source


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


def test_web_package_remains_local_container_runnable_without_external_calls() -> None:
    package = json.loads(WEB_PACKAGE.read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["scripts"]["start"] == "node server.js"
    assert package["dependencies"] == {}
