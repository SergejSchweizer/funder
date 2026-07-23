from __future__ import annotations

from datetime import date

from camovar.hosted_readiness import (
    MANDATORY_DECISIONS,
    failed_results,
    load_readiness,
    public_hosted_mode_allowed,
    validate_readiness,
)


def test_hosted_readiness_records_cover_every_mandatory_decision() -> None:
    payload = load_readiness()
    decisions = {row["id"] for row in payload["decisions"]}

    assert decisions == set(MANDATORY_DECISIONS)
    assert not failed_results(validate_readiness(payload, today=date(2026, 7, 19)))


def test_public_hosted_mode_fails_closed_when_a_decision_is_missing() -> None:
    payload = load_readiness()
    payload["decisions"] = payload["decisions"][:-1]

    failures = failed_results(validate_readiness(payload, today=date(2026, 7, 19)))

    assert failures
    assert not public_hosted_mode_allowed(payload, today=date(2026, 7, 19))


def test_public_hosted_mode_fails_closed_for_expired_review() -> None:
    payload = load_readiness()
    payload["public_hosted_mode"] = "enabled"
    payload["decisions"][0]["expires_on"] = "2026-07-18"

    failures = failed_results(validate_readiness(payload, today=date(2026, 7, 19)))

    assert any(failure.name.endswith(".not_expired") for failure in failures)
    assert not public_hosted_mode_allowed(payload, today=date(2026, 7, 19))


def test_local_only_mode_can_remain_available_while_public_mode_is_disabled() -> None:
    payload = load_readiness()
    payload["public_hosted_mode"] = "disabled"

    assert payload["local_only_mode"] == "available"
    assert not failed_results(validate_readiness(payload, today=date(2026, 7, 19)))
