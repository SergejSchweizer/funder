"""Public Refresh read ports.

Ports define the read-only interfaces Selection and Update may depend on
without importing Refresh's private adapters, repositories, or infrastructure
code. Concrete port protocols are added alongside the Refresh catalog and
market-data contracts; this module declares the package boundary so
Selection and Update have a stable, adapter-free import target.
"""

from __future__ import annotations

from typing import Protocol

from founder.refresh.contracts import CatalogSnapshot, ListingRecord


class RefreshCatalogProviderPort(Protocol):
    def list_exchange(self, exchange: str) -> tuple[ListingRecord, ...]: ...


class RefreshPublisherPort(Protocol):
    def publish_catalog(self, snapshot: CatalogSnapshot) -> str: ...


class RefreshReadPort(Protocol):
    """Marker protocol for read-only access to published Refresh snapshots.

    Concrete methods (for example resolving the current catalog snapshot or
    a pinned market-data version set) are added by the Refresh contract PR
    that builds on this skeleton.
    """


__all__ = ["RefreshCatalogProviderPort", "RefreshPublisherPort", "RefreshReadPort"]
