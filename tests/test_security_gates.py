from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from camovar.security_gates import (
    SECURITY_POLICY_PATH,
    failed_results,
    load_security_policy,
    validate_gitignore,
    validate_repository_security,
    validate_secret_text,
    validate_security_policy,
    validate_workflow_security,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_security_policy_is_versioned_and_detects_synthetic_secrets() -> None:
    policy = load_security_policy()

    assert policy["schema_version"] == 1
    assert not failed_results(validate_security_policy(policy))
    fixtures = cast(object, policy["synthetic_secret_fixtures"])
    assert isinstance(fixtures, dict)
    for fixture in cast(dict[object, object], fixtures).values():
        assert isinstance(fixture, str)
        assert validate_secret_text(fixture, policy=policy)


def test_benign_security_text_does_not_trigger_secret_scanner() -> None:
    assert validate_secret_text("provider key is loaded from an external file") == []


def test_workflows_are_sha_pinned_least_privilege_and_fork_safe() -> None:
    failures = failed_results(validate_workflow_security())

    assert failures == []
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml"))
    )
    assert "pull_request_target" not in rendered
    assert re.search(r"uses:\s*actions/checkout@[0-9a-f]{40}", rendered)
    assert re.search(r"uses:\s*astral-sh/setup-uv@[0-9a-f]{40}", rendered)


def test_gitignore_keeps_secret_and_runtime_artifacts_out_of_git() -> None:
    assert not failed_results(validate_gitignore())


def test_repository_security_gate_passes_current_source() -> None:
    assert SECURITY_POLICY_PATH.exists()
    assert not failed_results(validate_repository_security())
