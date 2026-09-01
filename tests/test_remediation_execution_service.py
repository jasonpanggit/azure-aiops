"""Approval-gated execution of a single controlled-patch-recovery plan.

The execution service is the one place in Phase 3 where HOG changes Azure
state. Every test here proves a bound: no caller-supplied target/patch
override exists, and nothing reaches ``PatchingService.trigger`` unless the
plan is exactly ``controlled-patch-recovery`` with a current, unexpired,
approved decision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intelligence.remediation.approval_decisions import RemediationDecisionStore
from intelligence.remediation.execution_service import (
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.plan_repository import PlanRepository
from operations.patching.adapters import PatchExecutionUnavailable, RecordingPatchExecutionAdapter
from operations.patching.models import PatchTarget
from operations.patching.service import PatchingService

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"

NOW = datetime(2026, 8, 18, 13, tzinfo=UTC)


def _plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-0001",
        "action_id": "controlled-patch-recovery",
        "opportunity_type": "Patch and vulnerability debt",
        "action_version": "v1",
        "resource_key": TARGET_ID,
        "resource": {"id": TARGET_ID, "name": "vm-payments", "entity_type": "VirtualMachine"},
    }
    plan.update(overrides)
    return plan


class _FakeVulnerabilityService:
    """Minimal stand-in exposing exactly what PatchingService.targets() needs."""

    def __init__(self, target_id: str) -> None:
        self._target_id = target_id
        self.freshness = "2026-08-18T13:00:00Z"

    def asset_exposures(self, scope=None) -> list[dict]:
        return [
            {
                "asset_id": self._target_id,
                "name": "vm-payments",
                "inventory_kind": "Azure VM",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "missing_kbs": ["KB600001"],
                "severities": ["Critical"],
                "cve_ids": ["CVE-2026-0001"],
            }
        ]


class _FakePlanRepository:
    """Repository stub: only ``get`` is needed for Task 1."""

    def __init__(self, plan: dict | None) -> None:
        self._plan = plan

    def get(self, plan_id: str) -> dict | None:
        if self._plan is not None and self._plan["plan_id"] == plan_id:
            return dict(self._plan)
        return None


def _service(
    *,
    plan: dict | None,
    adapter=None,
    require_human_approval: bool = False,
) -> tuple[RemediationExecutionService, PlanRepository | _FakePlanRepository]:
    repository = _FakePlanRepository(plan)
    vulnerability_service = _FakeVulnerabilityService(TARGET_ID)
    patching_service = PatchingService(
        vulnerability_service,
        adapter=adapter or RecordingPatchExecutionAdapter(),
        require_human_approval=require_human_approval,
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        now=lambda: NOW,
    )
    return service, repository


def _decisions_store() -> RemediationDecisionStore:
    return RemediationDecisionStore()


def _approve(store: RemediationDecisionStore, plan: dict, *, expires_at: str = "") -> None:
    store.append(
        plan=plan,
        decision="approved",
        approver="approver@example.com",
        reason="Approved for patch recovery",
        scope={},
        action_version=plan["action_version"],
        expires_at=expires_at or (NOW + timedelta(days=1)).isoformat(),
        now=NOW,
    )


def test_execute_rejects_plan_with_non_patch_recovery_action_id():
    plan = _plan(action_id="configuration-baseline-recovery")
    service, _ = _service(plan=plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "action_not_executable"


def test_execute_rejects_plan_with_no_approved_decision():
    plan = _plan()
    repository = PlanRepository()
    repository.replace_generation([_full_plan(plan)])
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _FakeVulnerabilityService(TARGET_ID),
            adapter=RecordingPatchExecutionAdapter(),
            require_human_approval=False,
        ),
        now=lambda: NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "not_approved"


def test_execute_rejects_stale_action_version():
    plan = _plan()
    repository = PlanRepository()
    full = _full_plan(plan)
    repository.replace_generation([full])
    _approve(repository.decisions, full, )
    # Mutate the stored plan's action_version to simulate regeneration.
    full_stale = dict(full)
    full_stale["action_version"] = "v2-changed"
    repository.replace_generation([full_stale])

    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _FakeVulnerabilityService(TARGET_ID),
            adapter=RecordingPatchExecutionAdapter(),
            require_human_approval=False,
        ),
        now=lambda: NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "stale_approval"


def test_execute_rejects_expired_decision():
    plan = _plan()
    repository = PlanRepository()
    full = _full_plan(plan)
    repository.replace_generation([full])
    _approve(repository.decisions, full, expires_at=(NOW - timedelta(days=1)).isoformat())

    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _FakeVulnerabilityService(TARGET_ID),
            adapter=RecordingPatchExecutionAdapter(),
            require_human_approval=False,
        ),
        now=lambda: NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "approval_expired"


def test_execute_valid_approved_plan_triggers_patching_service_with_no_caller_override():
    plan = _plan()
    repository = PlanRepository()
    full = _full_plan(plan)
    repository.replace_generation([full])
    _approve(repository.decisions, full)

    adapter = RecordingPatchExecutionAdapter()
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _FakeVulnerabilityService(TARGET_ID),
            adapter=adapter,
            require_human_approval=False,
        ),
        now=lambda: NOW,
    )

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert result["status"] == "succeeded"
    assert len(adapter.submissions) == 1
    submitted_run, submitted_target = adapter.submissions[0]
    assert submitted_target.target_id == TARGET_ID
    assert set(submitted_run.patch_ids) == {"KB600001"}


def test_execute_public_signature_accepts_no_target_or_patch_override():
    import inspect

    signature = inspect.signature(RemediationExecutionService.execute)
    parameter_names = set(signature.parameters) - {"self"}
    assert parameter_names == {"plan_id", "requested_by"}


def test_patch_execution_unavailable_surfaces_as_failed_not_swallowed():
    plan = _plan()
    repository = PlanRepository()
    full = _full_plan(plan)
    repository.replace_generation([full])
    _approve(repository.decisions, full)

    class _FailingAdapter:
        name = "failing"

        def submit(self, run, target):
            raise PatchExecutionUnavailable("No execution identity configured")

    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _FakeVulnerabilityService(TARGET_ID),
            adapter=_FailingAdapter(),
            require_human_approval=False,
        ),
        now=lambda: NOW,
    )

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert result["status"] == "failed"
    assert "No execution identity configured" in result["message"]


def _full_plan(plan: dict) -> dict:
    """Fill in the fields PlanRepository/PlanRepository.decisions expect."""
    return {
        "title": "Controlled patch and failed-update recovery",
        "risk_assessment": {"overall_risk": {"level": "High", "drivers": []}},
        "approval_requirements": [],
        "execution_steps": [],
        "application": "Payments API",
        "business_service": "Checkout",
        **plan,
    }
