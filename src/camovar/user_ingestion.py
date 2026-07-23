"""User-key-backed EODHD ingestion planning for hosted mode."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from camovar.entitlements import (
    InMemoryEntitlementStore,
    ProviderDownloadRun,
    UserDataSnapshot,
    publish_user_data_snapshot,
)
from camovar.hosted_credentials import EodhdCredentialVault, redact_credential_text
from camovar.shared_observations import (
    MarketObservation,
    SharedMarketObservationStore,
)


class UserIngestionError(RuntimeError):
    """Raised when user-scoped provider ingestion fails closed."""


class EodhdProvider(Protocol):
    """Provider boundary that receives plaintext keys only at request time."""

    def fetch_observations(
        self,
        *,
        api_key: str,
        plan: UserIngestionPlan,
    ) -> ProviderFetchResult:
        """Fetch provider observations for a resolved user ingestion plan."""
        ...


@dataclass(frozen=True)
class ProviderCapability:
    """User credential capability classification."""

    tier: str
    max_symbols_per_run: int
    supports_gap_refresh: bool


@dataclass(frozen=True)
class UserIngestionPlan:
    """Deterministic user-scoped provider request plan."""

    user_id: str
    credential_id: str
    provider: str
    dataset_type: str
    listing_identities: tuple[str, ...]
    mode: str
    as_of_date: str
    request_hash: str


@dataclass(frozen=True)
class ProviderFetchResult:
    """Provider response normalized before shared publication."""

    observations: tuple[MarketObservation, ...]
    failed_listings: tuple[str, ...] = ()
    retry_after_seconds: int | None = None


@dataclass
class UsageLedger:
    """Simple per-user usage ledger for hosted ingestion tests."""

    requests_by_user: dict[str, int] = field(default_factory=lambda: dict[str, int]())

    def record(self, user_id: str, request_count: int) -> None:
        """Record provider request usage."""

        self.requests_by_user[user_id] = self.requests_by_user.get(user_id, 0) + request_count


def build_user_ingestion_plan(
    *,
    user_id: str,
    credential_id: str,
    dataset_type: str,
    listing_identities: tuple[str, ...],
    capability: ProviderCapability,
    as_of_date: str,
    prior_snapshot: UserDataSnapshot | None = None,
) -> UserIngestionPlan:
    """Build a deterministic user-scoped full or gap-aware request plan."""

    if not listing_identities:
        raise UserIngestionError("listing identities are required")
    normalized = tuple(sorted(set(listing_identities)))
    if len(normalized) > capability.max_symbols_per_run:
        raise UserIngestionError("provider capability symbol limit exceeded")
    mode = "gap" if capability.supports_gap_refresh and prior_snapshot is not None else "full"
    request_payload = {
        "user_id": user_id,
        "credential_id": credential_id,
        "provider": "eodhd",
        "dataset_type": dataset_type,
        "listing_identities": list(normalized),
        "mode": mode,
        "as_of_date": as_of_date,
        "prior_snapshot_id": None if prior_snapshot is None else prior_snapshot.snapshot_id,
    }
    return UserIngestionPlan(
        user_id=user_id,
        credential_id=credential_id,
        provider="eodhd",
        dataset_type=dataset_type,
        listing_identities=normalized,
        mode=mode,
        as_of_date=as_of_date,
        request_hash=_stable_hash(request_payload),
    )


def run_user_key_backed_ingestion(
    *,
    plan: UserIngestionPlan,
    credential_vault: EodhdCredentialVault,
    provider: EodhdProvider,
    shared_store: SharedMarketObservationStore,
    entitlement_store: InMemoryEntitlementStore,
    usage_ledger: UsageLedger,
) -> UserDataSnapshot:
    """Execute a user-key-backed provider request and publish entitlements atomically."""

    provider_key = credential_vault.unwrap_for_provider_call(user_id=plan.user_id)
    try:
        result = provider.fetch_observations(api_key=provider_key, plan=plan)
    except Exception as error:
        message = redact_credential_text(str(error), provider_key=provider_key)
        raise UserIngestionError(message) from error
    if result.retry_after_seconds is not None:
        raise UserIngestionError("provider rate limited request")
    if result.failed_listings:
        raise UserIngestionError("partial provider response cannot publish grants")
    if not result.observations:
        raise UserIngestionError("provider returned no observations")

    manifest = shared_store.publish_segment(
        provider=plan.provider,
        dataset_type=plan.dataset_type,
        observations=list(result.observations),
    )
    usage_ledger.record(plan.user_id, 1)
    run = ProviderDownloadRun(
        download_run_id=f"download-{plan.request_hash}",
        user_id=plan.user_id,
        credential_id=plan.credential_id,
        provider=plan.provider,
        status="succeeded",
        returned_observation_ids=manifest.observation_ids,
        request_hash=plan.request_hash,
    )
    return publish_user_data_snapshot(store=entitlement_store, run=run)


def _stable_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
