"""Read-only architecture boundary checks for Founder."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "founder"

INGESTION_MODULES = {
    "founder.bronze",
    "founder.silver",
    "founder.search",
    "founder.cli",
    "founder.config",
    "founder.http",
}
SHARED_MODULES = {
    "founder.schemas",
    "founder.paths",
    "founder.table_io",
    "founder.run_state",
    "founder.run_locks",
    "founder.logging",
}
LAYER_HEAVY_MODULES = {
    "founder.bronze",
    "founder.silver",
    "founder.gold",
    "founder.evaluation",
    "founder.portfolio",
    "founder.search",
    "founder.cli",
}


def check_architecture(root: Path = SRC_ROOT) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        module_name = _module_name(path, root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = list(_imports(tree))
        imported_from = {module for module, _name in imports}

        if module_name.startswith("founder.evaluation_parts"):
            if "founder.evaluation" in imported_from:
                violations.append(f"{module_name} must not import founder.evaluation facade")
            forbidden = sorted(imported_from & INGESTION_MODULES)
            if forbidden:
                violations.append(
                    f"{module_name} imports ingestion modules: {', '.join(forbidden)}"
                )
        if (
            module_name.startswith("founder.portfolio_parts")
            and "founder.portfolio" in imported_from
        ):
            violations.append(f"{module_name} must not import founder.portfolio facade")
        if module_name.startswith("founder.evaluation"):
            forbidden = sorted(imported_from & INGESTION_MODULES)
            if forbidden:
                violations.append(
                    f"{module_name} imports ingestion modules: {', '.join(forbidden)}"
                )
        if module_name == "founder.silver":
            private_bronze = sorted(
                name
                for module, name in imports
                if module == "founder.bronze" and name.startswith("_")
            )
            if private_bronze:
                violations.append(
                    f"{module_name} imports private Bronze helpers: {', '.join(private_bronze)}"
                )
        if module_name != "founder.cli" and "founder.cli" in imported_from:
            violations.append(f"{module_name} must not import founder.cli")
        if module_name in SHARED_MODULES:
            forbidden = sorted(imported_from & LAYER_HEAVY_MODULES)
            if forbidden:
                violations.append(
                    f"{module_name} shared module imports layer modules: {', '.join(forbidden)}"
                )
        if module_name in {
            "founder.portfolio_parts.constraints",
            "founder.portfolio_parts.risk_parity",
        }:
            forbidden = sorted(imported_from & {"founder.paths", "founder.table_io"})
            if forbidden:
                violations.append(
                    f"{module_name} core math imports lake IO modules: {', '.join(forbidden)}"
                )
    return violations


def main() -> int:
    violations = check_architecture()
    if not violations:
        return 0
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    if relative.name == "__init__":
        relative = relative.parent
    parts = [part for part in relative.parts if part]
    return ".".join(("founder", *parts))


def _imports(tree: ast.AST) -> list[tuple[str, str]]:
    imports: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                (alias.name, alias.name.rsplit(".", maxsplit=1)[-1]) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.extend((node.module, alias.name) for alias in node.names)
    return imports


if __name__ == "__main__":
    raise SystemExit(main())
