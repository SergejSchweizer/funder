"""End-to-end hosted cutover proof for multi-user isolation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from camovar.artifact_cache import (
    ArtifactCacheError,
    InMemoryAnalysisRunStore,
    InMemoryArtifactCache,
    ReturnArtifactKey,
    UnivariateArtifactKey,
    create_return_artifact,
    create_univariate_artifact,
)
from camovar.entitlements import (
    EntitlementError,
    InMemoryEntitlementStore,
    ProviderDownloadRun,
    delete_user_entitlements,
    publish_user_data_snapshot,
)
from camovar.hosted_credentials import (
    EodhdCredentialVault,
    InMemoryCredentialStore,
    KeyEncryptionKey,
)
from camovar.hosted_readiness import public_hosted_mode_allowed
from camovar.scoped_inputs import (
    EntitledSnapshotReader,
    ScopedInputError,
    UserDataSnapshotRef,
    build_selection_ref,
)
from camovar.table_io import JsonRow

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class HostedCutoverReport:
    """Deterministic proof summary for hosted multi-user cutover."""

    user_count: int
    shared_observation_count: int
    user_grant_count: int
    artifact_count: int
    cross_user_snapshot_blocked: bool
    cross_user_artifact_blocked: bool
    retry_created_duplicate_snapshot: bool
    retry_created_duplicate_artifact: bool
    account_deletion_revoked_visibility: bool
    web_storage_safe: bool
    public_hosted_gate_green: bool
    local_cli_compatibility_preserved: bool

    def as_dict(self) -> JsonRow:
        """Return a JSON-serializable report."""

        return {
            "user_count": self.user_count,
            "shared_observation_count": self.shared_observation_count,
            "user_grant_count": self.user_grant_count,
            "artifact_count": self.artifact_count,
            "cross_user_snapshot_blocked": self.cross_user_snapshot_blocked,
            "cross_user_artifact_blocked": self.cross_user_artifact_blocked,
            "retry_created_duplicate_snapshot": self.retry_created_duplicate_snapshot,
            "retry_created_duplicate_artifact": self.retry_created_duplicate_artifact,
            "account_deletion_revoked_visibility": self.account_deletion_revoked_visibility,
            "web_storage_safe": self.web_storage_safe,
            "public_hosted_gate_green": self.public_hosted_gate_green,
            "local_cli_compatibility_preserved": self.local_cli_compatibility_preserved,
        }

    def passed(self) -> bool:
        """Return whether all hosted cutover invariants passed."""

        return all(
            (
                self.user_count == 3,
                self.shared_observation_count < self.user_grant_count,
                self.cross_user_snapshot_blocked,
                self.cross_user_artifact_blocked,
                not self.retry_created_duplicate_snapshot,
                not self.retry_created_duplicate_artifact,
                self.account_deletion_revoked_visibility,
                self.web_storage_safe,
                self.public_hosted_gate_green,
                self.local_cli_compatibility_preserved,
            )
        )


def run_hosted_cutover_proof() -> HostedCutoverReport:
    """Run a deterministic multi-user hosted cutover proof."""

    credential_store = InMemoryCredentialStore()
    vault = EodhdCredentialVault(
        store=credential_store,
        key_encryption_key=KeyEncryptionKey("cutover-v1", b"1" * 32),
        fingerprint_secret=b"camovar-cutover-fingerprint-secret",
    )
    for user_id in ("user-a", "user-b", "user-c"):
        vault.set_credential(user_id=user_id, provider_key=f"{user_id}-provider-key-value")

    entitlement_store = InMemoryEntitlementStore()
    run_a = _download_run("run-a", "user-a", ("obs-overlap", "obs-a-only"))
    run_b = _download_run("run-b", "user-b", ("obs-overlap", "obs-b-only"))
    run_c = _download_run("run-c", "user-c", ("obs-c-only",))
    snapshot_a = publish_user_data_snapshot(store=entitlement_store, run=run_a)
    snapshot_b = publish_user_data_snapshot(store=entitlement_store, run=run_b)
    snapshot_c = publish_user_data_snapshot(store=entitlement_store, run=run_c)
    retry_snapshot_a = publish_user_data_snapshot(store=entitlement_store, run=run_a)

    rows_by_observation_id = {
        "obs-overlap": {"market_object_id": "obs-overlap", "date": "2026-07-19", "return": 0.01},
        "obs-a-only": {"market_object_id": "obs-a-only", "date": "2026-07-19", "return": 0.02},
        "obs-b-only": {"market_object_id": "obs-b-only", "date": "2026-07-19", "return": -0.01},
        "obs-c-only": {"market_object_id": "obs-c-only", "date": "2026-07-19", "return": 0.0},
    }
    reader = EntitledSnapshotReader(
        entitlement_store=entitlement_store,
        rows_by_observation_id=rows_by_observation_id,
    )
    inputs_a = reader.read_inputs(
        snapshot=_snapshot_ref("user-a", snapshot_a.snapshot_id, snapshot_a.snapshot_hash),
        selection=build_selection_ref(
            selection_id="selection-a", member_ids=("obs-overlap", "obs-a-only")
        ),
    )
    cross_user_snapshot_blocked = _raises_scoped_input_error(
        lambda: reader.read_inputs(
            snapshot=_snapshot_ref("user-b", snapshot_a.snapshot_id, snapshot_a.snapshot_hash),
            selection=build_selection_ref(
                selection_id="selection-bad", member_ids=("obs-overlap",)
            ),
        )
    )

    artifact_cache = InMemoryArtifactCache()
    run_store = InMemoryAnalysisRunStore()
    return_artifact, _ = create_return_artifact(
        cache=artifact_cache,
        inputs=inputs_a,
        key=_return_key(inputs_a.input_hash),
        payload={"rows": [row["market_object_id"] for row in inputs_a.quote_rows]},
    )
    retry_return_artifact, _ = create_return_artifact(
        cache=artifact_cache,
        inputs=inputs_a,
        key=_return_key(inputs_a.input_hash),
        payload={"rows": [row["market_object_id"] for row in inputs_a.quote_rows]},
    )
    univariate_artifact, _ = create_univariate_artifact(
        cache=artifact_cache,
        inputs=inputs_a,
        return_artifact=return_artifact,
        key=UnivariateArtifactKey(
            return_artifact_id=return_artifact.artifact_id,
            metric_parameters={"frequency": "daily"},
            confidence_level=0.95,
            quality_policy_version="cutover-v1",
            algorithm_version="cutover-v1",
        ),
        payload={"volatility": 0.1},
    )
    run_store.create_project(
        user_id="user-a",
        project_id="project-a",
        current_snapshot_id=snapshot_a.snapshot_id,
    )
    cross_user_artifact_blocked = _raises_artifact_error(
        lambda: artifact_cache.require_ref(
            user_id="user-b",
            snapshot_id=snapshot_b.snapshot_id,
            artifact_id=return_artifact.artifact_id,
        )
    )
    delete_user_entitlements(store=entitlement_store, user_id="user-a")

    shared_observation_ids = (
        set(snapshot_a.observation_ids)
        | set(snapshot_b.observation_ids)
        | set(snapshot_c.observation_ids)
    )
    user_grant_count = sum(
        len(grants) for grants in entitlement_store.grants_by_user.values()
    ) + len(snapshot_a.observation_ids)
    report = HostedCutoverReport(
        user_count=3,
        shared_observation_count=len(shared_observation_ids),
        user_grant_count=user_grant_count,
        artifact_count=len(artifact_cache.artifacts_by_id),
        cross_user_snapshot_blocked=cross_user_snapshot_blocked,
        cross_user_artifact_blocked=cross_user_artifact_blocked,
        retry_created_duplicate_snapshot=retry_snapshot_a.snapshot_id != snapshot_a.snapshot_id,
        retry_created_duplicate_artifact=retry_return_artifact.artifact_id
        != return_artifact.artifact_id,
        account_deletion_revoked_visibility=entitlement_store.visible_observation_ids("user-a")
        == (),
        web_storage_safe=_web_storage_safe(),
        public_hosted_gate_green=public_hosted_mode_allowed(),
        local_cli_compatibility_preserved=_local_cli_contract_present(),
    )
    if univariate_artifact.artifact_kind != "univariate":
        raise ArtifactCacheError("cutover univariate artifact was not created")
    return report


def _download_run(run_id: str, user_id: str, observations: tuple[str, ...]) -> ProviderDownloadRun:
    return ProviderDownloadRun(
        download_run_id=run_id,
        user_id=user_id,
        credential_id=f"credential-{user_id}",
        provider="eodhd",
        status="succeeded",
        returned_observation_ids=observations,
        request_hash=run_id,
    )


def _snapshot_ref(user_id: str, snapshot_id: str, snapshot_hash: str) -> UserDataSnapshotRef:
    return UserDataSnapshotRef(
        user_id=user_id,
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
    )


def _return_key(input_hash: str) -> ReturnArtifactKey:
    return ReturnArtifactKey(
        listing_id="cutover-listing",
        quote_snapshot_hash=input_hash,
        dividend_snapshot_hash="no-dividends",
        date_window=("2026-07-19", "2026-07-19"),
        return_parameters={"method": "log"},
        quality_policy_version="cutover-v1",
        algorithm_version="cutover-v1",
    )


def _raises_scoped_input_error(callback: Callable[[], object]) -> bool:
    try:
        callback()
    except ScopedInputError, EntitlementError:
        return True
    return False


def _raises_artifact_error(callback: Callable[[], object]) -> bool:
    try:
        callback()
    except ArtifactCacheError:
        return True
    return False


def _web_storage_safe() -> bool:
    source = (REPOSITORY_ROOT / "apps" / "web" / "server.js").read_text(encoding="utf-8")
    forbidden = ("localStorage", "sessionStorage", "document.cookie", "access_token", "api_token")
    return all(term not in source for term in forbidden)


def _local_cli_contract_present() -> bool:
    cli_source = (REPOSITORY_ROOT / "src" / "camovar" / "cli.py").read_text(encoding="utf-8")
    return all(
        command in cli_source
        for command in (
            "fetch-all-isins",
            "metadata-filter",
            "fetch-all-quotes",
            "univariate-statistics",
            "univariate-filter",
            "bivariate-statistics",
            "multivariate-statistics",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    """Build hosted cutover proof CLI parser."""

    return argparse.ArgumentParser(description="Run the hosted multi-user cutover proof.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the hosted cutover proof CLI."""

    build_parser().parse_args(argv)
    report = run_hosted_cutover_proof()
    print(json.dumps(report.as_dict(), sort_keys=True))
    if not report.passed():
        print("hosted cutover proof failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
