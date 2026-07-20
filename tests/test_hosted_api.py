from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from founder.hosted_api import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, HostedApiState, create_app
from founder.paths import LakePaths
from founder.table_io import read_json, read_rows


def _client(state: HostedApiState | None = None) -> TestClient:
    return TestClient(create_app(state or HostedApiState()))


def _headers(
    user_id: str = "user-a", *, csrf: bool = True, idempotency: str | None = None
) -> dict[str, str]:
    headers: dict[str, str] = {"X-Founder-User": user_id}
    if csrf:
        headers["X-Founder-CSRF"] = "valid-csrf"
    if idempotency is not None:
        headers["Idempotency-Key"] = idempotency
    return headers


def _json(response: Any) -> dict[str, Any]:
    payload = response.json()
    assert isinstance(payload, dict)
    return cast("dict[str, Any]", payload)


def test_session_requires_authentication() -> None:
    client = _client()

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/session").status_code == 401
    assert _json(client.get("/session", headers=_headers(csrf=False))) == {
        "authenticated": True,
        "csrf_token": "",
        "user_id": "user-a",
    }


def test_google_login_route_creates_cookie_session_for_local_web_runtime() -> None:
    client = _client()

    response = client.get("/auth/google/start", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert SESSION_COOKIE_NAME in response.cookies
    assert CSRF_COOKIE_NAME in response.cookies
    assert _json(client.get("/session")) == {
        "authenticated": True,
        "csrf_token": "valid-csrf",
        "user_id": "local-google-dev-user",
    }


def test_logout_clears_cookie_session() -> None:
    client = _client()
    client.get("/auth/google/start", follow_redirects=False)

    response = client.get("/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert client.get("/session").status_code == 401


def test_state_changing_routes_require_csrf() -> None:
    client = _client()

    response = client.post(
        "/projects",
        headers=_headers(csrf=False),
        json={"name": "Core"},
    )

    assert response.status_code == 403
    assert _json(response)["detail"]["code"] == "csrf_required"


def test_credential_lifecycle_redacts_sensitive_material() -> None:
    client = _client()

    created = _json(
        client.post(
            "/credentials/eodhd",
            headers=_headers(idempotency="credential-1"),
            json={"provider_key": "secret-provider-token"},
        )
    )
    repeated = _json(
        client.post(
            "/credentials/eodhd",
            headers=_headers(idempotency="credential-1"),
            json={"provider_key": "changed-token"},
        )
    )
    deleted = _json(client.delete("/credentials/eodhd", headers=_headers()))
    rendered = str(created) + str(repeated) + str(deleted)

    assert created["status"] == "active"
    assert repeated["credential_id"] == created["credential_id"]
    assert deleted["status"] == "deleted"
    assert "secret-provider-token" not in rendered
    assert "changed-token" not in rendered
    assert "fingerprint" not in rendered
    assert "ciphertext" not in rendered
    assert "nonce" not in rendered


def test_downloads_publish_visible_user_datasets_and_are_idempotent() -> None:
    client = _client()

    plan = _json(
        client.post(
            "/downloads/plan",
            headers=_headers(),
            json={"symbols": ["AAA.XETRA", "BBB.XETRA"]},
        )
    )
    run = _json(
        client.post(
            "/downloads/run",
            headers=_headers(idempotency="download-1"),
            json={"symbols": ["AAA.XETRA", "BBB.XETRA"]},
        )
    )
    repeated = _json(
        client.post(
            "/downloads/run",
            headers=_headers(idempotency="download-1"),
            json={"symbols": ["CCC.XETRA"]},
        )
    )
    datasets = _json(client.get("/datasets", headers=_headers(csrf=False)))
    other_datasets = _json(client.get("/datasets", headers=_headers("user-b", csrf=False)))

    assert plan["status"] == "planned"
    assert run == repeated
    assert run["status"] == "succeeded"
    assert run["observation_count"] == 2
    assert len(datasets["items"]) == 2
    assert other_datasets["items"] == []


def test_metadata_filter_options_and_project_creation_use_all_isins_reference() -> None:
    state = HostedApiState(
        all_isins_rows=(
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "Example UCITS ETF",
                "instrument_type": "ETF",
                "country": "IE",
                "currency": "EUR",
                "source_exchange": "XETRA",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "isin": "US1",
                "exchange": "NYSE",
                "code": "BBB",
                "name": "Example Stock",
                "instrument_type": "Common Stock",
                "country": "US",
                "currency": "USD",
                "source_exchange": "NYSE",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            },
        )
    )
    client = _client(state)

    options = _json(client.get("/metadata-filter/options", headers=_headers(csrf=False)))
    created = _json(
        client.post(
            "/metadata-filter/projects",
            headers=_headers(idempotency="metadata-project-1"),
            json={
                "exchange": "XETRA",
                "name": "UCITS ETF",
                "instrument_type": "ETF",
                "country": "IE",
                "currency": "EUR",
            },
        )
    )
    repeated = _json(
        client.post(
            "/metadata-filter/projects",
            headers=_headers(idempotency="metadata-project-1"),
            json={
                "exchange": "XETRA",
                "name": "UCITS ETF",
                "instrument_type": "ETF",
                "country": "IE",
                "currency": "EUR",
            },
        )
    )

    assert options == {
        "country": ["IE", "US"],
        "currency": ["EUR", "USD"],
        "exchange": ["NYSE", "XETRA"],
        "instrument_type": ["Common Stock", "ETF"],
    }
    assert created == repeated
    assert created["project"]["name"] == "xetra_ucits_etf_etf_ie_eur"
    assert "name_" not in created["project"]["name"]
    assert created["selection"]["member_ids"] == ["IE1:XETRA:AAA"]
    assert created["selected_count"] == 1
    assert _json(client.get("/projects", headers=_headers(csrf=False)))["items"] == [
        {
            **created["project"],
            "data_loaded": False,
            "selected_count": 1,
            "selection_id": created["selection"]["selection_id"],
        }
    ]
    assert _json(client.get("/projects", headers=_headers("user-b", csrf=False)))["items"] == []
    assert (
        client.get(
            f"/selections/{created['selection']['selection_id']}",
            headers=_headers("user-b", csrf=False),
        ).status_code
        == 404
    )


def test_load_selected_isins_runs_fetch_all_quotes_for_metadata_selection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    lake_root = tmp_path / "lake"
    monkeypatch.setenv("FOUNDER_LAKE_ROOT", str(lake_root))
    calls: list[dict[str, Any]] = []
    state = HostedApiState(
        all_isins_rows=(
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "Example UCITS ETF",
                "instrument_type": "ETF",
                "country": "IE",
                "currency": "EUR",
                "source_exchange": "XETRA",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            },
        )
    )

    def fake_fetch_all_quotes_workflow(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "coverage_rows": 1,
            "raw_dataset_errors": 0,
            "raw_dataset_successes": 2,
            "quote_errors": 0,
            "quote_successes": 1,
            "run_id": kwargs["run_id"],
            "selection_id": kwargs["selection_id"],
            "selected_listing_count": 1,
            "silver_quote_rows": 42,
        }

    monkeypatch.setattr(
        "founder.hosted_api.run_fetch_all_quotes_workflow",
        fake_fetch_all_quotes_workflow,
    )
    client = _client(state)
    client.post(
        "/credentials/eodhd",
        headers=_headers(idempotency="credential-load-selected-isins"),
        json={"provider_key": "secret-provider-token"},
    )
    created = _json(
        client.post(
            "/metadata-filter/projects",
            headers=_headers(idempotency="metadata-project-load-selected-isins"),
            json={
                "exchange": "XETRA",
                "name": "UCITS ETF",
                "instrument_type": "ETF",
                "country": "IE",
                "currency": "EUR",
            },
        )
    )
    selection_id = created["selection"]["selection_id"]

    loaded_data = _json(
        client.post(
            "/data/load-selected-isins",
            headers=_headers(idempotency="load-selected-isins-1"),
            json={"project_id": created["project"]["project_id"]},
        )
    )
    loaded_data_again = _json(
        client.post(
            "/data/load-selected-isins",
            headers=_headers(idempotency="load-selected-isins-1"),
            json={"project_id": created["project"]["project_id"]},
        )
    )
    paths = LakePaths(root=lake_root)
    persisted_selection_rows = read_rows(paths.metadata_filter_isins(selection_id))
    current_selection = read_json(paths.current_metadata_filter_selection())
    reloaded_project = _json(client.get("/projects", headers=_headers(csrf=False)))["items"][0]

    assert len(calls) == 1
    assert calls[0]["root"] == lake_root
    assert calls[0]["selection_id"] == selection_id
    assert calls[0]["eodhd_config"].api_token == "secret-provider-token"
    assert persisted_selection_rows[0]["isin"] == "IE1"
    assert persisted_selection_rows[0]["exchange"] == "XETRA"
    assert persisted_selection_rows[0]["code"] == "AAA"
    assert current_selection["selection_id"] == selection_id
    assert loaded_data == loaded_data_again
    assert loaded_data["kind"] == "load-data"
    assert loaded_data["observation_count"] == 1
    assert loaded_data["quote_successes"] == 1
    assert loaded_data["raw_dataset_successes"] == 2
    assert loaded_data["selected_listing_count"] == 1
    assert loaded_data["selected_count"] == 1
    assert loaded_data["silver_quote_rows"] == 42
    assert loaded_data["status"] == "succeeded"
    assert reloaded_project["data_loaded"] is True


def test_fetch_all_isins_for_metadata_filter_requires_eodhd_key() -> None:
    state = HostedApiState(
        all_isins_rows=(
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "name": "Example UCITS ETF",
                "instrument_type": "ETF",
                "country": "IE",
                "currency": "EUR",
                "source_exchange": "XETRA",
                "fetched_at": "2026-01-01T00:00:00+00:00",
            },
        )
    )
    client = _client(state)

    rejected = client.post("/metadata-filter/fetch-all-isins", headers=_headers())
    client.post(
        "/credentials/eodhd",
        headers=_headers(idempotency="credential-fetch-all-isins"),
        json={"provider_key": "secret-provider-token"},
    )
    credential_status = _json(client.get("/credentials/eodhd", headers=_headers(csrf=False)))
    fetched = _json(client.post("/metadata-filter/fetch-all-isins", headers=_headers()))
    fetched_again = _json(client.post("/metadata-filter/fetch-all-isins", headers=_headers()))

    assert rejected.status_code == 422
    assert _json(rejected)["detail"]["code"] == "eodhd_key_required"
    assert credential_status["status"] == "active"
    assert fetched == {
        "country_count": 1,
        "currency_count": 1,
        "exchange_count": 1,
        "instrument_type_count": 1,
        "row_count": 1,
        "status": "succeeded",
    }
    assert fetched_again == fetched


def test_projects_selections_and_analyses_are_user_scoped_and_paginated() -> None:
    client = _client()
    project = _json(
        client.post(
            "/projects",
            headers=_headers(idempotency="project-1"),
            json={"name": "ETF Research"},
        )
    )
    repeated_project = _json(
        client.post(
            "/projects",
            headers=_headers(idempotency="project-1"),
            json={"name": "ETF Research"},
        )
    )
    selection = _json(
        client.post(
            "/selections",
            headers=_headers(),
            json={
                "project_id": project["project_id"],
                "name": "Monthly ETFs",
                "member_ids": ["IE1", "IE2"],
            },
        )
    )
    analysis = _json(
        client.post(
            "/analyses",
            headers=_headers(idempotency="analysis-1"),
            json={
                "project_id": project["project_id"],
                "selection_id": selection["selection_id"],
                "settings": {"objective": "minimum_variance"},
            },
        )
    )
    repeated_analysis = _json(
        client.post(
            "/analyses",
            headers=_headers(idempotency="analysis-1"),
            json={
                "project_id": project["project_id"],
                "selection_id": selection["selection_id"],
                "settings": {"objective": "changed"},
            },
        )
    )
    computed_statistics = _json(
        client.post(
            "/statistics/univariate/compute",
            headers=_headers(idempotency="statistics-univariate-1"),
            json={"project_id": project["project_id"]},
        )
    )
    projects_page = _json(client.get("/projects?limit=1&offset=0", headers=_headers(csrf=False)))

    assert repeated_project == project
    assert selection["member_ids"] == ["IE1", "IE2"]
    assert analysis["status"] == "succeeded"
    assert computed_statistics == {
        "kind": "univariate",
        "progress": 100,
        "project_id": project["project_id"],
        "selected_count": 1,
        "status": "succeeded",
    }
    assert (
        _json(
            client.post(
                "/statistics/bivariate/compute",
                headers=_headers(idempotency="statistics-bivariate-1"),
                json={"project_id": project["project_id"]},
            )
        )["selected_count"]
        == 0
    )
    assert analysis["cache_hit"] is False
    assert repeated_analysis["run_id"] == analysis["run_id"]
    assert repeated_analysis["cache_hit"] is True
    assert len(projects_page["items"]) == 1
    assert _json(
        client.get(f"/analyses/{analysis['run_id']}/metrics", headers=_headers(csrf=False))
    )["items"]
    assert _json(
        client.get(f"/analyses/{analysis['run_id']}/returns", headers=_headers(csrf=False))
    )["items"]
    assert _json(
        client.get(f"/analyses/{analysis['run_id']}/weights", headers=_headers(csrf=False))
    )["items"]
    assert "summary" in _json(
        client.get(f"/analyses/{analysis['run_id']}/report", headers=_headers(csrf=False))
    )

    assert (
        client.get(
            f"/selections/{selection['selection_id']}", headers=_headers("user-b", csrf=False)
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/analyses/{analysis['run_id']}", headers=_headers("user-b", csrf=False)
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/projects/{project['project_id']}", headers=_headers("user-b")).status_code
        == 404
    )
    assert (
        client.post(
            "/statistics/bivariate/compute",
            headers=_headers("user-b"),
            json={"project_id": project["project_id"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/statistics/unknown/compute",
            headers=_headers(),
            json={"project_id": project["project_id"]},
        ).status_code
        == 422
    )
    deleted_project = _json(client.delete(f"/projects/{project['project_id']}", headers=_headers()))
    assert deleted_project == {"project_id": project["project_id"], "status": "deleted"}
    assert _json(client.get("/projects", headers=_headers(csrf=False)))["items"] == []
    assert (
        client.get(
            f"/selections/{selection['selection_id']}", headers=_headers(csrf=False)
        ).status_code
        == 404
    )
    assert (
        client.get(f"/analyses/{analysis['run_id']}", headers=_headers(csrf=False)).status_code
        == 404
    )
    assert client.get("/projects?limit=0", headers=_headers(csrf=False)).status_code == 422


def test_projects_listing_removes_discontinued_statistics_smoke_project() -> None:
    client = _client()
    project = _json(
        client.post(
            "/projects",
            headers=_headers(idempotency="statistics-smoke-project"),
            json={"name": "Statistics Smoke"},
        )
    )
    selection = _json(
        client.post(
            "/selections",
            headers=_headers(),
            json={
                "project_id": project["project_id"],
                "name": "Smoke Selection",
                "member_ids": ["IE1", "IE2"],
            },
        )
    )

    assert _json(client.get("/projects", headers=_headers(csrf=False))) == {"items": []}
    assert (
        client.get(
            f"/selections/{selection['selection_id']}", headers=_headers(csrf=False)
        ).status_code
        == 404
    )


def test_univariate_statistics_summary_exposes_table_metrics_and_filter_options() -> None:
    state = HostedApiState(
        univariate_statistics_rows=(
            {
                "isin": "IE1",
                "exchange": "XETRA",
                "code": "AAA",
                "annualized_volatility": 0.10,
                "distribution_frequency": "monthly",
            },
            {
                "isin": "IE2",
                "exchange": "XETRA",
                "code": "BBB",
                "annualized_volatility": 0.20,
                "distribution_frequency": "quarterly",
            },
        )
    )
    client = _client(state)

    payload = _json(client.get("/statistics/univariate/summary", headers=_headers(csrf=False)))
    rows = {row["name"]: row for row in payload["items"]}

    assert payload["categories"][0]["label"] == "Instrument Identity"
    assert rows["annualized_volatility"]["category"] == "Volatility And Downside Risk"
    assert round(rows["annualized_volatility"]["mean"], 6) == 0.15
    assert round(rows["annualized_volatility"]["median"], 6) == 0.15
    assert rows["annualized_volatility"]["three_std_range"] is not None
    assert rows["annualized_volatility"]["filter_options"] == [
        {"label": ">", "value": ">"},
        {"label": ">=", "value": ">="},
        {"label": "<", "value": "<"},
        {"label": "<=", "value": "<="},
        {"label": "=", "value": "="},
        {"label": "!=", "value": "!="},
    ]
    assert rows["distribution_frequency"]["category"] == "Income Distribution"
    assert rows["distribution_frequency"]["filter_options"] == [
        {"label": "monthly", "value": "distribution_frequency=monthly"},
        {"label": "quarterly", "value": "distribution_frequency=quarterly"},
    ]


def test_account_deletion_removes_user_owned_api_state() -> None:
    client = _client()
    project = _json(client.post("/projects", headers=_headers(), json={"name": "Delete Me"}))
    selection = _json(
        client.post(
            "/selections",
            headers=_headers(),
            json={"project_id": project["project_id"], "name": "S", "member_ids": ["IE1"]},
        )
    )

    assert client.delete("/account", headers=_headers()).json() == {"status": "deleted"}
    assert client.get("/projects", headers=_headers(csrf=False)).json() == {"items": []}
    assert (
        client.get(
            f"/selections/{selection['selection_id']}", headers=_headers(csrf=False)
        ).status_code
        == 404
    )
