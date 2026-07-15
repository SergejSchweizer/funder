"""Update domain module: current-Selection metric computation and analysis.

Update computes and reuses metrics only for the current Selection, asks
Selection to finalize metric predicates, and publishes analyses. Update may
depend on Refresh's and Selection's public `contracts`, `ports`, and
`service` modules; it must not import either module's private adapters, and
neither Refresh nor Selection may import Update.

This package is a boundary skeleton. Work-planning, metric-cache, and
analysis DTOs, ports, and service behavior are added by the Update contract
and CLI PRs that build on this skeleton.
"""

from __future__ import annotations
