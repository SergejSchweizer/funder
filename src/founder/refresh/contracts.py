"""Public Refresh contracts (versioned DTOs)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from founder.contract_versioning import ContractVersion, stable_contract_id

REFRESH_CONTRACT_VERSION = ContractVersion(name="refresh", version=1)


def _empty_string_mapping() -> Mapping[str, str]:
    return {}


def normalized_identifier(value: str, *, field_name: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class InstrumentRecord:
    isin: str
    name: str = ""
    domicile_country: str = ""
    fund_metadata: Mapping[str, str] = field(default_factory=_empty_string_mapping)

    @property
    def instrument_id(self) -> str:
        return normalized_identifier(self.isin, field_name="isin")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract": REFRESH_CONTRACT_VERSION.qualified_name,
            "instrument_id": self.instrument_id,
            "isin": self.instrument_id,
            "name": self.name.strip(),
            "domicile_country": self.domicile_country.strip().upper(),
            "fund_metadata": dict(sorted(self.fund_metadata.items())),
        }


@dataclass(frozen=True, slots=True)
class ListingRecord:
    provider: str
    exchange: str
    code: str
    isin: str
    trading_currency: str = ""
    listing_country: str = ""
    provider_declared_distribution_frequency: str = ""
    historical_nav_available: bool = False
    active: bool = True
    first_seen: str = ""
    last_seen: str = ""
    provenance: Mapping[str, str] = field(default_factory=_empty_string_mapping)

    @property
    def instrument_id(self) -> str:
        return normalized_identifier(self.isin, field_name="isin")

    @property
    def listing_id(self) -> str:
        return stable_contract_id(
            "listing",
            {
                "contract": REFRESH_CONTRACT_VERSION.qualified_name,
                "provider": normalized_identifier(self.provider, field_name="provider"),
                "exchange": normalized_identifier(self.exchange, field_name="exchange"),
                "code": normalized_identifier(self.code, field_name="code"),
            },
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "active": self.active,
            "code": normalized_identifier(self.code, field_name="code"),
            "contract": REFRESH_CONTRACT_VERSION.qualified_name,
            "exchange": normalized_identifier(self.exchange, field_name="exchange"),
            "first_seen": self.first_seen,
            "historical_nav_available": self.historical_nav_available,
            "instrument_id": self.instrument_id,
            "isin": self.instrument_id,
            "last_seen": self.last_seen,
            "listing_country": self.listing_country.strip().upper(),
            "listing_id": self.listing_id,
            "provider": normalized_identifier(self.provider, field_name="provider"),
            "provider_declared_distribution_frequency": (
                self.provider_declared_distribution_frequency
            ),
            "provenance": dict(sorted(self.provenance.items())),
            "trading_currency": self.trading_currency.strip().upper(),
        }


@dataclass(frozen=True, slots=True)
class CanonicalListingPolicy:
    name: str = "default"
    version: int = 1
    preferred_exchanges: tuple[str, ...] = ("XETRA",)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "preferred_exchanges": tuple(
                normalized_identifier(item, field_name="preferred_exchange")
                for item in self.preferred_exchanges
            ),
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class CatalogCompleteness:
    expected_exchanges: int
    completed_exchanges: int
    failed_exchanges: int = 0
    missing_isin_rows: int = 0

    @property
    def is_complete(self) -> bool:
        return self.failed_exchanges == 0 and self.completed_exchanges >= self.expected_exchanges


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    instruments: tuple[InstrumentRecord, ...]
    listings: tuple[ListingRecord, ...]
    completeness: CatalogCompleteness
    policy: CanonicalListingPolicy = CanonicalListingPolicy()

    @property
    def catalog_snapshot_id(self) -> str:
        return stable_contract_id("catalog", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "completeness": {
                "completed_exchanges": self.completeness.completed_exchanges,
                "expected_exchanges": self.completeness.expected_exchanges,
                "failed_exchanges": self.completeness.failed_exchanges,
                "missing_isin_rows": self.completeness.missing_isin_rows,
            },
            "contract": REFRESH_CONTRACT_VERSION.qualified_name,
            "instruments": sorted(
                (item.canonical_payload() for item in self.instruments),
                key=lambda row: str(row["instrument_id"]),
            ),
            "listings": sorted(
                (item.canonical_payload() for item in self.listings),
                key=lambda row: str(row["listing_id"]),
            ),
            "policy": self.policy.canonical_payload(),
        }


@dataclass(frozen=True, slots=True)
class MarketDatasetVersion:
    dataset: str
    listing_id: str
    content_fingerprint: str
    first_date: str = ""
    last_date: str = ""

    @property
    def dataset_version_id(self) -> str:
        return stable_contract_id("market_dataset", self.canonical_payload())

    def canonical_payload(self) -> dict[str, str]:
        return {
            "content_fingerprint": self.content_fingerprint,
            "dataset": self.dataset,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "listing_id": self.listing_id,
        }


@dataclass(frozen=True, slots=True)
class MarketDataVersionSet:
    versions: tuple[MarketDatasetVersion, ...]

    @property
    def market_data_version_set_id(self) -> str:
        return stable_contract_id("market_set", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract": REFRESH_CONTRACT_VERSION.qualified_name,
            "versions": sorted(
                (item.canonical_payload() for item in self.versions),
                key=lambda row: (row["listing_id"], row["dataset"], row["content_fingerprint"]),
            ),
        }


@dataclass(frozen=True, slots=True)
class RefreshSnapshotRef:
    catalog_snapshot_id: str
    market_data_version_set_id: str

    def __post_init__(self) -> None:
        if not self.catalog_snapshot_id or not self.market_data_version_set_id:
            raise ValueError("refresh snapshot refs must pin catalog and market-data versions")


@dataclass(frozen=True, slots=True)
class CurrentRefreshPointer:
    refresh_snapshot_id: str
    catalog_snapshot_id: str
    market_data_version_set_id: str
    run_id: str

    def __post_init__(self) -> None:
        if not self.refresh_snapshot_id:
            raise ValueError("current Refresh pointer requires a refresh snapshot id")


@dataclass(frozen=True, slots=True)
class MissingIsinReviewRow:
    provider: str
    exchange: str
    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class UnsupportedListingReviewRow:
    listing_id: str
    reason: str


class RefreshRunStatus(Enum):
    PLANNED = "planned"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RefreshRequest:
    run_id: str
    exchanges: tuple[str, ...]
    publish: bool = False
    resume_from: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("refresh request run_id must not be empty")
        if not self.exchanges:
            raise ValueError("refresh request requires at least one exchange")


@dataclass(frozen=True, slots=True)
class RefreshPlan:
    run_id: str
    exchange_codes: tuple[str, ...]
    eligible_listing_ids: tuple[str, ...] = ()
    excluded_listings: tuple[UnsupportedListingReviewRow, ...] = ()

    @property
    def plan_id(self) -> str:
        return stable_contract_id("refresh_plan", self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract": REFRESH_CONTRACT_VERSION.qualified_name,
            "eligible_listing_ids": tuple(sorted(self.eligible_listing_ids)),
            "excluded_listings": tuple(
                sorted(
                    (
                        {"listing_id": row.listing_id, "reason": row.reason}
                        for row in self.excluded_listings
                    ),
                    key=lambda row: (row["listing_id"], row["reason"]),
                )
            ),
            "exchange_codes": tuple(
                sorted(
                    normalized_identifier(item, field_name="exchange")
                    for item in self.exchange_codes
                )
            ),
            "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class RefreshRunManifest:
    run_id: str
    plan_id: str
    status: RefreshRunStatus
    error_count: int = 0
    resume_marker: str = ""


@dataclass(frozen=True, slots=True)
class RefreshResult:
    request: RefreshRequest
    plan: RefreshPlan
    snapshot: CatalogSnapshot | None
    status: RefreshRunStatus
    missing_isins: tuple[MissingIsinReviewRow, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def listing_count(self) -> int:
        return 0 if self.snapshot is None else len(self.snapshot.listings)

    @property
    def unique_isin_count(self) -> int:
        if self.snapshot is None:
            return 0
        return len({item.instrument_id for item in self.snapshot.listings if item.active})


__all__ = [
    "CanonicalListingPolicy",
    "CatalogCompleteness",
    "CatalogSnapshot",
    "CurrentRefreshPointer",
    "InstrumentRecord",
    "ListingRecord",
    "MarketDatasetVersion",
    "MarketDataVersionSet",
    "MissingIsinReviewRow",
    "REFRESH_CONTRACT_VERSION",
    "RefreshPlan",
    "RefreshRequest",
    "RefreshResult",
    "RefreshRunManifest",
    "RefreshRunStatus",
    "RefreshSnapshotRef",
    "UnsupportedListingReviewRow",
    "normalized_identifier",
]
