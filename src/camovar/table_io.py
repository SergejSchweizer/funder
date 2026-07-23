"""Small deterministic table helpers for local lake artifacts."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

JsonRow = dict[str, Any]


class _ArrowTable(Protocol):
    def to_pylist(self) -> list[object]: ...


class _ArrowTableFactory(Protocol):
    def from_pylist(self, rows: list[JsonRow]) -> object: ...


class _PyArrowModule(Protocol):
    Table: _ArrowTableFactory


class _ParquetModule(Protocol):
    def write_table(self, table: object, where: Path) -> None: ...

    def read_table(self, source: Path) -> _ArrowTable: ...


_ARROW = cast(_PyArrowModule, pa)
_PARQUET = cast(_ParquetModule, pq)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> JsonRow:
    data = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return cast(JsonRow, data)


def write_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        table = _ARROW.Table.from_pylist([dict(row) for row in rows])
        _PARQUET.write_table(table, path)
        return
    content = "".join(json.dumps(dict(row), sort_keys=True) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")


def read_rows(path: Path) -> list[JsonRow]:
    rows: list[JsonRow] = []
    if not path.exists():
        return rows
    if path.suffix == ".parquet":
        for row in _PARQUET.read_table(path).to_pylist():
            if not isinstance(row, dict):
                raise ValueError(f"expected Parquet object row in {path}")
            rows.append(cast(JsonRow, row))
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = cast(object, json.loads(line))
        if not isinstance(data, dict):
            raise ValueError(f"expected JSON object row in {path}")
        rows.append(cast(JsonRow, data))
    return rows


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
