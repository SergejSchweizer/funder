"""Refresh application service."""

from __future__ import annotations

from founder.refresh.contracts import (
    REFRESH_CONTRACT_VERSION,
    CatalogCompleteness,
    CatalogSnapshot,
    InstrumentRecord,
    ListingRecord,
    MissingIsinReviewRow,
    RefreshPlan,
    RefreshRequest,
    RefreshResult,
    RefreshRunStatus,
    UnsupportedListingReviewRow,
)
from founder.refresh.ports import RefreshCatalogProviderPort, RefreshPublisherPort


class RefreshService:
    """Refresh orchestration with provider and publication side effects injected."""

    def __init__(
        self,
        *,
        catalog_provider: RefreshCatalogProviderPort | None = None,
        publisher: RefreshPublisherPort | None = None,
    ) -> None:
        self._catalog_provider = catalog_provider
        self._publisher = publisher

    @staticmethod
    def contract_version() -> str:
        return REFRESH_CONTRACT_VERSION.qualified_name

    def synchronize_catalog(self, request: RefreshRequest) -> RefreshResult:
        if self._catalog_provider is None:
            raise ValueError("refresh catalog synchronization requires a catalog provider")

        listings: list[ListingRecord] = []
        missing_isins: list[MissingIsinReviewRow] = []
        errors: list[str] = []
        completed_exchanges = 0
        for exchange in request.exchanges:
            try:
                exchange_listings = self._catalog_provider.list_exchange(exchange)
            except Exception as error:  # pragma: no cover - concrete adapters map provider errors
                errors.append(f"{exchange}: {error}")
                continue
            completed_exchanges += 1
            for listing in exchange_listings:
                if not listing.isin.strip():
                    missing_isins.append(
                        MissingIsinReviewRow(
                            provider=listing.provider,
                            exchange=listing.exchange,
                            code=listing.code,
                            reason="missing_isin",
                        )
                    )
                    continue
                listings.append(listing)

        instruments = tuple(
            InstrumentRecord(isin=isin)
            for isin in sorted({listing.instrument_id for listing in listings})
        )
        completeness = CatalogCompleteness(
            expected_exchanges=len(request.exchanges),
            completed_exchanges=completed_exchanges,
            failed_exchanges=len(errors),
            missing_isin_rows=len(missing_isins),
        )
        snapshot = CatalogSnapshot(
            instruments=instruments,
            listings=tuple(sorted(listings, key=lambda item: item.listing_id)),
            completeness=completeness,
        )
        plan = self.plan_market_data(run_id=request.run_id, snapshot=snapshot)
        status = (
            RefreshRunStatus.SUCCEEDED if completeness.is_complete else RefreshRunStatus.PARTIAL
        )
        if request.publish and not completeness.is_complete:
            raise ValueError("cannot publish incomplete refresh snapshot")
        if request.publish and self._publisher is not None:
            self._publisher.publish_catalog(snapshot)
        return RefreshResult(
            request=request,
            plan=plan,
            snapshot=snapshot,
            status=status,
            missing_isins=tuple(missing_isins),
            errors=tuple(errors),
        )

    def plan_market_data(self, *, run_id: str, snapshot: CatalogSnapshot) -> RefreshPlan:
        chosen: dict[str, ListingRecord] = {}
        excluded: list[UnsupportedListingReviewRow] = []
        preferred = tuple(item.upper() for item in snapshot.policy.preferred_exchanges)
        for listing in sorted(snapshot.listings, key=lambda item: item.listing_id):
            if not listing.active:
                excluded.append(UnsupportedListingReviewRow(listing.listing_id, "inactive_listing"))
                continue
            current = chosen.get(listing.instrument_id)
            if current is None or _listing_rank(listing, preferred) < _listing_rank(
                current, preferred
            ):
                if current is not None:
                    excluded.append(
                        UnsupportedListingReviewRow(current.listing_id, "duplicate_isin")
                    )
                chosen[listing.instrument_id] = listing
            else:
                excluded.append(UnsupportedListingReviewRow(listing.listing_id, "duplicate_isin"))
        return RefreshPlan(
            run_id=run_id,
            exchange_codes=tuple({listing.exchange for listing in snapshot.listings}),
            eligible_listing_ids=tuple(listing.listing_id for listing in chosen.values()),
            excluded_listings=tuple(excluded),
        )


def _listing_rank(
    listing: ListingRecord, preferred_exchanges: tuple[str, ...]
) -> tuple[int, str, str]:
    exchange = listing.exchange.strip().upper()
    preferred_rank = preferred_exchanges.index(exchange) if exchange in preferred_exchanges else 999
    return (preferred_rank, exchange, listing.code.strip().upper())


__all__ = ["RefreshService"]
