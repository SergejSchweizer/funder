"""Read-only architecture boundary checks for Camovar."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "camovar"

INGESTION_MODULES = {
    "camovar.bronze",
    "camovar.silver",
    "camovar.search",
    "camovar.cli",
    "camovar.config",
    "camovar.http",
}
SHARED_MODULES = {
    "camovar.schemas",
    "camovar.paths",
    "camovar.table_io",
    "camovar.run_state",
    "camovar.run_locks",
    "camovar.logging",
}
LAYER_HEAVY_MODULES = {
    "camovar.bronze",
    "camovar.silver",
    "camovar.gold",
    "camovar.evaluation",
    "camovar.portfolio",
    "camovar.search",
    "camovar.cli",
}


def check_architecture(root: Path = SRC_ROOT) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        module_name = _module_name(path, root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = list(_imports(tree))
        imported_from = {module for module, _name in imports}

        if module_name.startswith("camovar.evaluation_parts"):
            if "camovar.evaluation" in imported_from:
                violations.append(f"{module_name} must not import camovar.evaluation facade")
            forbidden = sorted(imported_from & INGESTION_MODULES)
            if forbidden:
                violations.append(
                    f"{module_name} imports ingestion modules: {', '.join(forbidden)}"
                )
        if (
            module_name.startswith("camovar.portfolio_parts")
            and "camovar.portfolio" in imported_from
        ):
            violations.append(f"{module_name} must not import camovar.portfolio facade")
        if module_name.startswith("camovar.evaluation"):
            forbidden = sorted(imported_from & INGESTION_MODULES)
            if forbidden:
                violations.append(
                    f"{module_name} imports ingestion modules: {', '.join(forbidden)}"
                )
        if module_name == "camovar.silver":
            private_bronze = sorted(
                name
                for module, name in imports
                if module == "camovar.bronze" and name.startswith("_")
            )
            if private_bronze:
                violations.append(
                    f"{module_name} imports private Bronze helpers: {', '.join(private_bronze)}"
                )
        if module_name != "camovar.cli" and "camovar.cli" in imported_from:
            violations.append(f"{module_name} must not import camovar.cli")
        if module_name in SHARED_MODULES:
            forbidden = sorted(imported_from & LAYER_HEAVY_MODULES)
            if forbidden:
                violations.append(
                    f"{module_name} shared module imports layer modules: {', '.join(forbidden)}"
                )
        if module_name in {
            "camovar.portfolio_parts.constraints",
            "camovar.portfolio_parts.risk_parity",
        }:
            forbidden = sorted(imported_from & {"camovar.paths", "camovar.table_io"})
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
    return ".".join(("camovar", *parts))


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
