from __future__ import annotations

import json

import pytest

from camovar.hosted_cutover import main, run_hosted_cutover_proof


def test_hosted_cutover_proof_passes_all_required_invariants() -> None:
    report = run_hosted_cutover_proof()

    assert report.passed()
    assert report.user_count == 3
    assert report.shared_observation_count < report.user_grant_count
    assert report.cross_user_snapshot_blocked
    assert report.cross_user_artifact_blocked
    assert not report.retry_created_duplicate_snapshot
    assert not report.retry_created_duplicate_artifact
    assert report.account_deletion_revoked_visibility
    assert report.web_storage_safe
    assert report.public_hosted_gate_green
    assert report.local_cli_compatibility_preserved


def test_hosted_cutover_report_is_json_serializable_and_stable() -> None:
    report = run_hosted_cutover_proof()
    rendered = json.dumps(report.as_dict(), sort_keys=True)

    assert '"cross_user_artifact_blocked": true' in rendered
    assert '"retry_created_duplicate_artifact": false' in rendered
    assert json.loads(rendered) == report.as_dict()


def test_hosted_cutover_cli_outputs_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(()) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["user_count"] == 3
    assert payload["cross_user_snapshot_blocked"] is True
