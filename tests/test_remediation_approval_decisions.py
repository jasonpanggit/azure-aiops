from __future__ import annotations

import copy

import pytest

from intelligence.remediation.approval_decisions import (
    ExecutionSnapshotError,
    RemediationDecisionStore,
    build_execution_snapshot,
    execution_snapshot_hash,
)
from operations.patching.models import AvailablePatch, PatchTarget

TARGET_ID = (
    "/subscriptions/sub-1/resourceGroups/rg-prod/providers/"
    "Microsoft.Compute/virtualMachines/vm-payments"
)


def _plan() -> dict:
    return {
        "plan_id": "RMP-0001",
        "action_id": "controlled-patch-recovery",
        "action_version": "action-v1",
        "resource_key": TARGET_ID,
        "resource": {"name": "vm-payments", "entity_type": "VirtualMachine"},
    }


def _target(*patch_ids: str) -> PatchTarget:
    return PatchTarget(
        target_id=TARGET_ID,
        inventory_kind="Azure VM",
        available_patches=tuple(
            AvailablePatch(patch_id=patch_id) for patch_id in patch_ids
        ),
    )


class _PatchingService:
    def __init__(self, target: PatchTarget | None) -> None:
        self.current_target = target
        self.scopes: list[object] = []

    def target(self, target_id: str, scope=None) -> PatchTarget | None:
        self.scopes.append(scope)
        if self.current_target is not None and target_id == self.current_target.target_id:
            return self.current_target
        return None


def test_candidate_snapshot_is_server_derived_sorted_versioned_and_hashed() -> None:
    service = _PatchingService(_target("KB600002", "KB600001"))
    scope = object()

    snapshot = build_execution_snapshot(_plan(), service, scope=scope)

    assert snapshot == {
        "target_id": TARGET_ID,
        "patch_ids": ["KB600001", "KB600002"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": "action-v1",
        "available_patches": [
            AvailablePatch(patch_id="KB600001").to_dict(),
            AvailablePatch(patch_id="KB600002").to_dict(),
        ],
        "snapshot_hash": execution_snapshot_hash(snapshot),
    }
    assert service.scopes == [scope]


def test_selected_patch_ids_narrows_snapshot_to_operator_chosen_subset() -> None:
    service = _PatchingService(_target("KB600002", "KB600001", "KB600003"))

    snapshot = build_execution_snapshot(
        _plan(), service, scope=object(), selected_patch_ids=["KB600002"]
    )

    assert snapshot["patch_ids"] == ["KB600002"]
    # Selecting a subset changes what gets hashed/approved -- the approval
    # binds to exactly the chosen patches, not the full available list.
    assert snapshot["snapshot_hash"] != build_execution_snapshot(_plan(), service, scope=object())["snapshot_hash"]


def test_selected_patch_ids_rejects_an_id_outside_the_observed_available_list() -> None:
    service = _PatchingService(_target("KB600001"))

    with pytest.raises(ExecutionSnapshotError) as excinfo:
        build_execution_snapshot(
            _plan(), service, scope=object(), selected_patch_ids=["KB999999"]
        )

    assert excinfo.value.reason == "patch_ids_not_available"
    assert excinfo.value.details["unknown_patch_ids"] == ["KB999999"]


def test_selected_patch_ids_rejects_an_empty_selection() -> None:
    service = _PatchingService(_target("KB600001"))

    with pytest.raises(ExecutionSnapshotError) as excinfo:
        build_execution_snapshot(_plan(), service, scope=object(), selected_patch_ids=[])

    assert excinfo.value.reason == "no_patches_selected"


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        (None, "target_not_found"),
        (_target(), "no_patches_available"),
    ],
)
def test_candidate_snapshot_fails_closed_without_target_or_patches(
    target: PatchTarget | None, reason: str
) -> None:
    with pytest.raises(ExecutionSnapshotError) as excinfo:
        build_execution_snapshot(_plan(), _PatchingService(target))

    assert excinfo.value.reason == reason


def test_approved_decision_persists_an_immutable_execution_snapshot() -> None:
    store = RemediationDecisionStore()
    snapshot = build_execution_snapshot(
        _plan(), _PatchingService(_target("KB600001"))
    )

    record = store.append(
        plan=_plan(),
        decision="approved",
        approver="approver@example.com",
        reason="Approved exact preview",
        scope={},
        action_version="action-v1",
        execution_snapshot=snapshot,
    )
    snapshot["patch_ids"].append("KB-WIDENED")

    assert record["execution_snapshot"]["patch_ids"] == ["KB600001"]
    assert store.list("RMP-0001")[0]["execution_snapshot"]["patch_ids"] == [
        "KB600001"
    ]


def test_non_approved_decision_never_persists_an_execution_snapshot() -> None:
    store = RemediationDecisionStore()
    snapshot = build_execution_snapshot(
        _plan(), _PatchingService(_target("KB600001"))
    )

    record = store.append(
        plan=_plan(),
        decision="rejected",
        approver="approver@example.com",
        reason="Rejected",
        scope={},
        action_version="action-v1",
        execution_snapshot=copy.deepcopy(snapshot),
    )

    assert record["execution_snapshot"] is None
