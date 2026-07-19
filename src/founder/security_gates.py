"""Security and supply-chain policy checks for hosted Founder."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SECURITY_POLICY_PATH = REPOSITORY_ROOT / "docs" / "security" / "hosted_security_policy.json"
WORKFLOW_ROOT = REPOSITORY_ROOT / ".github" / "workflows"
GITIGNORE_PATH = REPOSITORY_ROOT / ".gitignore"

ACTION_REF_PATTERN = re.compile(r"uses:\s*[^@\s]+@(?P<ref>[^\s#]+)")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PROHIBITED_TRIGGER_PATTERN = re.compile(r"^\s*pull_request_target\s*:", re.MULTILINE)
PERMISSIONS_PATTERN = re.compile(
    r"^permissions:\s*\n(?P<body>(?:\s{2}[a-z-]+:\s+[a-z-]+\s*\n)+)", re.MULTILINE
)


@dataclass(frozen=True)
class SecurityGateResult:
    """Result for one security gate validation."""

    name: str
    passed: bool
    message: str


SecurityPolicy = dict[str, Any]


def load_security_policy(path: Path = SECURITY_POLICY_PATH) -> SecurityPolicy:
    """Load the hosted security policy JSON document."""

    with path.open(encoding="utf-8") as policy_file:
        policy = cast(object, json.load(policy_file))
    if not isinstance(policy, dict):
        raise ValueError("security policy must be a JSON object")
    return cast(SecurityPolicy, policy)


def validate_secret_text(text: str, *, policy: SecurityPolicy | None = None) -> list[str]:
    """Return policy names whose secret patterns are present in text."""

    resolved_policy = policy or load_security_policy()
    patterns = cast(object, resolved_policy.get("secret_patterns", []))
    findings: list[str] = []
    if not isinstance(patterns, list):
        raise ValueError("secret_patterns must be a list")
    for pattern_row in cast(list[object], patterns):
        if not isinstance(pattern_row, dict):
            raise ValueError("secret pattern rows must be objects")
        row = cast(dict[str, object], pattern_row)
        name = row.get("name")
        pattern = row.get("pattern")
        if not isinstance(name, str) or not isinstance(pattern, str):
            raise ValueError("secret pattern rows require string name and pattern")
        if re.search(pattern, text):
            findings.append(name)
    return findings


def validate_security_policy(policy: SecurityPolicy | None = None) -> list[SecurityGateResult]:
    """Validate the hosted security policy shape and mandatory decisions."""

    resolved_policy = policy or load_security_policy()
    results: list[SecurityGateResult] = []
    mandatory_lists = (
        "secret_patterns",
        "forbidden_paths",
        "required_workflow_permissions",
        "required_scanners",
        "protected_secret_names",
    )
    for key in mandatory_lists:
        value = cast(object, resolved_policy.get(key))
        results.append(
            SecurityGateResult(
                name=f"policy.{key}",
                passed=isinstance(value, list) and bool(cast(list[object], value)),
                message=f"{key} must be a non-empty list",
            )
        )
    synthetic = cast(object, resolved_policy.get("synthetic_secret_fixtures", {}))
    synthetic_passed = isinstance(synthetic, dict) and all(
        isinstance(value, str) and validate_secret_text(value, policy=resolved_policy)
        for value in cast(dict[object, object], synthetic).values()
    )
    results.append(
        SecurityGateResult(
            name="policy.synthetic_secret_fixtures",
            passed=synthetic_passed,
            message="synthetic secret fixtures must trigger at least one configured detector",
        )
    )
    return results


def validate_workflow_security(workflow_root: Path = WORKFLOW_ROOT) -> list[SecurityGateResult]:
    """Validate GitHub workflow hardening rules."""

    results: list[SecurityGateResult] = []
    workflow_paths = sorted(workflow_root.glob("*.yml"))
    results.append(
        SecurityGateResult(
            name="workflow.exists",
            passed=bool(workflow_paths),
            message="at least one GitHub workflow must exist",
        )
    )
    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        results.append(
            SecurityGateResult(
                name=f"workflow.{path.name}.no_pull_request_target",
                passed=PROHIBITED_TRIGGER_PATTERN.search(text) is None,
                message=f"{path.name} must not use pull_request_target",
            )
        )
        permission_match = PERMISSIONS_PATTERN.search(text)
        results.append(
            SecurityGateResult(
                name=f"workflow.{path.name}.permissions",
                passed=permission_match is not None,
                message=f"{path.name} must declare top-level permissions",
            )
        )
        for action_ref in ACTION_REF_PATTERN.finditer(text):
            ref = action_ref.group("ref")
            results.append(
                SecurityGateResult(
                    name=f"workflow.{path.name}.action_pin",
                    passed=bool(FULL_SHA_PATTERN.fullmatch(ref)),
                    message=f"{path.name} action ref {ref!r} must be a full commit SHA",
                )
            )
    return results


def validate_gitignore(gitignore_path: Path = GITIGNORE_PATH) -> list[SecurityGateResult]:
    """Validate deny-by-default ignore rules for runtime data and secret-like files."""

    lines = {
        line.strip()
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    required_rules = {
        "*",
        ".env",
        ".env.*",
        "lake/",
        "data/",
        ".logs/",
        "*.duckdb",
        "*.duckdb.wal",
        "__pycache__/",
        "*.py[cod]",
    }
    return [
        SecurityGateResult(
            name=f"gitignore.{rule}",
            passed=rule in lines,
            message=f".gitignore must keep {rule} ignored",
        )
        for rule in sorted(required_rules)
    ]


def validate_repository_security() -> list[SecurityGateResult]:
    """Run all public-repository security hardening checks."""

    policy = load_security_policy()
    return [
        *validate_security_policy(policy),
        *validate_workflow_security(),
        *validate_gitignore(),
    ]


def failed_results(results: Iterable[SecurityGateResult]) -> list[SecurityGateResult]:
    """Return failed gate results in deterministic order."""

    return [result for result in results if not result.passed]


def build_parser() -> argparse.ArgumentParser:
    """Build the security gate CLI parser."""

    parser = argparse.ArgumentParser(description="Validate hosted security gates.")
    parser.add_argument(
        "--scan-text",
        help="Scan one text value for configured secret patterns.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the security gate CLI."""

    args = build_parser().parse_args(argv)
    if args.scan_text is not None:
        findings = validate_secret_text(args.scan_text)
        for finding in findings:
            print(finding)
        return 1 if findings else 0

    failures = failed_results(validate_repository_security())
    for failure in failures:
        print(f"{failure.name}: {failure.message}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
