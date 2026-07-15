"""Refresh domain module: global provider catalog and market-data snapshots.

Refresh discovers every provider-visible instrument and listing and
maintains catalog and market-data snapshots independent of any Selection or
Update. Refresh must not import Selection or Update; Selection and Update
may depend on Refresh's public `contracts` and `ports` only.

This package is a boundary skeleton. `InstrumentRecord`, `ListingRecord`,
`CatalogSnapshot`, and related public DTOs, ports, and service behavior are
added by the Refresh contract, planning, and CLI PRs that build on this
skeleton.
"""

from __future__ import annotations
