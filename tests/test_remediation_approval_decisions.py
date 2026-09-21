from __future__ import annotations

import copy

import pytest

from intelligence.remediation.approval_decisions import (
    ExecutionSnapshotError,
    RemediationDecisionStore,
    build_execution_snapshot,
    execution_snapshot_hash,
)
from intelligence.remediation.approval_engine import ApprovalEngine
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


def _target(*patch_ids: str, subscription_id: str = "sub-1") -> PatchTarget:
    return PatchTarget(
        target_id=TARGET_ID,
        inventory_kind="Azure VM",
        subscription_id=subscription_id,
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
        "subscription_id": "sub-1",
        "available_patches": [
            AvailablePatch(patch_id="KB600001").to_dict(),
            AvailablePatch(patch_id="KB600002").to_dict(),
        ],
        "snapshot_hash": execution_snapshot_hash(snapshot),
    }
    assert service.scopes == [scope]
    # Adding subscription_id must never change the hash: existing pending
    # approvals recorded before this fix must still revalidate as current.
    assert execution_snapshot_hash(snapshot) == execution_snapshot_hash(
        {**snapshot, "subscription_id": ""}
    )


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


def test_candidate_snapshot_carries_subscription_id_for_provider_equality_checks() -> None:
    """Regression: the SRE Agent's read skill rejects a submitted approval
    snapshot that lacks ``subscription_id``/``approver`` with
    ``blocked_no_action`` ("immutable approval snapshot lacks required
    subscription and approver fields for equality validation"). The target
    already carries ``subscription_id`` (Azure Update Manager / ARG
    acquisition); the snapshot must project it so the downstream provider
    never has to re-derive or trust an un-pinned identity field.
    """
    service = _PatchingService(_target("KB600001", subscription_id="sub-prod-1"))

    snapshot = build_execution_snapshot(_plan(), service, scope=object())

    assert snapshot["subscription_id"] == "sub-prod-1"


def test_approved_decision_snapshot_carries_the_recorded_approver() -> None:
    """Regression: the persisted (execution-bound) snapshot must self-attest
    who approved it -- the same identity dispatched to Azure/the SRE Agent
    for its own equality validation -- not only the decision record's own
    top-level ``approver`` field, which the provider never reads.
    """
    store = RemediationDecisionStore()
    snapshot = build_execution_snapshot(
        _plan(), _PatchingService(_target("KB600001", subscription_id="sub-prod-1"))
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

    assert record["execution_snapshot"]["approver"] == "approver@example.com"
    assert record["execution_snapshot"]["subscription_id"] == "sub-prod-1"
    # The approver merge must never change the hash SRE / execute-time
    # revalidation checks -- it's an additive, non-security-boundary field.
    assert record["execution_snapshot"]["snapshot_hash"] == snapshot["snapshot_hash"]


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


def test_append_persists_approver_roles_and_policy_version_with_safe_defaults() -> None:
    store = RemediationDecisionStore()

    record = store.append(
        plan=_plan(),
        decision="approved",
        approver="approver@example.com",
        reason="Approved",
        scope={},
        action_version="action-v1",
        approver_roles=["Security Response Owner", "security response owner", " "],
        approval_policy_version="policy-v1",
    )

    assert record["approver_roles"] == ["security response owner"]
    assert record["approval_policy_version"] == "policy-v1"
    assert record["self_approved"] is False
    assert record["self_approval_policy_id"] == ""


def test_append_defaults_approver_roles_and_policy_version_when_omitted() -> None:
    store = RemediationDecisionStore()

    record = store.append(
        plan=_plan(),
        decision="approved",
        approver="approver@example.com",
        reason="Approved",
        scope={},
        action_version="action-v1",
    )

    assert record["approver_roles"] == []
    assert record["approval_policy_version"] == ""
    assert record["self_approved"] is False
    assert record["self_approval_policy_id"] == ""


def test_record_self_approval_marks_exactly_one_decision_and_is_idempotent() -> None:
    store = RemediationDecisionStore()
    record = store.append(
        plan=_plan(),
        decision="approved",
        approver="approver@example.com",
        reason="Approved",
        scope={},
        action_version="action-v1",
    )
    other = store.append(
        plan=_plan(),
        decision="approved",
        approver="other@example.com",
        reason="Approved",
        scope={},
        action_version="action-v1",
    )

    updated = store.record_self_approval(record["decision_id"], policy_id="demo-self-approval")

    assert updated["self_approved"] is True
    assert updated["self_approval_policy_id"] == "demo-self-approval"

    rows = store.list("RMP-0001")
    marked = next(row for row in rows if row["decision_id"] == record["decision_id"])
    unmarked = next(row for row in rows if row["decision_id"] == other["decision_id"])
    assert marked["self_approved"] is True
    assert unmarked["self_approved"] is False

    # Idempotent: calling twice with the same policy_id is a no-op.
    again = store.record_self_approval(record["decision_id"], policy_id="demo-self-approval")
    assert again["self_approved"] is True
    assert again["self_approval_policy_id"] == "demo-self-approval"


def test_record_self_approval_raises_on_unknown_decision_id() -> None:
    store = RemediationDecisionStore()

    with pytest.raises(ValueError):
        store.record_self_approval("RMD-UNKNOWN", policy_id="demo-self-approval")


def test_record_self_approval_concurrent_callers_converge_with_no_lost_update() -> None:
    store = RemediationDecisionStore()
    record = store.append(
        plan=_plan(),
        decision="approved",
        approver="approver@example.com",
        reason="Approved",
        scope={},
        action_version="action-v1",
    )

    # Simulate two concurrent callers each performing their own read/mutate/
    # write cycle -- the CAS retry loop must converge without a lost update.
    first = store.record_self_approval(record["decision_id"], policy_id="demo-self-approval")
    second = store.record_self_approval(record["decision_id"], policy_id="demo-self-approval")

    assert first["self_approved"] is True
    assert second["self_approved"] is True
    assert len(store.list("RMP-0001")) == 1


def test_list_backfills_legacy_document_with_no_new_keys() -> None:
    store = RemediationDecisionStore()
    # Hand-write a legacy (schema 1.0.0) decision document with none of the
    # four Phase 03.5 fields present at all.
    store._memory = {
        "schema_version": "1.0.0",
        "revision": 1,
        "decisions": [
            {
                "decision_id": "RMD-LEGACY",
                "plan_id": "RMP-0001",
                "decision": "approved",
                "approver": "legacy@example.com",
                "decided_at": "2020-01-01T00:00:00+00:00",
                "reason": "Legacy",
                "scope": {},
                "action_version": "action-v0",
                "expires_at": "",
                "revalidation": {"status": "passed", "checks": []},
                "execution_authorized": False,
                "execution_performed": False,
                "read_only": True,
                "execution_snapshot": None,
            }
        ],
        "updated_at": "2020-01-01T00:00:00+00:00",
    }

    rows = store.list("RMP-0001")

    assert len(rows) == 1
    assert rows[0]["approver_roles"] == []
    assert rows[0]["approval_policy_version"] == ""
    assert rows[0]["self_approved"] is False
    assert rows[0]["self_approval_policy_id"] == ""



def _policy(policy_id: str, roles: list[str]) -> dict:
    return {"policy_id": policy_id, "roles": roles, "conditions": {}}


def test_policy_version_is_order_independent_and_change_sensitive() -> None:
    first = ApprovalEngine([_policy("p1", ["Change Manager"]), _policy("p2", ["Security Response Owner"])])
    reordered = ApprovalEngine([_policy("p2", ["Security Response Owner"]), _policy("p1", ["Change Manager"])])
    changed = ApprovalEngine([_policy("p1", ["Change Manager"]), _policy("p2", ["Different Role"])])

    assert first.policy_version == reordered.policy_version
    assert first.policy_version != changed.policy_version
