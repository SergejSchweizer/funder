"""Hosted readiness decision gates for public Camovar deployment."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
READINESS_PATH = REPOSITORY_ROOT / "docs" / "security" / "hosted_readiness.json"

MANDATORY_DECISIONS: tuple[str, ...] = (
    "eodhd-storage-and-derived-display-rights",
    "personal-license-boundary",
    "shared-physical-deduplication",
    "user-key-backed-grants",
    "retention-and-account-deletion",
    "gdpr-rights-and-country-coverage",
    "audit-retention-and-incident-response",
    "encrypted-backups-and-restore-drills",
    "kek-recovery-and-rotation",
    "session-key-rotation",
    "database-role-review",
    "no-automatic-broker-execution",
)


@dataclass(frozen=True)
class ReadinessResult:
    """Result for one hosted readiness decision or invariant."""

    name: str
    passed: bool
    message: str


def load_readiness(path: Path = READINESS_PATH) -> dict[str, Any]:
    """Load hosted readiness evidence records."""

    with path.open(encoding="utf-8") as readiness_file:
        payload = cast(object, json.load(readiness_file))
    if not isinstance(payload, dict):
        raise ValueError("hosted readiness must be a JSON object")
    return cast(dict[str, Any], payload)


def validate_readiness(
    payload: dict[str, Any] | None = None,
    *,
    today: date | None = None,
) -> list[ReadinessResult]:
    """Validate public-hosted readiness records without mutating production state."""

    resolved = payload or load_readiness()
    resolved_today = today or date.today()
    results: list[ReadinessResult] = []
    decisions = _decision_map(resolved)
    for decision_id in MANDATORY_DECISIONS:
        decision = decisions.get(decision_id)
        results.extend(_validate_decision(decision_id, decision, today=resolved_today))
    results.extend(_validate_mode(resolved, decisions))
    return results


def public_hosted_mode_allowed(
    payload: dict[str, Any] | None = None,
    *,
    today: date | None = None,
) -> bool:
    """Return whether public-hosted mode can be enabled."""

    return not failed_results(validate_readiness(payload, today=today))


def failed_results(results: Iterable[ReadinessResult]) -> list[ReadinessResult]:
    """Return failed readiness results in deterministic order."""

    return [result for result in results if not result.passed]


def _decision_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_decisions = cast(object, payload.get("decisions", []))
    if not isinstance(raw_decisions, list):
        raise ValueError("decisions must be a list")
    decisions: dict[str, dict[str, Any]] = {}
    for raw_decision in cast(list[object], raw_decisions):
        if not isinstance(raw_decision, dict):
            raise ValueError("decision rows must be objects")
        decision = cast(dict[str, Any], raw_decision)
        decision_id = decision.get("id")
        if not isinstance(decision_id, str):
            raise ValueError("decision id must be a string")
        decisions[decision_id] = decision
    return decisions


def _validate_decision(
    decision_id: str,
    decision: dict[str, Any] | None,
    *,
    today: date,
) -> list[ReadinessResult]:
    if decision is None:
        return [
            ReadinessResult(
                name=f"decision.{decision_id}.present",
                passed=False,
                message="mandatory decision is missing",
            )
        ]
    status = decision.get("status")
    reviewed_on = decision.get("reviewed_on")
    expires_on = decision.get("expires_on")
    evidence = decision.get("evidence")
    owner = decision.get("owner")
    results = [
        ReadinessResult(
            name=f"decision.{decision_id}.approved",
            passed=status == "approved",
            message="mandatory decision must be approved",
        ),
        ReadinessResult(
            name=f"decision.{decision_id}.owner",
            passed=isinstance(owner, str) and bool(owner),
            message="mandatory decision must have an owner",
        ),
        ReadinessResult(
            name=f"decision.{decision_id}.evidence",
            passed=isinstance(evidence, str) and bool(evidence),
            message="mandatory decision must link evidence",
        ),
        ReadinessResult(
            name=f"decision.{decision_id}.reviewed_on",
            passed=_is_iso_date(reviewed_on),
            message="mandatory decision must have an ISO reviewed_on date",
        ),
        ReadinessResult(
            name=f"decision.{decision_id}.not_expired",
            passed=_is_future_or_today(expires_on, today=today),
            message="mandatory decision must not be expired",
        ),
    ]
    return results


def _validate_mode(
    payload: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
) -> list[ReadinessResult]:
    public_hosted_enabled = payload.get("public_hosted_mode") == "enabled"
    approved = all(
        decisions.get(decision_id, {}).get("status") == "approved"
        for decision_id in MANDATORY_DECISIONS
    )
    local_mode = payload.get("local_only_mode") == "available"
    backup_contract = payload.get("backup_contract")
    key_contract = payload.get("key_contract")
    return [
        ReadinessResult(
            name="mode.local_only_available",
            passed=local_mode,
            message="local-only mode must remain available while hosted readiness is blocked",
        ),
        ReadinessResult(
            name="mode.public_enabled_only_when_approved",
            passed=not public_hosted_enabled or approved,
            message=(
                "public-hosted mode cannot be enabled until every mandatory decision is approved"
            ),
        ),
        ReadinessResult(
            name="backup.encrypted_and_separate",
            passed=backup_contract == "encrypted-separate-from-kek",
            message=(
                "database/shared-store backups must be encrypted and stored separately "
                "from KEK recovery material"
            ),
        ),
        ReadinessResult(
            name="keys.restore_fails_closed",
            passed=key_contract == "restore-requires-kek-version",
            message="restore procedures must fail closed without the required KEK version",
        ),
    ]


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_future_or_today(value: object, *, today: date) -> bool:
    if not _is_iso_date(value):
        return False
    return date.fromisoformat(cast(str, value)) >= today


def build_parser() -> argparse.ArgumentParser:
    """Build the hosted readiness CLI parser."""

    parser = argparse.ArgumentParser(description="Validate hosted deployment readiness.")
    parser.add_argument(
        "--require-public-hosted",
        action="store_true",
        help="Fail unless public-hosted mode is fully approved.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run hosted readiness checks."""

    args = build_parser().parse_args(argv)
    results = validate_readiness()
    failures = failed_results(results)
    if args.require_public_hosted and failures:
        for failure in failures:
            print(f"{failure.name}: {failure.message}", file=sys.stderr)
        return 1
    if failures:
        print("public-hosted mode is blocked; local-only mode remains available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
