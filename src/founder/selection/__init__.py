"""Selection domain module: deterministic conjunctive instrument selections.

Selection defines, persists, and activates deterministic conjunctive
selections without performing network access or metric computation.
Selection may depend only on Refresh's public `contracts` and `ports`; it
must not import Refresh's adapters, and it must not import Update.

This package is a boundary skeleton. Predicate, membership, and lifecycle
DTOs, ports, and service behavior are added by the Selection contract and
CLI PRs that build on this skeleton.
"""

from __future__ import annotations
