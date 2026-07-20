from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from founder.hosted_runtime import health

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


ComposeMapping = dict[str, Any]


def _compose() -> ComposeMapping:
    return cast(
        ComposeMapping,
        yaml.safe_load((REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")),
    )


def test_compose_defines_persistent_internal_postgres_and_shared_data() -> None:
    compose = _compose()
    services = cast(ComposeMapping, compose["services"])
    volumes = cast(ComposeMapping, compose["volumes"])
    postgres = cast(ComposeMapping, services["postgres"])
    api = cast(ComposeMapping, services["api"])

    assert "founder-postgres-data" in volumes
    assert "founder-shared-data" in volumes
    assert postgres["networks"] == ["founder-internal"]
    assert "ports" not in postgres
    assert "5432" in postgres["expose"]
    assert "founder-postgres-data:/var/lib/postgresql/data" in postgres["volumes"]
    assert "founder-shared-data:/srv/founder/shared-data" in api["volumes"]
    assert "./lake:/srv/founder/lake:ro" in api["volumes"]
    assert api["environment"]["FOUNDER_LAKE_ROOT"] == "/srv/founder/lake"
    assert api["group_add"] == ["${FOUNDER_LAKE_GROUP_ID:-10}"]


def test_compose_exposes_only_api_and_web_development_ports() -> None:
    services = cast(ComposeMapping, _compose()["services"])

    assert cast(ComposeMapping, services["api"])["ports"] == [
        "0.0.0.0:${FOUNDER_API_PORT:-8000}:8000"
    ]
    assert cast(ComposeMapping, services["web"])["ports"] == [
        "0.0.0.0:${FOUNDER_WEB_PORT:-3000}:3000"
    ]
    assert "ports" not in cast(ComposeMapping, services["postgres"])


def test_web_has_no_shared_data_mount_and_only_google_auth_secret() -> None:
    services = cast(ComposeMapping, _compose()["services"])
    web = cast(ComposeMapping, services["web"])

    assert "volumes" not in web
    assert web["secrets"] == ["google_client_secret"]
    assert "FOUNDER_API_BASE_URL" in web["environment"]
    assert web["environment"]["FOUNDER_AUTH_MODE"] == "${FOUNDER_AUTH_MODE:-google}"
    assert (
        web["environment"]["FOUNDER_GOOGLE_ALLOWED_DOMAIN"] == "${FOUNDER_GOOGLE_ALLOWED_DOMAIN:-}"
    )
    assert (
        web["environment"]["FOUNDER_LOCAL_DEV_GOOGLE_EMAIL"]
        == "${FOUNDER_LOCAL_DEV_GOOGLE_EMAIL:-local-google-dev-user@example.test}"
    )
    assert "FOUNDER_GOOGLE_CLIENT_SECRET_FILE" in web["environment"]


def test_web_compose_develop_watch_rebuilds_local_ui_changes() -> None:
    services = cast(ComposeMapping, _compose()["services"])
    web = cast(ComposeMapping, services["web"])
    develop = cast(ComposeMapping, web["develop"])
    watch = cast(list[ComposeMapping], develop["watch"])

    assert watch == [
        {"action": "rebuild", "path": "./apps/web"},
        {"action": "rebuild", "path": "./apps/web/Dockerfile"},
        {"action": "rebuild", "path": "./compose.yaml"},
    ]


def test_runtime_secrets_are_external_paths_and_not_build_arguments() -> None:
    compose = _compose()
    secrets = cast(ComposeMapping, compose["secrets"])
    rendered = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert cast(ComposeMapping, secrets["postgres_password"])["file"].startswith(
        "${FOUNDER_POSTGRES_PASSWORD_FILE:?"
    )
    assert cast(ComposeMapping, secrets["session_secret"])["file"].startswith(
        "${FOUNDER_SESSION_SECRET_FILE:?"
    )
    assert cast(ComposeMapping, secrets["eodhd_kek"])["file"].startswith(
        "${FOUNDER_EODHD_KEK_FILE:?"
    )
    assert cast(ComposeMapping, secrets["google_client_secret"])["file"].startswith(
        "${FOUNDER_GOOGLE_CLIENT_SECRET_FILE:?"
    )
    assert "api_token" not in rendered.lower()
    assert "build:" in rendered
    assert "args:" not in rendered


def test_compose_uses_health_checks_startup_order_and_hardening() -> None:
    services = cast(ComposeMapping, _compose()["services"])

    for service_name in ("postgres", "api", "web"):
        service = cast(ComposeMapping, services[service_name])
        assert "healthcheck" in service
        assert service["read_only"] is True
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "deploy" in service

    for service_name in ("api", "web"):
        service = cast(ComposeMapping, services[service_name])
        assert service["cap_drop"] == ["ALL"]

    api_depends = cast(ComposeMapping, cast(ComposeMapping, services["api"])["depends_on"])
    web_depends = cast(ComposeMapping, cast(ComposeMapping, services["web"])["depends_on"])
    assert cast(ComposeMapping, api_depends["postgres"])["condition"] == "service_healthy"
    assert cast(ComposeMapping, web_depends["api"])["condition"] == "service_healthy"


def test_hosted_runtime_health_entrypoint(capsys: Any) -> None:
    assert health() == 0

    assert '"status": "ok"' in capsys.readouterr().out
