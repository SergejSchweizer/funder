"""Public Update ports.

Ports define the interfaces used to reuse cached metric artifacts and
publish analyses without importing Update's private cache repositories.
Concrete port protocols are added alongside the Update work-planner
contracts; this module declares the package boundary so tests and future
consumers have a stable, adapter-free import target.
"""

from __future__ import annotations

from typing import Protocol

from founder.update.contracts import CurrentUpdatePointer, MetricArtifactRef


class UpdateReadPort(Protocol):
    """Marker protocol for read-only access to published Update results.

    Concrete methods (for example resolving the current Update pointer or a
    metric artifact reference) are added by the Update contract PRs that
    build on this skeleton.
    """

    def current_pointer(self) -> CurrentUpdatePointer | None: ...

    def metric_artifact(self, cache_key_id: str) -> MetricArtifactRef | None: ...


__all__ = ["UpdateReadPort"]
