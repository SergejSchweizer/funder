"""FastAPI hosted API boundary for user-scoped Founder workflows."""

# pyright: reportUnusedFunction=false
# ruff: noqa: B008

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from founder.config import EodhdConfig
from founder.entitlements import (
    InMemoryEntitlementStore,
    ProviderDownloadRun,
    delete_user_entitlements,
    publish_user_data_snapshot,
)
from founder.hosted_credentials import (
    CredentialStatus,
    CredentialVaultError,
    EodhdCredentialVault,
    InMemoryCredentialStore,
    KeyEncryptionKey,
)
from founder.metadata_filter import write_metadata_selection
from founder.paths import LakePaths
from founder.schemas import required_fields
from founder.selection_filters import Predicate, filter_rows
from founder.table_io import JsonRow, read_rows
from founder.univariate_categories import (
    UNIVARIATE_PORTFOLIO_CATEGORIES,
    category_for_univariate_field,
)
from founder.workflows import run_fetch_all_quotes_workflow

SESSION_COOKIE_NAME = "founder_session_user"
CSRF_COOKIE_NAME = "founder_csrf"
LOCAL_DEV_USER_ID = "local-google-dev-user"
LOCAL_DEV_CSRF_TOKEN = "valid-csrf"
REMOVED_PROJECT_NAMES = frozenset({"Statistics Smoke"})


class HostedApiError(RuntimeError):
    """Raised when the hosted API cannot satisfy a user-scoped request."""


class CredentialSetRequest(BaseModel):
    """Request to set or replace a provider credential."""

    provider_key: str = Field(min_length=1, max_length=4096)


class DownloadRequest(BaseModel):
    """Request to plan or run a user-key-backed download."""

    symbols: list[str] = Field(default_factory=list, max_length=1000)


class ProjectCreateRequest(BaseModel):
    """Request to create one user-owned project."""

    name: str = Field(min_length=1, max_length=120)


class MetadataFilterProjectRequest(BaseModel):
    """Request to create one project from metadata-filter criteria."""

    exchange: str = Field(default="", max_length=80)
    name: str = Field(default="", max_length=240)
    instrument_type: str = Field(default="", max_length=80)
    country: str = Field(default="", max_length=80)
    currency: str = Field(default="", max_length=80)


class SelectionCreateRequest(BaseModel):
    """Request to persist one user-owned selection."""

    project_id: str
    name: str = Field(min_length=1, max_length=120)
    member_ids: list[str] = Field(default_factory=list, min_length=1, max_length=1000)


class AnalysisCreateRequest(BaseModel):
    """Request to submit one analysis over an authorized selection."""

    project_id: str
    selection_id: str
    settings: JsonRow = Field(default_factory=dict)


class StatisticsComputeRequest(BaseModel):
    """Request to compute one statistics layer for a user-owned project."""

    project_id: str


class LoadSelectedIsinsRequest(BaseModel):
    """Request to load quote data for one user-owned project selection."""

    project_id: str


class UserOwnedRow(Protocol):
    """Protocol for rows that are scoped to one hosted API user."""

    @property
    def user_id(self) -> str:
        """User that owns the row."""
        ...


@dataclass(frozen=True)
class ApiUser:
    """Authenticated hosted API user."""

    user_id: str
    csrf_token: str


@dataclass(frozen=True)
class ProjectRecord:
    """User-owned project record."""

    project_id: str
    user_id: str
    name: str


@dataclass(frozen=True)
class SelectionRecord:
    """User-owned selection record."""

    selection_id: str
    user_id: str
    project_id: str
    name: str
    member_ids: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisRecord:
    """User-owned analysis run record."""

    run_id: str
    user_id: str
    project_id: str
    selection_id: str
    logical_hash: str
    status: str
    metrics: tuple[JsonRow, ...]
    returns: tuple[JsonRow, ...]
    weights: tuple[JsonRow, ...]
    report: JsonRow


@dataclass
class HostedApiState:
    """In-memory hosted API repository set for deterministic tests and local dev."""

    credentials: InMemoryCredentialStore = field(default_factory=InMemoryCredentialStore)
    entitlements: InMemoryEntitlementStore = field(default_factory=InMemoryEntitlementStore)
    projects_by_id: dict[str, ProjectRecord] = field(
        default_factory=lambda: dict[str, ProjectRecord]()
    )
    selections_by_id: dict[str, SelectionRecord] = field(
        default_factory=lambda: dict[str, SelectionRecord]()
    )
    downloads_by_id: dict[str, ProviderDownloadRun] = field(
        default_factory=lambda: dict[str, ProviderDownloadRun]()
    )
    download_summaries_by_id: dict[str, JsonRow] = field(
        default_factory=lambda: dict[str, JsonRow]()
    )
    analyses_by_id: dict[str, AnalysisRecord] = field(
        default_factory=lambda: dict[str, AnalysisRecord]()
    )
    idempotency_refs: dict[tuple[str, str, str], str] = field(
        default_factory=lambda: dict[tuple[str, str, str], str]()
    )
    audit_events: list[JsonRow] = field(default_factory=lambda: list[JsonRow]())
    all_isins_rows: tuple[JsonRow, ...] = field(default_factory=tuple)
    univariate_statistics_rows: tuple[JsonRow, ...] = field(default_factory=tuple)

    def credential_vault(self) -> EodhdCredentialVault:
        """Return a deterministic local credential vault."""

        return EodhdCredentialVault(
            store=self.credentials,
            key_encryption_key=KeyEncryptionKey("dev-v1", b"0" * 32),
            fingerprint_secret=b"founder-dev-fingerprint-secret",
        )


def create_app(state: HostedApiState | None = None) -> FastAPI:
    """Create the hosted FastAPI application."""

    resolved_state = state or HostedApiState()
    app = FastAPI(title="Founder Hosted API", version="0.1.0")
    app.state.founder_state = resolved_state

    def current_state() -> HostedApiState:
        return resolved_state

    def current_user(
        x_founder_user: str | None = Header(default=None, alias="X-Founder-User"),
        x_founder_csrf: str | None = Header(default=None, alias="X-Founder-CSRF"),
        founder_session_user: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        founder_csrf: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME),
    ) -> ApiUser:
        user_id = x_founder_user or founder_session_user
        if not user_id:
            raise _http_error(status.HTTP_401_UNAUTHORIZED, "authentication_required")
        return ApiUser(user_id=user_id, csrf_token=x_founder_csrf or founder_csrf or "")

    def csrf_user(
        request: Request,
        user: ApiUser = Depends(current_user),
    ) -> ApiUser:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and user.csrf_token != "valid-csrf":
            raise _http_error(status.HTTP_403_FORBIDDEN, "csrf_required")
        return user

    @app.get("/health")
    def health() -> JsonRow:
        return {"status": "ok"}

    @app.get("/auth/google/start")
    def start_google_login() -> RedirectResponse:
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=LOCAL_DEV_USER_ID,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=3600,
        )
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=LOCAL_DEV_CSRF_TOKEN,
            httponly=False,
            secure=False,
            samesite="lax",
            max_age=3600,
        )
        return response

    @app.get("/auth/logout")
    def logout() -> RedirectResponse:
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie(SESSION_COOKIE_NAME)
        response.delete_cookie(CSRF_COOKIE_NAME)
        return response

    @app.get("/session")
    def session(user: ApiUser = Depends(current_user)) -> JsonRow:
        return {"authenticated": True, "user_id": user.user_id, "csrf_token": user.csrf_token}

    @app.get("/credentials/eodhd")
    def credential_status(
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        try:
            return _credential_status_row(api_state.credential_vault().status(user_id=user.user_id))
        except Exception as error:
            raise _http_error(status.HTTP_404_NOT_FOUND, "credential_not_found") from error

    @app.post("/credentials/eodhd")
    def set_credential(
        payload: CredentialSetRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonRow:
        cached = _idempotent_response(
            api_state,
            user_id=user.user_id,
            operation="set-credential",
            idempotency_key=idempotency_key,
        )
        if cached is not None:
            return credential_status(user, api_state)
        status_row = api_state.credential_vault().set_credential(
            user_id=user.user_id,
            provider_key=payload.provider_key,
        )
        _remember_idempotency(
            api_state,
            user.user_id,
            "set-credential",
            idempotency_key,
            status_row.credential_id,
        )
        _audit(api_state, user.user_id, "credential.set")
        return _credential_status_row(status_row)

    @app.delete("/credentials/eodhd")
    def delete_credential(
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        try:
            status_row = api_state.credential_vault().delete(user_id=user.user_id)
        except Exception as error:
            raise _http_error(status.HTTP_404_NOT_FOUND, "credential_not_found") from error
        _audit(api_state, user.user_id, "credential.delete")
        return _credential_status_row(status_row)

    @app.post("/downloads/plan")
    def plan_download(
        payload: DownloadRequest,
        user: ApiUser = Depends(csrf_user),
    ) -> JsonRow:
        request_hash = _stable_hash({"user_id": user.user_id, "symbols": sorted(payload.symbols)})
        return {"download_run_id": _opaque_id("download-plan", request_hash), "status": "planned"}

    @app.post("/downloads/run")
    def run_download(
        payload: DownloadRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonRow:
        cached_run_id = _idempotent_response(
            api_state,
            user_id=user.user_id,
            operation="download-run",
            idempotency_key=idempotency_key,
        )
        if cached_run_id is not None:
            return _download_row(api_state.downloads_by_id[cached_run_id])
        observation_ids = tuple(
            _opaque_id("observation", symbol) for symbol in sorted(set(payload.symbols))
        )
        request_hash = _stable_hash({"user_id": user.user_id, "symbols": list(observation_ids)})
        run = ProviderDownloadRun(
            download_run_id=_opaque_id("download-run", request_hash),
            user_id=user.user_id,
            credential_id="credential-ref",
            provider="eodhd",
            status="succeeded",
            returned_observation_ids=observation_ids,
            request_hash=request_hash,
        )
        api_state.downloads_by_id[run.download_run_id] = run
        publish_user_data_snapshot(store=api_state.entitlements, run=run)
        _remember_idempotency(
            api_state, user.user_id, "download-run", idempotency_key, run.download_run_id
        )
        _audit(api_state, user.user_id, "download.run")
        return _download_row(run)

    @app.get("/downloads/{download_run_id}")
    def download_status(
        download_run_id: str,
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        run = _require_user_row(api_state.downloads_by_id, download_run_id, user.user_id)
        return _download_row(run)

    @app.get("/datasets")
    def visible_datasets(
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        observation_ids = api_state.entitlements.visible_observation_ids(user.user_id)
        return {
            "items": [
                {"dataset_id": observation_id, "dataset_type": "eodhd_observation"}
                for observation_id in observation_ids
            ]
        }

    @app.post("/projects")
    def create_project(
        payload: ProjectCreateRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonRow:
        cached_project_id = _idempotent_response(
            api_state,
            user_id=user.user_id,
            operation=f"project:{payload.name}",
            idempotency_key=idempotency_key,
        )
        if cached_project_id is not None:
            return _project_row(api_state.projects_by_id[cached_project_id])
        project_id = _opaque_id("project", f"{user.user_id}:{payload.name}")
        project = ProjectRecord(project_id=project_id, user_id=user.user_id, name=payload.name)
        api_state.projects_by_id.setdefault(project_id, project)
        _remember_idempotency(
            api_state, user.user_id, f"project:{payload.name}", idempotency_key, project_id
        )
        _audit(api_state, user.user_id, "project.create")
        return _project_row(api_state.projects_by_id[project_id])

    @app.get("/projects")
    def list_projects(
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
        limit: int = 100,
        offset: int = 0,
    ) -> JsonRow:
        _remove_discontinued_projects(api_state, user.user_id)
        items = [
            _project_with_selection_row(api_state, project, user.user_id)
            for project in api_state.projects_by_id.values()
            if project.user_id == user.user_id
        ]
        return {"items": _page(items, limit=limit, offset=offset)}

    @app.delete("/projects/{project_id}")
    def delete_project(
        project_id: str,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        _require_user_row(api_state.projects_by_id, project_id, user.user_id)
        api_state.projects_by_id.pop(project_id, None)
        api_state.selections_by_id = {
            row_id: row
            for row_id, row in api_state.selections_by_id.items()
            if row.project_id != project_id or row.user_id != user.user_id
        }
        api_state.analyses_by_id = {
            row_id: row
            for row_id, row in api_state.analyses_by_id.items()
            if row.project_id != project_id or row.user_id != user.user_id
        }
        _audit(api_state, user.user_id, "project.delete")
        return {"status": "deleted", "project_id": project_id}

    @app.get("/metadata-filter/options")
    def metadata_filter_options(
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        _ = user
        rows = _all_isins_rows(api_state)
        return {
            "exchange": _distinct_options(rows, "exchange"),
            "instrument_type": _distinct_options(rows, "instrument_type"),
            "country": _distinct_options(rows, "country"),
            "currency": _distinct_options(rows, "currency"),
        }

    @app.post("/metadata-filter/fetch-all-isins")
    def fetch_all_isins_for_metadata_filter(
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        try:
            api_state.credential_vault().status(user_id=user.user_id)
        except Exception as error:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "eodhd_key_required"
            ) from error
        rows = _all_isins_rows(api_state)
        if not rows:
            raise _http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "all_isins_not_available")
        _audit(api_state, user.user_id, "metadata_filter.all_isins.fetch")
        return {
            "status": "succeeded",
            "row_count": len(rows),
            "exchange_count": len(_distinct_options(rows, "exchange")),
            "instrument_type_count": len(_distinct_options(rows, "instrument_type")),
            "country_count": len(_distinct_options(rows, "country")),
            "currency_count": len(_distinct_options(rows, "currency")),
        }

    @app.post("/metadata-filter/projects")
    def create_metadata_filter_project(
        payload: MetadataFilterProjectRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonRow:
        predicates = _metadata_filter_predicates(payload)
        if not predicates:
            raise _http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "metadata_filter_required")
        selected_rows = filter_rows(_all_isins_rows(api_state), predicates)
        if not selected_rows:
            raise _http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "metadata_filter_empty")
        project_name = _metadata_filter_project_name(payload)
        cached_project_id = _idempotent_response(
            api_state,
            user_id=user.user_id,
            operation=f"metadata-filter-project:{project_name}",
            idempotency_key=idempotency_key,
        )
        if cached_project_id is not None:
            project = api_state.projects_by_id[cached_project_id]
            selection = _selection_for_project(api_state, project.project_id, user.user_id)
            return _metadata_filter_project_row(project, selection, len(selected_rows))
        project_id = _opaque_id("project", f"{user.user_id}:{project_name}")
        project = ProjectRecord(project_id=project_id, user_id=user.user_id, name=project_name)
        api_state.projects_by_id.setdefault(project_id, project)
        member_ids = tuple(
            sorted(
                {
                    f"{row['isin']}:{row['exchange']}:{row['code']}"
                    for row in selected_rows
                    if row.get("isin") and row.get("exchange") and row.get("code")
                }
            )
        )
        selection_id = _opaque_id(
            "selection", f"{user.user_id}:{project_id}:{project_name}:{member_ids}"
        )
        selection = SelectionRecord(
            selection_id=selection_id,
            user_id=user.user_id,
            project_id=project_id,
            name=project_name,
            member_ids=member_ids,
        )
        api_state.selections_by_id.setdefault(selection_id, selection)
        _write_hosted_metadata_selection(selection_id, selected_rows, predicates)
        _remember_idempotency(
            api_state,
            user.user_id,
            f"metadata-filter-project:{project_name}",
            idempotency_key,
            project_id,
        )
        _audit(api_state, user.user_id, "metadata_filter.project.create")
        return _metadata_filter_project_row(
            api_state.projects_by_id[project_id],
            api_state.selections_by_id[selection_id],
            len(selected_rows),
        )

    @app.post("/selections")
    def create_selection(
        payload: SelectionCreateRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        _require_user_row(api_state.projects_by_id, payload.project_id, user.user_id)
        member_ids = tuple(sorted(set(payload.member_ids)))
        selection_id = _opaque_id(
            "selection", f"{user.user_id}:{payload.project_id}:{payload.name}:{member_ids}"
        )
        selection = SelectionRecord(
            selection_id=selection_id,
            user_id=user.user_id,
            project_id=payload.project_id,
            name=payload.name,
            member_ids=member_ids,
        )
        api_state.selections_by_id.setdefault(selection_id, selection)
        _audit(api_state, user.user_id, "selection.create")
        return _selection_row(api_state.selections_by_id[selection_id])

    @app.get("/selections/{selection_id}")
    def selection_detail(
        selection_id: str,
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        return _selection_row(
            _require_user_row(api_state.selections_by_id, selection_id, user.user_id)
        )

    @app.post("/data/load-selected-isins")
    def load_selected_isins(
        payload: LoadSelectedIsinsRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonRow:
        _require_user_row(api_state.projects_by_id, payload.project_id, user.user_id)
        selection = _selection_for_project(api_state, payload.project_id, user.user_id)
        cached_run_id = _idempotent_response(
            api_state,
            user_id=user.user_id,
            operation=f"fetch-all-quotes:{payload.project_id}",
            idempotency_key=idempotency_key,
        )
        if cached_run_id is not None:
            return _load_selected_isins_row(
                api_state.downloads_by_id[cached_run_id],
                summary=api_state.download_summaries_by_id.get(cached_run_id),
            )
        request_hash = _stable_hash(
            {
                "project_id": payload.project_id,
                "selection_id": selection.selection_id,
                "member_ids": list(selection.member_ids),
            }
        )
        try:
            provider_key = api_state.credential_vault().unwrap_for_provider_call(
                user_id=user.user_id
            )
        except CredentialVaultError as error:
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "eodhd_credential_required"
            ) from error
        summary = run_fetch_all_quotes_workflow(
            root=_lake_paths().root,
            run_id=_opaque_id("fetch-all-quotes", request_hash),
            selection_id=selection.selection_id,
            concurrency=max(1, os.cpu_count() or 1),
            eodhd_config=EodhdConfig(api_token=provider_key),
        )
        run = ProviderDownloadRun(
            download_run_id=_opaque_id("fetch-all-quotes", f"{user.user_id}:{request_hash}"),
            user_id=user.user_id,
            credential_id="project-selection",
            provider="eodhd",
            status="succeeded",
            returned_observation_ids=selection.member_ids,
            request_hash=request_hash,
        )
        api_state.downloads_by_id[run.download_run_id] = run
        api_state.download_summaries_by_id[run.download_run_id] = dict(summary)
        publish_user_data_snapshot(store=api_state.entitlements, run=run)
        _remember_idempotency(
            api_state,
            user.user_id,
            f"fetch-all-quotes:{payload.project_id}",
            idempotency_key,
            run.download_run_id,
        )
        _audit(api_state, user.user_id, "fetch_all_quotes.load_selected_isins")
        return _load_selected_isins_row(run, summary=summary)

    @app.post("/statistics/{statistics_kind}/compute")
    def compute_statistics(
        statistics_kind: str,
        payload: StatisticsComputeRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        allowed_kinds = {"univariate", "bivariate", "multivariate"}
        if statistics_kind not in allowed_kinds:
            raise _http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_statistics_kind")
        _require_user_row(api_state.projects_by_id, payload.project_id, user.user_id)
        selection = _selection_for_project(api_state, payload.project_id, user.user_id)
        _audit(api_state, user.user_id, f"statistics.{statistics_kind}.compute")
        return {
            "kind": statistics_kind,
            "project_id": payload.project_id,
            "selected_count": _statistics_selected_count(
                len(selection.member_ids), statistics_kind
            ),
            "status": "succeeded",
            "progress": 100,
        }

    @app.get("/statistics/univariate/summary")
    def univariate_statistics_summary(
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        _ = user
        return {
            "items": _univariate_summary_rows(_univariate_statistics_rows(api_state)),
            "categories": [
                {
                    "key": category.key,
                    "label": category.label,
                    "purpose": category.purpose,
                }
                for category in UNIVARIATE_PORTFOLIO_CATEGORIES
            ],
        }

    @app.post("/analyses")
    def create_analysis(
        payload: AnalysisCreateRequest,
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JsonRow:
        selection = _require_user_row(
            api_state.selections_by_id, payload.selection_id, user.user_id
        )
        _require_user_row(api_state.projects_by_id, payload.project_id, user.user_id)
        logical_hash = _stable_hash(
            {
                "selection_id": selection.selection_id,
                "member_ids": list(selection.member_ids),
                "settings": payload.settings,
            }
        )
        cached_run_id = _idempotent_response(
            api_state,
            user_id=user.user_id,
            operation="analysis",
            idempotency_key=idempotency_key,
        )
        cache_hit = cached_run_id is not None
        if cached_run_id is not None:
            return {**_analysis_row(api_state.analyses_by_id[cached_run_id]), "cache_hit": True}
        run_id = _opaque_id("analysis", f"{user.user_id}:{logical_hash}")
        analysis = AnalysisRecord(
            run_id=run_id,
            user_id=user.user_id,
            project_id=payload.project_id,
            selection_id=selection.selection_id,
            logical_hash=logical_hash,
            status="succeeded",
            metrics=({"name": "selection_size", "value": len(selection.member_ids)},),
            returns=tuple(
                {"member_id": member_id, "return": 0.0} for member_id in selection.member_ids
            ),
            weights=tuple(
                {"member_id": member_id, "weight": 1 / len(selection.member_ids)}
                for member_id in selection.member_ids
            ),
            report={"summary": "deterministic hosted analysis placeholder"},
        )
        api_state.analyses_by_id[run_id] = analysis
        _remember_idempotency(api_state, user.user_id, "analysis", idempotency_key, run_id)
        _audit(api_state, user.user_id, "analysis.create")
        return {**_analysis_row(analysis), "cache_hit": cache_hit}

    @app.get("/analyses/{run_id}")
    def analysis_status(
        run_id: str,
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        return _analysis_row(_require_user_row(api_state.analyses_by_id, run_id, user.user_id))

    @app.get("/analyses/{run_id}/metrics")
    def analysis_metrics(
        run_id: str,
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        analysis = _require_user_row(api_state.analyses_by_id, run_id, user.user_id)
        return {"items": list(analysis.metrics)}

    @app.get("/analyses/{run_id}/returns")
    def analysis_returns(
        run_id: str,
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        analysis = _require_user_row(api_state.analyses_by_id, run_id, user.user_id)
        return {"items": list(analysis.returns)}

    @app.get("/analyses/{run_id}/weights")
    def analysis_weights(
        run_id: str,
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        analysis = _require_user_row(api_state.analyses_by_id, run_id, user.user_id)
        return {"items": list(analysis.weights)}

    @app.get("/analyses/{run_id}/report")
    def analysis_report(
        run_id: str,
        user: ApiUser = Depends(current_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        analysis = _require_user_row(api_state.analyses_by_id, run_id, user.user_id)
        return analysis.report

    @app.delete("/account")
    def delete_account(
        user: ApiUser = Depends(csrf_user),
        api_state: HostedApiState = Depends(current_state),
    ) -> JsonRow:
        delete_user_entitlements(store=api_state.entitlements, user_id=user.user_id)
        api_state.projects_by_id = {
            row_id: row
            for row_id, row in api_state.projects_by_id.items()
            if row.user_id != user.user_id
        }
        api_state.selections_by_id = {
            row_id: row
            for row_id, row in api_state.selections_by_id.items()
            if row.user_id != user.user_id
        }
        api_state.analyses_by_id = {
            row_id: row
            for row_id, row in api_state.analyses_by_id.items()
            if row.user_id != user.user_id
        }
        _audit(api_state, user.user_id, "account.delete")
        return {"status": "deleted"}

    return app


def _lake_paths() -> LakePaths:
    return LakePaths(root=Path(os.environ.get("FOUNDER_LAKE_ROOT", "lake")))


def _all_isins_rows(state: HostedApiState) -> tuple[JsonRow, ...]:
    if state.all_isins_rows:
        return state.all_isins_rows
    return tuple(read_rows(_lake_paths().all_isins()))


def _univariate_statistics_rows(state: HostedApiState) -> tuple[JsonRow, ...]:
    if state.univariate_statistics_rows:
        return state.univariate_statistics_rows
    root = _lake_paths().gold / "univariate_statistics"
    rows: list[JsonRow] = []
    for path in sorted(root.glob("*/*.parquet")):
        rows.extend(read_rows(path))
    return tuple(rows)


def _write_hosted_metadata_selection(
    selection_id: str,
    selected_rows: Iterable[Mapping[str, Any]],
    predicates: tuple[Predicate, ...],
) -> None:
    if "FOUNDER_LAKE_ROOT" not in os.environ:
        return
    paths = _lake_paths()
    write_metadata_selection(
        paths,
        selection_id,
        tuple(selected_rows),
        predicates=predicates,
        source_path=str(paths.all_isins()),
    )


def _univariate_summary_rows(rows: tuple[JsonRow, ...]) -> list[JsonRow]:
    return [
        _univariate_field_summary(field, rows) for field in required_fields("univariate_statistics")
    ]


def _univariate_field_summary(field: str, rows: tuple[JsonRow, ...]) -> JsonRow:
    category = category_for_univariate_field(field)
    numeric_values = _finite_numeric_values(row.get(field) for row in rows)
    distinct_values = sorted(
        {str(row.get(field, "")).strip() for row in rows if str(row.get(field, "")).strip()}
    )
    if numeric_values:
        mean_value = statistics.fmean(numeric_values)
        std_value = statistics.stdev(numeric_values) if len(numeric_values) > 1 else 0.0
        median_value: float | str | None = statistics.median(numeric_values)
        mean_output: float | str | None = mean_value
        lower_bound = mean_value - (3 * std_value)
        upper_bound = mean_value + (3 * std_value)
        band_output: str | None = f"{lower_bound:.6g}..{upper_bound:.6g}"
    else:
        mean_output = None
        median_value = _categorical_median(distinct_values)
        band_output = None
    return {
        "name": field,
        "category": category.label if category is not None else "Uncategorized",
        "mean": mean_output,
        "median": median_value,
        "three_std_range": band_output,
        "filter_options": _univariate_filter_options(field, numeric_values, distinct_values),
    }


def _finite_numeric_values(values: Iterable[object]) -> list[float]:
    numbers: list[float] = []
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int | float):
            number = float(value)
        else:
            try:
                number = float(str(value))
            except ValueError:
                continue
        if math.isfinite(number):
            numbers.append(number)
    return numbers


def _categorical_median(values: list[str]) -> str | None:
    if not values:
        return None
    return values[len(values) // 2]


def _univariate_filter_options(
    field: str, numeric_values: list[float], distinct_values: list[str]
) -> list[JsonRow]:
    if numeric_values:
        return [
            {"value": operator, "label": operator} for operator in (">", ">=", "<", "<=", "=", "!=")
        ]
    if distinct_values:
        return [{"value": f"{field}={value}", "label": value} for value in distinct_values[:100]]
    return [{"value": operator, "label": operator} for operator in ("=", "!=", "~")]


def _distinct_options(rows: tuple[JsonRow, ...], field: str) -> list[str]:
    return sorted(
        {str(row.get(field, "")).strip() for row in rows if str(row.get(field, "")).strip()}
    )


def _metadata_filter_predicates(payload: MetadataFilterProjectRequest) -> tuple[Predicate, ...]:
    predicates: list[Predicate] = []
    if payload.exchange.strip():
        predicates.append(Predicate("exchange", "=", payload.exchange.strip()))
    if payload.name.strip():
        predicates.append(Predicate("name", "~", payload.name.strip()))
    if payload.instrument_type.strip():
        predicates.append(Predicate("instrument_type", "=", payload.instrument_type.strip()))
    if payload.country.strip():
        predicates.append(Predicate("country", "=", payload.country.strip()))
    if payload.currency.strip():
        predicates.append(Predicate("currency", "=", payload.currency.strip()))
    return tuple(predicates)


def _metadata_filter_project_name(payload: MetadataFilterProjectRequest) -> str:
    parts = [
        _project_name_part(payload.exchange),
        _project_name_part(payload.name),
        _project_name_part(payload.instrument_type),
        _project_name_part(payload.country),
        _project_name_part(payload.currency),
    ]
    normalized = [part for part in parts if part]
    return "_".join(normalized) or "metadata_filter_project"


def _project_name_part(value: str) -> str:
    return "_".join(str(value).strip().casefold().split())


def _selection_for_project(state: HostedApiState, project_id: str, user_id: str) -> SelectionRecord:
    for selection in state.selections_by_id.values():
        if selection.project_id == project_id and selection.user_id == user_id:
            return selection
    raise _http_error(status.HTTP_404_NOT_FOUND, "not_found")


def _metadata_filter_project_row(
    project: ProjectRecord, selection: SelectionRecord, selected_count: int
) -> JsonRow:
    return {
        "project": _project_row(project),
        "selection": _selection_row(selection),
        "selected_count": selected_count,
    }


def _credential_status_row(status_row: CredentialStatus) -> JsonRow:
    return {
        "credential_id": status_row.credential_id,
        "provider": status_row.provider,
        "status": status_row.status,
        "key_version": status_row.key_version,
        "masked_label": status_row.masked_label,
    }


def _download_row(run: ProviderDownloadRun) -> JsonRow:
    return {
        "download_run_id": run.download_run_id,
        "provider": run.provider,
        "status": run.status,
        "observation_count": len(run.returned_observation_ids),
    }


def _load_selected_isins_row(
    run: ProviderDownloadRun,
    *,
    summary: Mapping[str, Any] | None = None,
) -> JsonRow:
    workflow_summary = dict(summary or {})
    return {
        **_download_row(run),
        "kind": "load-data",
        "progress": 100,
        "quote_errors": int(workflow_summary.get("quote_errors", 0)),
        "quote_successes": int(workflow_summary.get("quote_successes", 0)),
        "raw_dataset_errors": int(workflow_summary.get("raw_dataset_errors", 0)),
        "raw_dataset_successes": int(workflow_summary.get("raw_dataset_successes", 0)),
        "run_id": str(workflow_summary.get("run_id", run.download_run_id)),
        "selected_listing_count": int(
            workflow_summary.get("selected_listing_count", len(run.returned_observation_ids))
        ),
        "selected_count": len(run.returned_observation_ids),
        "silver_quote_rows": int(workflow_summary.get("silver_quote_rows", 0)),
    }


def _project_row(project: ProjectRecord) -> JsonRow:
    return {"project_id": project.project_id, "name": project.name}


def _remove_discontinued_projects(state: HostedApiState, user_id: str) -> None:
    project_ids = {
        project_id
        for project_id, project in state.projects_by_id.items()
        if project.user_id == user_id and project.name in REMOVED_PROJECT_NAMES
    }
    if not project_ids:
        return
    state.projects_by_id = {
        project_id: project
        for project_id, project in state.projects_by_id.items()
        if project_id not in project_ids
    }
    state.selections_by_id = {
        selection_id: selection
        for selection_id, selection in state.selections_by_id.items()
        if selection.project_id not in project_ids or selection.user_id != user_id
    }
    state.analyses_by_id = {
        analysis_id: analysis
        for analysis_id, analysis in state.analyses_by_id.items()
        if analysis.project_id not in project_ids or analysis.user_id != user_id
    }


def _project_with_selection_row(
    state: HostedApiState, project: ProjectRecord, user_id: str
) -> JsonRow:
    try:
        selection = _selection_for_project(state, project.project_id, user_id)
    except HTTPException:
        return {**_project_row(project), "selected_count": 0, "data_loaded": False}
    return {
        **_project_row(project),
        "selection_id": selection.selection_id,
        "selected_count": len(selection.member_ids),
        "data_loaded": _project_data_loaded(state, project.project_id, user_id),
    }


def _project_data_loaded(state: HostedApiState, project_id: str, user_id: str) -> bool:
    operation_prefix = f"fetch-all-quotes:{project_id}"
    for (
        stored_user_id,
        operation,
        _idempotency_key,
    ), download_run_id in state.idempotency_refs.items():
        if stored_user_id != user_id or operation != operation_prefix:
            continue
        run = state.downloads_by_id.get(download_run_id)
        if run is not None and run.status == "succeeded":
            return True
    return False


def _statistics_selected_count(selection_count: int, statistics_kind: str) -> int:
    reduction_by_kind = {"univariate": 1, "bivariate": 2, "multivariate": 3}
    return max(0, selection_count - reduction_by_kind[statistics_kind])


def _selection_row(selection: SelectionRecord) -> JsonRow:
    return {
        "selection_id": selection.selection_id,
        "project_id": selection.project_id,
        "name": selection.name,
        "member_ids": list(selection.member_ids),
    }


def _analysis_row(analysis: AnalysisRecord) -> JsonRow:
    return {
        "run_id": analysis.run_id,
        "project_id": analysis.project_id,
        "selection_id": analysis.selection_id,
        "status": analysis.status,
    }


def _require_user_row[UserOwnedRowT: UserOwnedRow](
    rows: Mapping[str, UserOwnedRowT],
    row_id: str,
    user_id: str,
) -> UserOwnedRowT:
    row = rows.get(row_id)
    if row is None or row.user_id != user_id:
        raise _http_error(status.HTTP_404_NOT_FOUND, "not_found")
    return row


def _page(items: list[JsonRow], *, limit: int, offset: int) -> list[JsonRow]:
    if limit < 1 or limit > 500:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_limit")
    if offset < 0:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_offset")
    return items[offset : offset + limit]


def _idempotent_response(
    state: HostedApiState, *, user_id: str, operation: str, idempotency_key: str | None
) -> str | None:
    if idempotency_key is None:
        return None
    return state.idempotency_refs.get((user_id, operation, idempotency_key))


def _remember_idempotency(
    state: HostedApiState,
    user_id: str,
    operation: str,
    idempotency_key: str | None,
    row_id: str,
) -> None:
    if idempotency_key is not None:
        state.idempotency_refs[(user_id, operation, idempotency_key)] = row_id


def _audit(state: HostedApiState, user_id: str, action: str) -> None:
    state.audit_events.append({"user_id": user_id, "action": action})


def _opaque_id(kind: str, value: str) -> str:
    return f"{kind}_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex}"


def _stable_hash(payload: JsonRow) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _http_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


app = create_app()
