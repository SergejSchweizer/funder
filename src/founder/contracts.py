"""Typed contracts shared by Search and Fetch modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def require_text(value: str, field_name: str) -> str:
    """Return stripped text or raise a clear contract error."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


@dataclass(frozen=True)
class SearchCandidate:
    """A normalized instrument candidate found by Search."""

    search_run_id: str
    query: str
    source_endpoint: str
    code: str
    exchange: str
    instrument_type: str
    country: str
    currency: str
    isin: str
    name: str
    normalized_name: str
    found_at: datetime
    previous_close: float | None = None
    previous_close_date: str | None = None
    is_primary: bool | None = None

    def __post_init__(self) -> None:
        require_text(self.search_run_id, "search_run_id")
        require_text(self.query, "query")
        require_text(self.source_endpoint, "source_endpoint")
        require_text(self.code, "code")
        require_text(self.exchange, "exchange")
        require_text(self.name, "name")
        if self.found_at.tzinfo is None:
            raise ValueError("found_at must be timezone-aware")


@dataclass(frozen=True)
class CanonicalUniverseRow:
    """The Search-to-Fetch contract: one approved listing for one ISIN."""

    search_run_id: str
    isin: str
    code: str
    exchange: str
    instrument_type: str
    country: str
    currency: str
    name: str
    normalized_name: str
    selection_reason: str
    selected_for_fetch: bool

    def __post_init__(self) -> None:
        require_text(self.search_run_id, "search_run_id")
        require_text(self.isin, "isin")
        require_text(self.code, "code")
        require_text(self.exchange, "exchange")
        require_text(self.name, "name")
        require_text(self.selection_reason, "selection_reason")
        if not self.selected_for_fetch:
            raise ValueError("canonical rows must be selected for fetch")


@dataclass(frozen=True)
class FetchRun:
    """Operational metadata for one fetch execution."""

    run_id: str
    universe_search_run_id: str
    started_at: datetime
    source: str = "EODHD"

    def __post_init__(self) -> None:
        require_text(self.run_id, "run_id")
        require_text(self.universe_search_run_id, "universe_search_run_id")
        require_text(self.source, "source")
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")

    @classmethod
    def start(cls, run_id: str, universe_search_run_id: str) -> FetchRun:
        return cls(
            run_id=run_id,
            universe_search_run_id=universe_search_run_id,
            started_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class FetchError:
    """A non-secret fetch error record."""

    run_id: str
    code: str
    exchange: str
    endpoint: str
    error_type: str
    message: str

    def __post_init__(self) -> None:
        require_text(self.run_id, "run_id")
        require_text(self.code, "code")
        require_text(self.exchange, "exchange")
        require_text(self.endpoint, "endpoint")
        require_text(self.error_type, "error_type")
        require_text(self.message, "message")
