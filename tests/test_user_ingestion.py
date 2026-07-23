from __future__ import annotations

import pytest

from camovar.entitlements import InMemoryEntitlementStore
from camovar.hosted_credentials import (
    EodhdCredentialVault,
    InMemoryCredentialStore,
    KeyEncryptionKey,
)
from camovar.shared_observations import (
    MarketObservation,
    SharedMarketObservationStore,
    SharedObservationCatalog,
)
from camovar.user_ingestion import (
    ProviderCapability,
    ProviderFetchResult,
    UsageLedger,
    UserIngestionError,
    UserIngestionPlan,
    build_user_ingestion_plan,
    run_user_key_backed_ingestion,
)


class FakeProvider:
    def __init__(self, result: ProviderFetchResult | Exception) -> None:
        self.result = result
        self.keys_seen: list[str] = []
        self.plans: list[UserIngestionPlan] = []

    def fetch_observations(self, *, api_key: str, plan: UserIngestionPlan) -> ProviderFetchResult:
        self.keys_seen.append(api_key)
        self.plans.append(plan)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _vault() -> EodhdCredentialVault:
    store = InMemoryCredentialStore()
    vault = EodhdCredentialVault(
        store=store,
        key_encryption_key=KeyEncryptionKey(version="kek-v1", material=b"1" * 32),
        fingerprint_secret=b"fingerprint-secret",
    )
    vault.set_credential(
        user_id="user-a",
        credential_id="credential-a",
        provider_key="abcd-secret-token-1234",
    )
    return vault


def _observation(close: float = 100.0) -> MarketObservation:
    return MarketObservation(
        provider="eodhd",
        dataset_type="quotes",
        listing_identity="XETRA:ABC:IE0000000001",
        business_key="2026-01-01",
        payload={"date": "2026-01-01", "close": close},
    )


def test_plan_is_deterministic_capability_aware_and_gap_mode() -> None:
    capability = ProviderCapability(tier="free", max_symbols_per_run=2, supports_gap_refresh=True)
    full = build_user_ingestion_plan(
        user_id="user-a",
        credential_id="credential-a",
        dataset_type="quotes",
        listing_identities=("B", "A", "A"),
        capability=capability,
        as_of_date="2026-07-19",
    )
    gap = build_user_ingestion_plan(
        user_id="user-a",
        credential_id="credential-a",
        dataset_type="quotes",
        listing_identities=("A", "B"),
        capability=capability,
        as_of_date="2026-07-19",
        prior_snapshot=type("Snapshot", (), {"snapshot_id": "snapshot-1"})(),  # type: ignore[arg-type]
    )

    assert full.listing_identities == ("A", "B")
    assert full.mode == "full"
    assert gap.mode == "gap"
    with pytest.raises(UserIngestionError, match="symbol limit"):
        build_user_ingestion_plan(
            user_id="user-a",
            credential_id="credential-a",
            dataset_type="quotes",
            listing_identities=("A", "B", "C"),
            capability=capability,
            as_of_date="2026-07-19",
        )


def test_successful_ingestion_uses_user_key_and_publishes_snapshot(tmp_path) -> None:  # type: ignore[no-untyped-def]
    entitlement_store = InMemoryEntitlementStore()
    shared_store = SharedMarketObservationStore(root=tmp_path, catalog=SharedObservationCatalog())
    provider = FakeProvider(ProviderFetchResult(observations=(_observation(),)))
    plan = build_user_ingestion_plan(
        user_id="user-a",
        credential_id="credential-a",
        dataset_type="quotes",
        listing_identities=("XETRA:ABC:IE0000000001",),
        capability=ProviderCapability("paid", 10, True),
        as_of_date="2026-07-19",
    )

    snapshot = run_user_key_backed_ingestion(
        plan=plan,
        credential_vault=_vault(),
        provider=provider,
        shared_store=shared_store,
        entitlement_store=entitlement_store,
        usage_ledger=UsageLedger(),
    )

    assert provider.keys_seen == ["abcd-secret-token-1234"]
    assert snapshot.observation_ids
    assert entitlement_store.visible_observation_ids("user-a") == snapshot.observation_ids


def test_partial_failure_rate_limit_and_provider_error_do_not_publish(tmp_path) -> None:  # type: ignore[no-untyped-def]
    plan = build_user_ingestion_plan(
        user_id="user-a",
        credential_id="credential-a",
        dataset_type="quotes",
        listing_identities=("XETRA:ABC:IE0000000001",),
        capability=ProviderCapability("paid", 10, True),
        as_of_date="2026-07-19",
    )
    for result, match in (
        (ProviderFetchResult(observations=(_observation(),), failed_listings=("X",)), "partial"),
        (ProviderFetchResult(observations=(_observation(),), retry_after_seconds=60), "rate"),
        (RuntimeError("failed abcd-secret-token-1234"), "<redacted>"),
    ):
        entitlement_store = InMemoryEntitlementStore()
        with pytest.raises(UserIngestionError, match=match):
            run_user_key_backed_ingestion(
                plan=plan,
                credential_vault=_vault(),
                provider=FakeProvider(result),  # type: ignore[arg-type]
                shared_store=SharedMarketObservationStore(
                    root=tmp_path,
                    catalog=SharedObservationCatalog(),
                ),
                entitlement_store=entitlement_store,
                usage_ledger=UsageLedger(),
            )
        assert entitlement_store.visible_observation_ids("user-a") == ()


def test_repeated_existing_shared_objects_still_require_user_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    shared_store = SharedMarketObservationStore(root=tmp_path, catalog=SharedObservationCatalog())
    first_provider = FakeProvider(ProviderFetchResult(observations=(_observation(),)))
    second_provider = FakeProvider(ProviderFetchResult(observations=(_observation(),)))
    plan = build_user_ingestion_plan(
        user_id="user-a",
        credential_id="credential-a",
        dataset_type="quotes",
        listing_identities=("XETRA:ABC:IE0000000001",),
        capability=ProviderCapability("paid", 10, True),
        as_of_date="2026-07-19",
    )

    first = run_user_key_backed_ingestion(
        plan=plan,
        credential_vault=_vault(),
        provider=first_provider,
        shared_store=shared_store,
        entitlement_store=InMemoryEntitlementStore(),
        usage_ledger=UsageLedger(),
    )
    second = run_user_key_backed_ingestion(
        plan=plan,
        credential_vault=_vault(),
        provider=second_provider,
        shared_store=shared_store,
        entitlement_store=InMemoryEntitlementStore(),
        usage_ledger=UsageLedger(),
    )

    assert first.observation_ids == second.observation_ids
    assert first_provider.keys_seen == ["abcd-secret-token-1234"]
    assert second_provider.keys_seen == ["abcd-secret-token-1234"]
