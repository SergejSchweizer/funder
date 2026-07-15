"""Update application service."""

from __future__ import annotations

from founder.selection.contracts import CandidateMembership, CurrentSelectionPointer, SelectionState
from founder.selection.ports import SelectionReadPort
from founder.update.contracts import (
    UPDATE_CONTRACT_VERSION,
    CurrentUpdatePointer,
    PinnedUpdateInput,
    UpdatePlan,
    UpdateRequest,
    UpdateRunManifest,
    UpdateWorkItem,
    UpdateWorkKind,
)


class UpdateService:
    """Plan Update work from the current Selection read port."""

    def __init__(self, *, selection_read_port: SelectionReadPort | None = None) -> None:
        self._selection_read_port = selection_read_port
        self._current_pointer: CurrentUpdatePointer | None = None

    @staticmethod
    def contract_version() -> str:
        return UPDATE_CONTRACT_VERSION.qualified_name

    def plan_current_selection(self, request: UpdateRequest) -> UpdatePlan:
        pointer = self._current_selection_pointer()
        if pointer.selection_id != request.selection_id:
            raise ValueError("update request does not match the current Selection")
        candidate = self._candidate_membership(pointer.candidate_membership_id)
        if not candidate.listing_ids:
            raise ValueError("cannot plan Update work for an empty Selection")
        pinned = PinnedUpdateInput(
            selection_id=pointer.selection_id,
            candidate_membership_id=pointer.candidate_membership_id,
            final_membership_id=pointer.membership_id,
            refresh_snapshot_id=candidate.catalog_snapshot_id,
        )
        asset_work = tuple(
            UpdateWorkItem(f"asset:{listing_id}", UpdateWorkKind.ASSET_METRIC)
            for listing_id in sorted(candidate.listing_ids)
        )
        finalization: tuple[UpdateWorkItem, ...] = ()
        if pointer.state is SelectionState.PENDING_UPDATE:
            finalization = (
                UpdateWorkItem(
                    "selection:finalize",
                    UpdateWorkKind.SELECTION_FINALIZATION,
                    tuple(item.work_id for item in asset_work),
                ),
            )
        return UpdatePlan(pinned_input=pinned, work_items=(*asset_work, *finalization))

    def publish_manifest(self, manifest: UpdateRunManifest) -> CurrentUpdatePointer:
        if not manifest.published:
            raise ValueError("only published update manifests can become current")
        pointer = CurrentUpdatePointer(run_id=manifest.run_id, plan_id=manifest.plan_id)
        self._current_pointer = pointer
        return pointer

    def current_pointer(self) -> CurrentUpdatePointer | None:
        return self._current_pointer

    def _current_selection_pointer(self) -> CurrentSelectionPointer:
        if self._selection_read_port is None:
            raise ValueError("update planning requires a Selection read port")
        pointer = self._selection_read_port.current_pointer()
        if pointer is None:
            raise ValueError("cannot plan Update work without a current Selection")
        if pointer.state in {SelectionState.PAUSED, SelectionState.ARCHIVED, SelectionState.STALE}:
            raise ValueError(f"cannot plan Update work for {pointer.state.value} Selection")
        return pointer

    def _candidate_membership(self, candidate_membership_id: str) -> CandidateMembership:
        if self._selection_read_port is None:
            raise ValueError("update planning requires a Selection read port")
        candidate = self._selection_read_port.candidate_membership(candidate_membership_id)
        if candidate is None:
            raise ValueError("current Selection candidate membership is unavailable")
        return candidate


__all__ = ["UpdateService"]
