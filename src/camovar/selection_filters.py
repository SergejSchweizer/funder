"""Deterministic conjunctive row filtering shared by selection modules."""

from __future__ import annotations

import hashlib
import json
import operator
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from camovar.table_io import JsonRow

_PREDICATE_PATTERN = re.compile(r"^\s*([A-Za-z0-9_]+)\s*(>=|<=|!=|=|>|<|~)\s*(.*?)\s*$")


@dataclass(frozen=True)
class Predicate:
    """One field comparison used by metadata and univariate filters."""

    field: str
    operator: str
    expected: str

    def matches(self, row: Mapping[str, Any]) -> bool:
        """Return whether this predicate matches one row."""
        actual = row.get(self.field)
        if actual is None:
            return False
        if self.operator == "~":
            return self.expected.casefold() in str(actual).casefold()
        if self.operator in {">", ">=", "<", "<="}:
            return _numeric_compare(float(actual), float(self.expected), self.operator)
        return _TEXT_OPERATORS[self.operator](str(actual), self.expected)

    def as_text(self) -> str:
        """Return a stable user-facing representation."""
        return f"{self.field}{self.operator}{self.expected}"


_TEXT_OPERATORS: dict[str, Callable[[str, str], bool]] = {
    "=": operator.eq,
    "!=": operator.ne,
}


def parse_predicates(expressions: Sequence[str]) -> tuple[Predicate, ...]:
    """Parse CLI predicate expressions into comparable filter objects."""
    predicates: list[Predicate] = []
    for expression in expressions:
        match = _PREDICATE_PATTERN.match(expression)
        if match is None:
            raise ValueError(f"invalid predicate: {expression}")
        predicates.append(Predicate(match.group(1), match.group(2), match.group(3)))
    return tuple(predicates)


def filter_rows(
    rows: Sequence[Mapping[str, Any]],
    predicates: Sequence[Predicate],
) -> list[JsonRow]:
    """Apply predicates conjunctively to rows."""
    return [dict(row) for row in rows if all(predicate.matches(row) for predicate in predicates)]


def selection_id(module: str, name: str | None, predicates: Sequence[Predicate]) -> str:
    """Build a stable selection id from the module, optional name, and predicates."""
    parts = [predicate.as_text() for predicate in predicates]
    slug_source = name or "_".join(_slug(part) for part in parts) or "all"
    digest_payload = json.dumps(
        {"module": module, "name": name or "", "predicates": parts},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()[:12]
    return f"{_slug(slug_source)}-{digest}"


def _numeric_compare(actual: float, expected: float, comparison: str) -> bool:
    if comparison == ">":
        return actual > expected
    if comparison == ">=":
        return actual >= expected
    if comparison == "<":
        return actual < expected
    return actual <= expected


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return normalized or "selection"
