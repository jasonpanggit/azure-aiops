"""Approval-gated execution of a single controlled-patch-recovery plan.

The execution service is the one place in Phase 3 where HOG changes Azure
state. Every test here proves a bound: no caller-supplied target/patch
override exists, and nothing reaches ``PatchingService.trigger`` unless the
plan is exactly ``controlled-patch-recovery`` with a current, unexpired,
approved decision.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from intelligence.remediation.approval_decisions import (
    RemediationDecisionStore,
    execution_snapshot_hash,
)
from intelligence.remediation.execution_service import (
    VERIFICATION_DEADLINE_SECONDS,
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from operations.defender_configuration import (
    ENABLE_DEFENDER_SERVERS_P1,
    DefenderConfigurationResult,
)
from operations.patching.adapters import (
    PatchExecutionUnavailable,
    RecordingPatchExecutionAdapter,
)
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
        self.asset_exposure_calls = 0

    def asset_exposures(self, scope=None) -> list[dict]:
        self.asset_exposure_calls += 1
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


class _EmptyVulnerabilityService:
    freshness = "2026-08-18T13:00:00Z"

    def asset_exposures(self, scope=None) -> list[dict]:
        return []


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


def _execution_snapshot(plan: dict, **overrides) -> dict:
    snapshot = {
        "target_id": TARGET_ID,
        "patch_ids": ["KB600001"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": plan["action_version"],
    }
    snapshot.update(overrides)
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    return snapshot


def _approve(
    store: RemediationDecisionStore,
    plan: dict,
    *,
    expires_at: str = "",
    execution_snapshot: dict | None = None,
    now: datetime = NOW,
) -> dict:
    return store.append(
        plan=plan,
        decision="approved",
        approver="approver@example.com",
        reason="Approved for patch recovery",
        scope={},
        action_version=plan["action_version"],
        expires_at=expires_at or (NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=execution_snapshot or _execution_snapshot(plan),
        now=now,
    )


def _eligible_business_decision(**overrides) -> dict:
    decision = {
        "disposition": "act_now",
        "business_impact": {"status": "known"},
        "review_requirements": [],
        "unknowns": [],
        "urgency_rationale": {"evidence_citations": ["assessment:assess-001"]},
    }
    decision.update(overrides)
    return decision


@pytest.mark.parametrize(
    ("plan_overrides", "reason"),
    [
        (
            {"business_decision": _eligible_business_decision(disposition="defer")},
            "disposition_not_executable",
        ),
        (
            {
                "business_decision": _eligible_business_decision(
                    business_impact={"status": "unknown"}
                )
            },
            "business_impact_unknown",
        ),
        (
            {
                "business_decision": _eligible_business_decision(
                    review_requirements=["CAB review"]
                )
            },
            "review_required",
        ),
        (
            {
                "business_decision": _eligible_business_decision(
                    unknowns=["downtime"]
                )
            },
            "decision_unknowns_present",
        ),
        (
            {
                "business_decision": _eligible_business_decision(
                    urgency_rationale={"evidence_citations": []}
                )
            },
            "decision_evidence_missing",
        ),
        ({"evidence_citations": []}, "plan_evidence_missing"),
    ],
)
def test_business_eligibility_rejects_before_target_lookup(
    plan_overrides: dict, reason: str
) -> None:
    plan = _full_plan(_plan(**plan_overrides))
    repository = PlanRepository()
    repository.replace_generation([plan])
    _approve(repository.decisions, plan)
    vulnerability = _FakeVulnerabilityService(TARGET_ID)
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            vulnerability,
            adapter=RecordingPatchExecutionAdapter(),
            require_human_approval=False,
        ),
        now=lambda: NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == reason
    assert vulnerability.asset_exposure_calls == 0


def test_execute_rejects_tampered_execution_snapshot_hash() -> None:
    plan = _full_plan(_plan())
    repository = PlanRepository()
    repository.replace_generation([plan])
    snapshot = _execution_snapshot(plan)
    snapshot["snapshot_hash"] = "0" * 64
    _approve(repository.decisions, plan, execution_snapshot=snapshot)
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

    assert excinfo.value.reason == "execution_snapshot_invalid"


def test_execute_rejects_snapshot_action_version_tampering() -> None:
    plan = _full_plan(_plan())
    repository = PlanRepository()
    repository.replace_generation([plan])
    snapshot = _execution_snapshot(plan, action_version="different-version")
    _approve(repository.decisions, plan, execution_snapshot=snapshot)
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

    assert excinfo.value.reason == "execution_snapshot_invalid"


def test_execute_never_widens_beyond_approved_patch_ids() -> None:
    plan = _full_plan(_plan())
    repository = PlanRepository()
    repository.replace_generation([plan])
    _approve(repository.decisions, plan)
    adapter = RecordingPatchExecutionAdapter()

    class _MorePatchesAvailable(_FakeVulnerabilityService):
        def asset_exposures(self, scope=None) -> list[dict]:
            rows = super().asset_exposures(scope)
            rows[0]["missing_kbs"] = ["KB600001", "KB600002"]
            return rows

    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _MorePatchesAvailable(TARGET_ID),
            adapter=adapter,
            require_human_approval=False,
        ),
        now=lambda: NOW,
    )

    service.execute(plan["plan_id"], requested_by="operator@example.com")

    submitted_run, _ = adapter.submissions[0]
    assert submitted_run.patch_ids == ("KB600001",)


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

    assert result["status"] == "running"
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


def test_target_revalidation_failure_is_persisted_as_failed_attempt():
    plan = _plan()
    service, store = _service_with_store(plan=plan)

    # Approval was captured while the target existed. Simulate the target
    # disappearing before the execution submission revalidation.
    service._patching._vulnerability = _EmptyVulnerabilityService()

    assert service.plan_eligibility(plan["plan_id"]) == {
        "executable": False,
        "ineligibility_reason": "target_not_found",
    }

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert result["status"] == "failed"
    assert result["outcome"] == "failed"
    assert result["failure_details"] == "No patch target matches this plan's resource"
    record = store.get(result["execution_id"])
    assert record["status"] == "failed"
    assert record["attempts"][0]["status"] == "failed"
    assert record["attempts"][0]["transitions"][-1]["status"] == "failed"


def _service_without_plan_repository(
    *, adapter=None
) -> RemediationExecutionService:
    """A service with no plan repository at all (CR-06 fail-closed guards)."""
    vulnerability_service = _FakeVulnerabilityService(TARGET_ID)
    patching_service = PatchingService(
        vulnerability_service,
        adapter=adapter or RecordingPatchExecutionAdapter(),
        require_human_approval=False,
    )
    return RemediationExecutionService(
        plan_repository=None,
        patching_service=patching_service,
        execution_store=RemediationExecutionStore(),
        now=lambda: NOW,
    )


def test_execute_never_raises_attribute_error_when_plan_repository_unavailable():
    service = _service_without_plan_repository()

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute("RMP-0001", requested_by="operator@example.com")

    assert excinfo.value.reason == "plan_repository_unavailable"


def test_retry_never_raises_attribute_error_when_plan_repository_unavailable():
    service = _service_without_plan_repository()
    queued, _ = service._store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=_execution_snapshot(_plan()),
    )
    service._store.transition(
        queued["execution_id"],
        expected_revision=int(queued.get("revision") or 0),
        expected_status="queued",
        status="failed",
        actor="operator@example.com",
        now=NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(queued["execution_id"])

    assert excinfo.value.reason == "plan_repository_unavailable"


def test_plan_eligibility_never_raises_attribute_error_when_plan_repository_unavailable():
    service = _service_without_plan_repository()

    assert service.plan_eligibility("RMP-0001") == {
        "executable": False,
        "ineligibility_reason": "plan_repository_unavailable",
    }


def _service_with_store(
    *,
    plan: dict | None,
    adapter=None,
    execution_store: RemediationExecutionStore | None = None,
    require_human_approval: bool = False,
) -> tuple[RemediationExecutionService, RemediationExecutionStore]:
    store = execution_store or RemediationExecutionStore()
    vulnerability_service = _FakeVulnerabilityService(TARGET_ID)
    patching_service = PatchingService(
        vulnerability_service,
        adapter=adapter or RecordingPatchExecutionAdapter(),
        require_human_approval=require_human_approval,
    )
    repository = PlanRepository()
    if plan is not None:
        repository.replace_generation([_full_plan(plan)])
        _approve(repository.decisions, _full_plan(plan))
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        now=lambda: NOW,
    )
    return service, store


def test_orphaned_executions_reports_none_for_a_healthy_store():
    plan = _plan()
    service, _store = _service_with_store(plan=plan)
    service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert service.orphaned_executions() == []


def test_orphaned_executions_flags_a_legacy_record_with_no_resolvable_plan_or_scope():
    service, store = _service_with_store(plan=None)
    legacy = store.create("RMP-does-not-exist", requested_by="legacy@example.com")

    orphans = service.orphaned_executions()

    assert len(orphans) == 1
    assert orphans[0]["execution_id"] == legacy["execution_id"]
    assert orphans[0]["plan_id"] == "RMP-does-not-exist"
    assert orphans[0]["status"] == legacy["status"]
    assert orphans[0]["reason"] == "legacy_scope_unresolvable"


def test_orphaned_executions_does_not_flag_an_unresolvable_plan_with_derivable_scope():
    service, store = _service_with_store(plan=None)
    snapshot = _execution_snapshot(_plan())
    store.create_or_get(
        "RMP-does-not-exist",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=snapshot,
    )

    # No stored scope_attributes, but the execution_snapshot's target_id
    # still yields a derivable subscription -- reconcilable, not orphaned.
    assert service.orphaned_executions() == []


def test_orphaned_executions_reports_plan_repository_unavailable_reason():
    service = _service_without_plan_repository()
    legacy = service._store.create("RMP-0001", requested_by="legacy@example.com")

    orphans = service.orphaned_executions()

    assert len(orphans) == 1
    assert orphans[0]["execution_id"] == legacy["execution_id"]
    assert orphans[0]["reason"] == "plan_repository_unavailable"


def test_execution_store_persists_record_surviving_round_trip(tmp_path):
    path = tmp_path / "executions.json"
    store = RemediationExecutionStore(path=path)
    record = store.create("RMP-0001", requested_by="operator@example.com")

    assert record["plan_id"] == "RMP-0001"
    assert record["status"] == "queued"
    assert record["requested_by"] == "operator@example.com"
    for field in (
        "execution_id",
        "plan_id",
        "status",
        "requested_by",
        "approved_by",
        "created_at",
        "updated_at",
        "provider_job_id",
        "message",
        "attempt_count",
        "rollback_guidance",
    ):
        assert field in record

    reread_store = RemediationExecutionStore(path=path)
    reread = reread_store.get(record["execution_id"])
    assert reread == record


def test_execution_store_rejects_concurrent_execution_for_same_plan():
    store = RemediationExecutionStore()
    first = store.create("RMP-0001", requested_by="operator@example.com")

    second = store.create("RMP-0001", requested_by="operator2@example.com")

    assert second["execution_id"] == first["execution_id"]


@pytest.mark.parametrize(
    "status",
    ["queued", "running", "retrying", "failed", "cancelled", "succeeded"],
)
def test_same_approval_execution_identity_is_idempotent_after_every_status(status):
    store = RemediationExecutionStore()
    snapshot = _execution_snapshot(_plan())
    first, created = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-APPROVAL-1",
        execution_snapshot=snapshot,
    )
    assert created is True
    store.update(first["execution_id"], status=status)

    second, created = store.create_or_get(
        "RMP-0001",
        requested_by="other@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-APPROVAL-1",
        execution_snapshot=snapshot,
    )

    assert created is False
    assert second["execution_id"] == first["execution_id"]


@pytest.mark.parametrize(
    ("status", "failure_class"),
    [
        ("failed", "provider_rejected"),
        ("cancelled", "operator_cancelled"),
        ("succeeded", ""),
    ],
)
def test_fresh_approval_creates_execution_after_terminal_non_ambiguous_status(
    status,
    failure_class,
):
    store = RemediationExecutionStore()
    snapshot = _execution_snapshot(_plan())
    first, _ = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-APPROVAL-1",
        execution_snapshot=snapshot,
    )
    store.update(
        first["execution_id"],
        status=status,
        failure_class=failure_class,
    )

    second, created = store.create_or_get(
        "RMP-0001",
        requested_by="other@example.com",
        approved_by="approver2@example.com",
        approval_decision_id="RMD-APPROVAL-2",
        execution_snapshot=snapshot,
    )

    assert created is True
    assert second["execution_id"] != first["execution_id"]
    assert second["approval_decision_id"] == "RMD-APPROVAL-2"


def test_fresh_approval_creates_execution_after_reconciled_incomplete_terminal():
    store = RemediationExecutionStore()
    snapshot = _execution_snapshot(_plan())
    first, _ = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-APPROVAL-1",
        execution_snapshot=snapshot,
    )
    store.update(
        first["execution_id"],
        status="succeeded",
        evidence_reconciliation={
            "status": "reconciled_incomplete",
            "kbs_cleared": [],
            "kbs_remaining": ["KB600001"],
            "assessed_at": NOW.isoformat(),
        },
    )

    second, created = store.create_or_get(
        "RMP-0001",
        requested_by="other@example.com",
        approved_by="approver2@example.com",
        approval_decision_id="RMD-APPROVAL-2",
        execution_snapshot=snapshot,
    )

    assert created is True
    assert second["execution_id"] != first["execution_id"]


@pytest.mark.parametrize("status", ["queued", "running", "retrying"])
def test_fresh_approval_is_blocked_by_related_active_execution(status):
    store = RemediationExecutionStore()
    snapshot = _execution_snapshot(_plan())
    first, _ = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-APPROVAL-1",
        execution_snapshot=snapshot,
    )
    if status != "queued":
        store.update(first["execution_id"], status=status)

    second, created = store.create_or_get(
        "RMP-0001",
        requested_by="other@example.com",
        approved_by="approver2@example.com",
        approval_decision_id="RMD-APPROVAL-2",
        execution_snapshot=snapshot,
    )

    assert created is False
    assert second["execution_id"] == first["execution_id"]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_fresh_approval_is_blocked_by_any_related_submission_ambiguity(status):
    store = RemediationExecutionStore()
    snapshot = _execution_snapshot(_plan())
    first, _ = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-APPROVAL-1",
        execution_snapshot=snapshot,
    )
    store.update(
        first["execution_id"],
        status=status,
        failure_class="submission_ambiguous",
    )

    second, created = store.create_or_get(
        "RMP-0001",
        requested_by="other@example.com",
        approved_by="approver2@example.com",
        approval_decision_id="RMD-APPROVAL-2",
        execution_snapshot=snapshot,
    )

    assert created is False
    assert second["execution_id"] == first["execution_id"]


def test_empty_decision_id_preserves_legacy_three_part_identity():
    store = RemediationExecutionStore()
    snapshot = _execution_snapshot(_plan())

    record, created = store.create_or_get(
        "RMP-0001",
        requested_by="legacy@example.com",
        approved_by="",
        execution_snapshot=snapshot,
    )

    assert created is True
    assert record["execution_identity"] == (
        f"RMP-0001|{snapshot['snapshot_hash']}|{snapshot['action_version']}"
    )
    assert record["approval_decision_id"] == ""
    assert record["approval_decided_at"] == ""


def test_legacy_terminal_execution_requires_provably_later_approval():
    store = RemediationExecutionStore()
    snapshot = _execution_snapshot(_plan())
    legacy, created = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=snapshot,
        now=NOW,
    )
    assert created is True
    terminal_at = NOW + timedelta(minutes=5)
    store.update(legacy["execution_id"], status="succeeded", now=terminal_at)

    repeated, created = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-LEGACY-APPROVAL",
        approval_decided_at=(NOW - timedelta(minutes=1)).isoformat(),
        execution_snapshot=snapshot,
        now=terminal_at + timedelta(minutes=1),
    )

    assert created is False
    assert repeated["execution_id"] == legacy["execution_id"]

    fresh_decided_at = terminal_at + timedelta(minutes=2)
    fresh, created = store.create_or_get(
        "RMP-0001",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        approval_decision_id="RMD-FRESH-APPROVAL",
        approval_decided_at=fresh_decided_at.isoformat(),
        execution_snapshot=snapshot,
        now=fresh_decided_at + timedelta(seconds=1),
    )

    assert created is True
    assert fresh["execution_id"] != legacy["execution_id"]
    assert fresh["approval_decision_id"] == "RMD-FRESH-APPROVAL"
    assert fresh["approval_decided_at"] == fresh_decided_at.isoformat()


def test_service_resubmits_same_snapshot_only_after_fresh_terminal_approval():
    plan = _plan()
    adapter = RecordingPatchExecutionAdapter()
    service, store = _service_with_store(plan=plan, adapter=adapter)

    first = service.execute(plan["plan_id"], requested_by="operator@example.com")
    repeated = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert repeated["execution_id"] == first["execution_id"]
    assert len(adapter.submissions) == 1

    store.update(
        first["execution_id"],
        status="succeeded",
        evidence_reconciliation={
            "status": "reconciled_incomplete",
            "kbs_cleared": [],
            "kbs_remaining": ["KB600001"],
            "assessed_at": NOW.isoformat(),
        },
    )
    fresh_decision = _approve(
        service._plans.decisions,
        _full_plan(plan),
        execution_snapshot=first["execution_snapshot"],
        now=NOW + timedelta(seconds=1),
    )

    second = service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert second["execution_id"] != first["execution_id"]
    assert second["approval_decision_id"] == fresh_decision["decision_id"]
    assert len(adapter.submissions) == 2


def test_execute_persists_running_until_authoritative_terminal_verification():
    plan = _plan()
    store = RemediationExecutionStore()
    service, store = _service_with_store(plan=plan, execution_store=store)

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    execution = store.get(result["execution_id"])
    assert execution["status"] == "running"
    assert execution["plan_id"] == plan["plan_id"]


def test_execute_failure_persists_failed_status_with_message():
    plan = _plan()

    class _FailingAdapter:
        name = "failing"

        def submit(self, run, target):
            raise PatchExecutionUnavailable("No execution identity configured")

    service, store = _service_with_store(plan=plan, adapter=_FailingAdapter())

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    execution = store.get(result["execution_id"])
    assert execution["status"] == "failed"
    assert "No execution identity configured" in execution["message"]


def test_two_services_sharing_local_store_submit_once(tmp_path):
    path = tmp_path / "state" / "remediation_executions.json"
    adapter = RecordingPatchExecutionAdapter()
    plan = _plan()
    first, _ = _service_with_store(
        plan=plan,
        adapter=adapter,
        execution_store=RemediationExecutionStore(path=path),
    )
    second, _ = _service_with_store(
        plan=plan,
        adapter=adapter,
        execution_store=RemediationExecutionStore(path=path),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda service: service.execute(
                    plan["plan_id"], requested_by="operator@example.com"
                ),
                (first, second),
            )
        )

    assert results[0]["execution_id"] == results[1]["execution_id"]
    assert len(adapter.submissions) == 1


def test_duplicate_execute_after_failure_never_resubmits():
    plan = _plan()

    class _FailingAdapter:
        name = "failing"

        def __init__(self):
            self.calls = 0

        def submit(self, run, target):
            self.calls += 1
            raise PatchExecutionUnavailable("ambiguous provider failure")

    adapter = _FailingAdapter()
    service, _ = _service_with_store(plan=plan, adapter=adapter)

    first = service.execute(plan["plan_id"], requested_by="operator@example.com")
    second = service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert first["execution_id"] == second["execution_id"]
    assert adapter.calls == 1


def _full_plan(plan: dict) -> dict:
    """Fill in the fields PlanRepository/PlanRepository.decisions expect."""
    return {
        "title": "Controlled patch and failed-update recovery",
        "risk_assessment": {"overall_risk": {"level": "High", "drivers": []}},
        "approval_requirements": [],
        "execution_steps": [],
        "application": "Payments API",
        "business_service": "Checkout",
        "business_decision": _eligible_business_decision(),
        "evidence_citations": [{"source_type": "assessment", "source_id": "assess-001"}],
        **plan,
    }


# --- Plan 03.4-02 Task 1: deadline-first poll_verification ------------------


def test_execute_sets_verification_deadline_and_next_verification_at():
    plan = _plan()
    service, store = _service_with_store(plan=plan)

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    record = store.get(result["execution_id"])
    assert record["status"] == "running"
    assert record["verification_deadline_at"] == (
        NOW + timedelta(seconds=VERIFICATION_DEADLINE_SECONDS)
    ).isoformat()
    assert record["next_verification_at"] == NOW.isoformat()
    assert record["verification_attempts"] == 0


def test_poll_verification_past_deadline_terminates_without_touching_verifier():
    plan = _plan()
    service, store = _service_with_store(plan=plan)
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    service._now = lambda: NOW + timedelta(seconds=VERIFICATION_DEADLINE_SECONDS + 1)
    polled = service.poll_verification(execution_id)

    assert polled["status"] == "failed"
    assert polled["outcome"] == "unknown"
    assert polled["failure_class"] == "verification_timed_out"
    assert polled["verified_state"] == "verification_deadline_exceeded"
    assert polled["failure_details"]
    stored = store.get(execution_id)
    assert stored["status"] == "failed"
    assert stored["attempts"][-1]["failure_class"] == "verification_timed_out"


def test_poll_verification_before_deadline_bumps_attempts_and_backoff():
    plan = _plan()
    store = RemediationExecutionStore()
    repository = PlanRepository()
    repository.replace_generation([_full_plan(plan)])
    _approve(repository.decisions, _full_plan(plan))
    vulnerability_service = _FakeVulnerabilityService(TARGET_ID)
    patching_service = PatchingService(
        vulnerability_service,
        adapter=RecordingPatchExecutionAdapter(),
        require_human_approval=False,
    )

    class _StillRunningVerifier:
        def verify(self, execution_record):
            return {"verifiable": True, "outcome": "running", "verified_state": "InProgress"}

    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=_StillRunningVerifier(),
        now=lambda: NOW,
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    polled = service.poll_verification(execution_id)

    assert polled["status"] == "running"
    assert polled["verification_attempts"] == 1
    assert polled["next_verification_at"] == (NOW + timedelta(seconds=5)).isoformat()


def test_poll_verification_with_empty_deadline_is_never_timed_out(tmp_path):
    path = tmp_path / "state" / "remediation_executions.json"
    plan = _plan()
    service, _store = _service_with_store(
        plan=plan, execution_store=RemediationExecutionStore(path=path)
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    payload = json.loads(path.read_text(encoding="utf-8"))
    for execution in payload["executions"]:
        if execution["execution_id"] == execution_id:
            execution["verification_deadline_at"] = ""
    path.write_text(json.dumps(payload), encoding="utf-8")

    reread_store = RemediationExecutionStore(path=path)
    service._store = reread_store
    service._now = lambda: NOW + timedelta(days=365)
    polled = service.poll_verification(execution_id)

    assert polled["status"] == "running"


# --- Plan 03.5-05: per-role satisfaction and cross-family self-approval ----


class _RecordingDefenderConfigurationAdapter:
    """Test-only defender configuration adapter that records submissions."""

    def __init__(self) -> None:
        self.state = {"pricingTier": "Free"}
        self.submissions: list[dict] = []

    def inspect(self, request: dict) -> dict:
        import hashlib
        import json as _json

        digest = hashlib.sha256(
            _json.dumps(self.state, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return {"etag": '"v1"', "state_hash": digest, "properties": self.state}

    def submit(self, snapshot: dict) -> DefenderConfigurationResult:
        self.submissions.append(snapshot)
        return DefenderConfigurationResult(
            provider="recording",
            provider_job_id=(
                "https://management.azure.com"
                f"{snapshot['request']['path']}?api-version=2024-01-01"
            ),
            state="submitted",
            message="recorded",
        )


def _defender_plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-CONFIG-1",
        "action_id": ENABLE_DEFENDER_SERVERS_P1,
        "action_version": "v1",
        "resource_key": VM_DEFENDER_ID,
        "resource": {"id": VM_DEFENDER_ID, "name": "vm-1"},
        "approval_requirements": [],
        "business_decision": {
            "disposition": "schedule",
            "business_impact": {"status": "known"},
            "review_requirements": [],
            "unknowns": [],
            "urgency_rationale": {"evidence_citations": ["assessment:assessment-1"]},
        },
        "evidence_citations": [
            {"source_type": "assessment", "source_id": "assessment-1"}
        ],
        "rollback_plan": {
            "rollback_actions": ["Restore the captured prior pricing configuration."]
        },
    }
    plan.update(overrides)
    return plan


VM_DEFENDER_ID = (
    "/subscriptions/sub-1/resourceGroups/rg/providers/"
    "Microsoft.Compute/virtualMachines/vm-1"
)


def _defender_service(
    plan: dict, *, allow_self_approval=False
) -> tuple[RemediationExecutionService, _RecordingDefenderConfigurationAdapter, PlanRepository]:
    repository = PlanRepository()
    repository.replace_generation([plan])
    adapter = _RecordingDefenderConfigurationAdapter()
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=None,
        defender_configuration_adapter=adapter,
        execution_store=RemediationExecutionStore(),
        allow_self_approval=allow_self_approval,
        now=lambda: NOW,
    )
    return service, adapter, repository


def _approve_defender(
    service: RemediationExecutionService,
    repository: PlanRepository,
    plan: dict,
    *,
    approver: str = "security@example.com",
    approver_roles: list[str] = (),
) -> dict:
    snapshot = service.build_execution_snapshot(
        plan, scope=None
    )
    return repository.decisions.append(
        plan=plan,
        decision="approved",
        approver=approver,
        reason="Approved exact Defender configuration",
        scope={},
        action_version=plan["action_version"],
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=snapshot,
        approver_roles=list(approver_roles),
        now=NOW,
    )


def test_two_role_approval_requirements_cannot_be_satisfied_by_one_wrong_role_decision() -> None:
    plan = _full_plan(
        _plan(
            approval_requirements=[
                {
                    "policy_id": "change-control",
                    "role": "Change Manager",
                    "stage": "Planning",
                    "approval_evidence_required": [],
                },
                {
                    "policy_id": "security-review",
                    "role": "Security Response Owner",
                    "stage": "Planning",
                    "approval_evidence_required": [],
                },
            ]
        )
    )
    repository = PlanRepository()
    repository.replace_generation([plan])
    repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="security@example.com",
        reason="Security sign-off only",
        scope={},
        action_version=plan["action_version"],
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=_execution_snapshot(plan),
        approver_roles=["Security Response Owner"],
        now=NOW,
    )
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

    assert excinfo.value.reason == "approval_requirements_unmet"
    unmet_roles = {row["role"] for row in excinfo.value.details["unmet"]}
    assert unmet_roles == {"Change Manager"}


@pytest.mark.parametrize("family", ["patch", "defender"])
def test_self_approval_refused_for_both_families_when_disallowed(family: str) -> None:
    if family == "patch":
        plan = _full_plan(_plan())
        repository = PlanRepository()
        repository.replace_generation([plan])
        repository.decisions.append(
            plan=plan,
            decision="approved",
            approver="operator@example.com",
            reason="Self-approved",
            scope={},
            action_version=plan["action_version"],
            expires_at=(NOW + timedelta(days=1)).isoformat(),
            execution_snapshot=_execution_snapshot(plan),
            now=NOW,
        )
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
    else:
        plan = _defender_plan()
        service, adapter, repository = _defender_service(plan)
        _approve_defender(service, repository, plan, approver="operator@example.com")

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "self_approval_not_permitted"
    assert adapter.submissions == []


def test_self_approval_allowed_is_durably_recorded_on_the_decision() -> None:
    plan = _defender_plan()
    service, adapter, repository = _defender_service(plan, allow_self_approval=True)
    recorded = _approve_defender(
        service, repository, plan, approver="operator@example.com"
    )

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert result["status"] == "running"
    assert len(adapter.submissions) == 1

    decisions = repository.decisions.list(plan["plan_id"])
    matching = [
        row for row in decisions if row["decision_id"] == recorded["decision_id"]
    ]
    assert len(matching) == 1
    assert matching[0]["self_approved"] is True
    assert matching[0]["self_approval_policy_id"] != ""
