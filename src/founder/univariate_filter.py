"""Univariate-statistics based ISIN selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from founder.paths import LakePaths
from founder.schemas import validate_rows
from founder.selection_filters import Predicate, filter_rows, selection_id
from founder.table_io import JsonRow, read_rows, write_json, write_rows


def run_univariate_filter(
    paths: LakePaths,
    predicates: Sequence[Predicate],
    *,
    name: str | None = None,
) -> dict[str, Any]:
    """Filter Gold univariate statistics by metric predicates."""
    source_rows = read_univariate_statistics(paths)
    selected_rows = filter_rows(source_rows, predicates)
    resolved_selection_id = selection_id("univariate_filter", name, predicates)
    write_univariate_selection(
        paths,
        resolved_selection_id,
        selected_rows,
        predicates=predicates,
        source_path=str(paths.gold / "univariate_statistics"),
    )
    return {
        "input_rows": len(source_rows),
        "selected_rows": len(selected_rows),
        "selection_id": resolved_selection_id,
        "selection_path": str(paths.univariate_filter_isins(resolved_selection_id)),
    }


def read_univariate_statistics(paths: LakePaths) -> list[JsonRow]:
    """Read all persisted Gold univariate statistics rows."""
    root = paths.gold / "univariate_statistics"
    if not root.exists():
        return []
    rows: list[JsonRow] = []
    for path in sorted(root.rglob("*.parquet")):
        rows.extend(read_rows(path))
    return rows


def write_univariate_selection(
    paths: LakePaths,
    selection_id_value: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    predicates: Sequence[Predicate],
    source_path: str,
) -> list[JsonRow]:
    """Write a univariate-filter selection and its manifest."""
    selection_rows = [_selection_row(selection_id_value, row) for row in rows]
    validate_rows("isin_selection", selection_rows)
    write_rows(paths.univariate_filter_isins(selection_id_value), selection_rows)
    write_json(
        paths.univariate_filter_manifest(selection_id_value),
        {
            "module": "univariate_filter",
            "selection_id": selection_id_value,
            "source_path": source_path,
            "row_count": len(selection_rows),
            "predicates": [predicate.as_text() for predicate in predicates],
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        },
    )
    write_json(
        paths.current_univariate_filter_selection(),
        {
            "selection_id": selection_id_value,
            "selection_path": str(paths.univariate_filter_isins(selection_id_value)),
            "manifest_path": str(paths.univariate_filter_manifest(selection_id_value)),
        },
    )
    return selection_rows


def selection_rows(paths: LakePaths, selection_id_value: str) -> list[JsonRow]:
    """Read a persisted selection from univariate or metadata filter outputs."""
    candidates: tuple[Path, ...] = (
        paths.univariate_filter_isins(selection_id_value),
        paths.metadata_filter_isins(selection_id_value),
    )
    for path in candidates:
        if path.exists():
            return read_rows(path)
    raise FileNotFoundError(f"selection does not exist: {selection_id_value}")


def _selection_row(selection_id_value: str, row: Mapping[str, Any]) -> JsonRow:
    return {
        "selection_id": selection_id_value,
        "isin": str(row["isin"]),
        "exchange": str(row["exchange"]),
        "code": str(row["code"]),
        "name": str(row.get("name", "")),
        "source_module": "univariate_filter",
    }
