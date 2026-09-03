"""Enforcement tests for the approval gate on patch execution.

``POST /patching/runs`` is the only path in the platform that changes customer
Azure infrastructure, so it is the only place an approval gate can protect
anything. Before this gate existed the service recorded
``approved_by or requested_by``, meaning an omitted approver silently became
the requester, and ``agent_policy.require_human_approval`` was read at no
execution point at all.

Every test here asserts against the adapter, not just the raised error: the
property that matters is that Azure was never touched, not merely that a
message was produced.
"""

from __future__ import annotations

import pytest
from test_api_patching_router import VM_ID, _vulnerability_service

from operations.patching import InMemoryPatchRunStore, PatchingService
from operations.patching.adapters import RecordingPatchExecutionAdapter
from operations.patching.service import PatchValidationError


def _service(
    *, require_human_approval=True, allow_self_approval=False
) -> tuple[PatchingService, RecordingPatchExecutionAdapter]:
    adapter = RecordingPatchExecutionAdapter()
    service = PatchingService(
        _vulnerability_service(),
        store=InMemoryPatchRunStore(),
        adapter=adapter,
        require_human_approval=require_human_approval,
        allow_self_approval=allow_self_approval,
    )
    return service, adapter


def _target(service: PatchingService):
    target = next(item for item in service.targets() if item.target_id == VM_ID)
    assert target.patchable, "fixture must offer a patchable VM for these tests"
    return target


def _trigger(service: PatchingService, **overrides):
    target = _target(service)
    kwargs = {
        "target": target,
        "patch_ids": [min(target.available_patch_ids)],
        "requested_by": "operator@example.com",
        "reason": "Emergency patch",
    }
    kwargs.update(overrides)
    return service.trigger(**kwargs)


def test_missing_approver_is_refused_when_policy_requires_approval() -> None:
    """The gap that made the field decorative: omitting it used to self-approve."""
    service, adapter = _service()

    with pytest.raises(PatchValidationError) as excinfo:
        _trigger(service)

    assert "approver" in str(excinfo.value).casefold()
    assert adapter.submissions == [], "Azure must not be touched without an approver"


def test_self_approval_is_refused() -> None:
    service, adapter = _service()

    with pytest.raises(PatchValidationError):
        _trigger(service, approved_by="operator@example.com")

    assert adapter.submissions == []


def test_self_approval_cannot_be_disguised_by_casing_or_whitespace() -> None:
    """Identity comparison must normalise, or the check is trivially defeated."""
    service, adapter = _service()

    with pytest.raises(PatchValidationError):
        _trigger(service, approved_by="  Operator@Example.COM  ")

    assert adapter.submissions == []


def test_a_distinct_approver_is_accepted_and_recorded() -> None:
    service, adapter = _service()

    run = _trigger(service, approved_by="manager@example.com")

    assert run.approved_by == "manager@example.com"
    assert len(adapter.submissions) == 1


def test_dry_run_is_exempt_because_it_changes_nothing() -> None:
    service, adapter = _service()

    run = _trigger(service, dry_run=True)

    assert adapter.submissions == [], "a dry run must never reach the adapter"
    assert run is not None


def test_policy_disabled_allows_an_unapproved_run() -> None:
    """Turning the setting off is a deliberate choice and must take effect."""
    service, adapter = _service(require_human_approval=False)

    run = _trigger(service)

    assert len(adapter.submissions) == 1
    assert run.requested_by == "operator@example.com"


def test_policy_is_read_per_call_not_captured_at_construction() -> None:
    """An administrator re-enabling approval must not await a replica restart."""
    enabled = {"value": False}
    service, adapter = _service(require_human_approval=lambda: enabled["value"])

    _trigger(service)
    assert len(adapter.submissions) == 1

    enabled["value"] = True
    with pytest.raises(PatchValidationError):
        _trigger(service)

    assert len(adapter.submissions) == 1, "no further submission after re-enabling"


def test_service_built_without_the_policy_fails_closed() -> None:
    """A caller that forgets to pass the policy must get the safe behaviour."""
    adapter = RecordingPatchExecutionAdapter()
    service = PatchingService(
        _vulnerability_service(), store=InMemoryPatchRunStore(), adapter=adapter
    )

    with pytest.raises(PatchValidationError):
        _trigger(service)

    assert adapter.submissions == []


def test_self_approval_allowed_when_explicitly_opted_in() -> None:
    """Demo/single-operator environments may opt out of separation of duties."""
    service, adapter = _service(allow_self_approval=True)

    run = _trigger(service, approved_by="operator@example.com")

    assert run.approved_by == "operator@example.com"
    assert len(adapter.submissions) == 1


def test_self_approval_opt_in_is_read_per_call_not_captured_at_construction() -> None:
    """Same fresh-read guarantee as require_human_approval: no restart needed."""
    allowed = {"value": False}
    service, adapter = _service(allow_self_approval=lambda: allowed["value"])

    with pytest.raises(PatchValidationError):
        _trigger(service, approved_by="operator@example.com")
    assert adapter.submissions == []

    allowed["value"] = True
    run = _trigger(service, approved_by="operator@example.com")
    assert run.approved_by == "operator@example.com"
    assert len(adapter.submissions) == 1


def test_self_approval_opt_in_does_not_waive_missing_approver() -> None:
    """Opting into self-approval must not also waive the named-approver rule."""
    service, adapter = _service(allow_self_approval=True)

    with pytest.raises(PatchValidationError) as excinfo:
        _trigger(service)

    assert "approver" in str(excinfo.value).casefold()
    assert adapter.submissions == []


def test_service_built_without_self_approval_flag_fails_closed() -> None:
    """Omitting the new parameter must not silently allow self-approval."""
    adapter = RecordingPatchExecutionAdapter()
    service = PatchingService(
        _vulnerability_service(),
        store=InMemoryPatchRunStore(),
        adapter=adapter,
        require_human_approval=True,
    )

    with pytest.raises(PatchValidationError):
        _trigger(service, approved_by="operator@example.com")

    assert adapter.submissions == []
