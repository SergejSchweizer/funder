"""Public Selection ports.

Ports define the interfaces Update may depend on without importing
Selection's private adapters or repositories. Concrete port protocols (for
example finalizing a candidate membership against supplied metric evidence)
are added alongside the Selection membership contracts; this module declares
the package boundary so Update has a stable, adapter-free import target.
"""

from __future__ import annotations

from typing import Protocol

from founder.selection.contracts import CandidateMembership, CurrentSelectionPointer


class SelectionReadPort(Protocol):
    """Marker protocol for read-only access to published Selection state.

    Concrete methods (for example resolving the current Selection pointer or
    a candidate membership) are added by the Selection contract PRs that
    build on this skeleton.
    """

    def current_pointer(self) -> CurrentSelectionPointer | None: ...

    def candidate_membership(self, candidate_membership_id: str) -> CandidateMembership | None: ...


__all__ = ["SelectionReadPort"]
