"""Operator self-service ``abandon`` recovery for a safe, quiescent SRE request.

Distinct from :meth:`RemediationExecutionService.cancel`: `abandon` never
contacts the Azure SRE Agent to reject/cancel anything. It only ends this
repo's own local tracking of a running execution once a *fresh* verification
proves the thread has no pending approval, no approval record of any status,
no submitted provider operation, no typed active incident/action, and no
success evidence -- i.e. nothing an operator could still be waiting on. Every
ambiguous or unconfirmable case must fail closed and leave the execution
unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import (
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import (
    RemediationExecutionStore,
)
from intelligence.remediation.execution_verifier import ExecutionVerificationUnavailable
from intelligence.remediation.plan_repository import PlanRepository
from operations.patching.adapters import PatchExecutionResult
from operations.patching.service import PatchingService

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
THREAD_URL = "https://sre-agent.example.azure.com/api/v1/threads/thread-abandon-1"


class _FakeVulnerabilityService:
    def __init__(self) -> None:
        self.freshness = "2026-09-21T08:00:00Z"

    def asset_exposures(self, scope=None) -> list[dict]:
        return [
            {
                "asset_id": TARGET_ID,
                "name": "vm-payments",
                "inventory_kind": "Azure VM",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "missing_kbs": ["KB600001"],
                "severities": ["Critical"],
                "cve_ids": ["CVE-2026-0001"],
            }
        ]


class _NoopAdapter:
    name = "sre-agent"

    def submit(self, run, target) -> PatchExecutionResult:
        return PatchExecutionResult(
            provider="sre-agent",
            provider_job_id=THREAD_URL,
            state="submitted",
            message="Accepted by Azure SRE Agent",
        )


def _full_plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-ABANDON-0001",
        "action_id": "controlled-patch-recovery",
        "opportunity_type": "Patch and vulnerability debt",
        "action_version": "v1",
        "resource_key": TARGET_ID,
        "resource": {
            "id": TARGET_ID,
            "name": "vm-payments",
            "entity_type": "VirtualMachine",
        },
        "title": "Controlled patch and failed-update recovery",
        "risk_assessment": {"overall_risk": {"level": "High", "drivers": []}},
        "approval_requirements": [],
        "execution_steps": [],
        "application": "Payments API",
        "business_service": "Checkout",
        "business_decision": {
            "disposition": "act_now",
            "business_impact": {"status": "known"},
            "review_requirements": [],
            "unknowns": [],
            "urgency_rationale": {"evidence_citations": ["assessment:assess-001"]},
        },
        "evidence_citations": [
            {"source_type": "assessment", "source_id": "assess-001"}
        ],
        "rollback_plan": {
            "rollback_actions": ["Restore from last known-good snapshot"],
            "automatic_rollback": False,
            "execution_status": "Not Executed",
        },
    }
    plan.update(overrides)
    return plan


def _approve(repository: PlanRepository, plan: dict, *, expires_at: str = "") -> dict:
    snapshot = {
        "target_id": TARGET_ID,
        "patch_ids": ["KB600001"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": plan["action_version"],
    }
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="approver@example.com",
        reason="Approved for patch recovery",
        scope={},
        action_version=plan["action_version"],
        expires_at=expires_at or (NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=snapshot,
        now=NOW,
    )
    return snapshot


def _running_sre_execution(
    service: RemediationExecutionService,
    store: RemediationExecutionStore,
    plan: dict,
) -> dict:
    """Execute and manually seed the record into a running SRE-agent state.

    Mirrors ``test_remediation_execution_retry.py``'s
    ``test_running_sre_review_can_be_cancelled_then_retried`` pattern:
    execute against the default patching adapter, then move the record to
    the exact ``running``/``sre-agent``/thread-handle shape abandon
    requires, independent of whatever provider the fixture's adapter used.
    """
    execution = service.execute(plan["plan_id"], requested_by="operator@example.com")
    current = store.get(execution["execution_id"])
    return store.transition(
        execution["execution_id"],
        expected_revision=current["revision"],
        expected_status="running",
        status="running",
        actor="test",
        provider="sre-agent",
        provider_job_id=THREAD_URL,
        verification_evidence={},
        now=NOW,
    )


def _service(
    *, plan: dict
) -> tuple[RemediationExecutionService, RemediationExecutionStore, PlanRepository]:
    store = RemediationExecutionStore()
    repository = PlanRepository()
    repository.replace_generation([plan])
    _approve(repository, plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=_NoopAdapter(),
        require_human_approval=False,
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=None,
        now=lambda: NOW,
    )
    return service, store, repository


_QUIESCENT_EVIDENCE = {
    "thread_status": {
        "last_message_complete": True,
        "has_critical_actions": False,
        "has_warning_actions": False,
        "incident_status": "",
    },
}


class _QuiescentVerifier:
    """Reachable, blank-status thread with zero approvals -- the exact
    ``blocked_no_action``-shaped composite the debug session diagnosed."""

    def __init__(self, *, approvals: list[object] | None = ()) -> None:
        self.approvals = approvals
        self.verify_calls = 0
        self.read_approvals_calls = 0

    def verify(self, _record):
        self.verify_calls += 1
        return {
            "verifiable": True,
            "outcome": "running",
            "verified_state": "In Progress",
            "provider_active": True,
            "verification_evidence": _QUIESCENT_EVIDENCE,
        }

    def read_approvals(self, _record):
        self.read_approvals_calls += 1
        if self.approvals is None:
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent approval lookup returned HTTP 503.",
                capability="sre_agent_approval_read",
            )
        return list(self.approvals)


def test_abandon_terminalizes_a_quiescent_sre_request_without_provider_cancellation() -> (
    None
):
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    verifier = _QuiescentVerifier(approvals=[])
    service._verifier = verifier
    running = _running_sre_execution(service, store, plan)

    result = service.abandon(
        running["execution_id"], requested_by="operator@example.com"
    )

    assert result["status"] == "failed"
    assert result["outcome"] == "unknown"
    assert result["failure_class"] == "operator_abandoned_without_provider_cancellation"
    assert result["abandoned"] is True
    assert result["provider_cancelled"] is False
    assert result["provider_job_id"] == THREAD_URL
    assert result["execution_id"] == running["execution_id"]
    assert verifier.verify_calls == 1
    assert verifier.read_approvals_calls == 1

    stored = store.get(running["execution_id"])
    assert stored["status"] == "failed"
    assert stored["provider_job_id"] == THREAD_URL
    assert stored["next_verification_at"] == "" or not store.list_due_for_verification(
        now=NOW
    )


def test_abandoned_record_is_not_due_for_further_verification() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    service._verifier = _QuiescentVerifier(approvals=[])
    running = _running_sre_execution(service, store, plan)

    service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert running["execution_id"] not in {
        due["execution_id"] for due in store.list_due_for_verification(now=NOW)
    }


def test_abandoned_execution_no_longer_blocks_a_fresh_same_snapshot_execute() -> None:
    plan = _full_plan()
    service, store, repository = _service(plan=plan)
    service._verifier = _QuiescentVerifier(approvals=[])
    running = _running_sre_execution(service, store, plan)
    service.abandon(running["execution_id"], requested_by="operator@example.com")

    # A genuinely fresh approval decision for the same snapshot (a new
    # decision_id, as a real re-approval through the UI would record) --
    # not a re-read of the original decision that produced the now-
    # abandoned execution's own exact ``execution_identity``.
    original_decision = repository.decisions.list(plan["plan_id"])[-1]
    fresh_snapshot = dict(original_decision["execution_snapshot"])
    repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="approver@example.com",
        reason="Re-approved after abandoning the quiescent request",
        scope={},
        action_version=plan["action_version"],
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=fresh_snapshot,
        now=NOW + timedelta(minutes=5),
    )
    fresh_decision = repository.decisions.list(plan["plan_id"])[-1]
    assert fresh_decision["decision_id"] != original_decision["decision_id"]

    _record, claimed = store.create_or_get(
        plan["plan_id"],
        requested_by="operator2@example.com",
        approved_by="approver@example.com",
        approval_decision_id=str(fresh_decision["decision_id"]),
        approval_decided_at=str(fresh_decision["decided_at"]),
        execution_snapshot=fresh_snapshot,
        now=NOW + timedelta(minutes=5),
    )

    assert claimed is True


def test_abandon_refuses_when_approval_pending() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)

    class _PendingApprovalVerifier(_QuiescentVerifier):
        def verify(self, _record):
            self.verify_calls += 1
            return {
                "verifiable": True,
                "outcome": "running",
                "verified_state": "Pending Review",
                "provider_active": True,
                "verification_evidence": {"approval_pending": True},
            }

    verifier = _PendingApprovalVerifier()
    service._verifier = verifier
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "approval_pending"
    assert store.get(running["execution_id"])["status"] == "running"


def test_abandon_refuses_when_provider_operation_exists() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)

    class _SubmittedVerifier(_QuiescentVerifier):
        def verify(self, _record):
            self.verify_calls += 1
            return {
                "verifiable": True,
                "outcome": "running",
                "verified_state": "In Progress",
                "provider_active": True,
                "verification_evidence": {
                    "provider_operation": {
                        "operation_id": "op-1",
                        "status": "submitted",
                    },
                },
            }

    verifier = _SubmittedVerifier()
    service._verifier = verifier
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "provider_operation_exists"
    assert store.get(running["execution_id"])["status"] == "running"


@pytest.mark.parametrize(
    "thread_status",
    [
        {
            "last_message_complete": True,
            "has_critical_actions": False,
            "has_warning_actions": False,
            "incident_status": "blocked_no_action",
        },
        {
            "last_message_complete": True,
            "has_critical_actions": True,
            "has_warning_actions": False,
            "incident_status": "",
        },
        {
            "last_message_complete": True,
            "has_critical_actions": False,
            "has_warning_actions": True,
            "incident_status": "",
        },
    ],
)
def test_abandon_refuses_when_typed_active_incident_or_action_exists(
    thread_status,
) -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)

    class _TypedActiveVerifier(_QuiescentVerifier):
        def verify(self, _record):
            self.verify_calls += 1
            return {
                "verifiable": True,
                "outcome": "running",
                "verified_state": "In Progress",
                "provider_active": True,
                "verification_evidence": {"thread_status": thread_status},
            }

    verifier = _TypedActiveVerifier()
    service._verifier = verifier
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "typed_active_action_exists"
    assert store.get(running["execution_id"])["status"] == "running"


def test_abandon_refuses_when_any_approval_record_exists_regardless_of_status() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    verifier = _QuiescentVerifier(
        approvals=[{"id": "approval-1", "status": "Rejected"}]
    )
    service._verifier = verifier
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "approval_exists"
    assert store.get(running["execution_id"])["status"] == "running"


def test_abandon_fails_closed_when_approval_read_is_unavailable() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    verifier = _QuiescentVerifier(approvals=None)
    service._verifier = verifier
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "verification_unavailable"
    assert store.get(running["execution_id"])["status"] == "running"


def test_abandon_fails_closed_when_fresh_verification_is_unavailable() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)

    class _UnavailableVerifier:
        def verify(self, _record):
            raise ExecutionVerificationUnavailable(
                "Azure SRE Agent was unreachable while polling the execution thread.",
                capability="sre_agent_thread_poll",
            )

    service._verifier = _UnavailableVerifier()
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "verification_unavailable"
    assert store.get(running["execution_id"])["status"] == "running"


def test_abandon_refuses_when_no_verifier_is_configured() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "verification_unavailable"
    assert store.get(running["execution_id"])["status"] == "running"


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
def test_abandon_refuses_when_fresh_verification_is_already_terminal(
    outcome: str,
) -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)

    class _TerminalVerifier(_QuiescentVerifier):
        def verify(self, _record):
            self.verify_calls += 1
            return {
                "verifiable": True,
                "outcome": outcome,
                "verified_state": "Complete",
                "verification_evidence": {},
            }

    service._verifier = _TerminalVerifier()
    running = _running_sre_execution(service, store, plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "execution_already_terminal"
    assert store.get(running["execution_id"])["status"] == "running"


def test_abandon_refuses_a_non_sre_provider() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    service._verifier = _QuiescentVerifier(approvals=[])
    execution = service.execute(plan["plan_id"], requested_by="operator@example.com")
    current = store.get(execution["execution_id"])
    running = store.transition(
        execution["execution_id"],
        expected_revision=current["revision"],
        expected_status="running",
        status="running",
        actor="test",
        provider="azure-arm",
        provider_job_id="https://management.azure.com/some/operation",
        now=NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "execution_not_abandonable"


def test_abandon_refuses_a_non_running_status() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    service._verifier = _QuiescentVerifier(approvals=[])
    running = _running_sre_execution(service, store, plan)
    service.abandon(running["execution_id"], requested_by="operator@example.com")

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "execution_not_abandonable"


class _RacingVerifier(_QuiescentVerifier):
    """A verifier whose fresh check races a concurrent winner into the
    store between abandon's initial read and its own CAS write -- proving
    abandon's final transition is guarded exactly like every other
    lifecycle claim (CR-01/CAS-contention pattern)."""

    def __init__(self, store: RemediationExecutionStore) -> None:
        super().__init__(approvals=[])
        self._store = store

    def verify(self, record):
        self._store.transition(
            record["execution_id"],
            expected_revision=int(record["revision"]),
            expected_status="running",
            status="running",
            actor="execution-verifier",
            verified_state="In Progress",
            now=NOW,
        )
        return super().verify(record)


def test_abandon_is_race_safe_against_a_concurrent_transition() -> None:
    plan = _full_plan()
    service, store, _repository = _service(plan=plan)
    running = _running_sre_execution(service, store, plan)
    service._verifier = _RacingVerifier(store)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon(running["execution_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "execution_claim_conflict"
    assert store.get(running["execution_id"])["status"] == "running"


def test_abandon_refuses_when_store_not_configured() -> None:
    plan = _full_plan()
    repository = PlanRepository()
    repository.replace_generation([plan])
    _approve(repository, plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=_NoopAdapter(),
        require_human_approval=False,
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=None,
        now=lambda: NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon("RME-DOES-NOT-EXIST", requested_by="operator@example.com")

    assert excinfo.value.reason == "store_not_configured"


def test_abandon_refuses_unknown_execution_id() -> None:
    plan = _full_plan()
    service, _store, _repository = _service(plan=plan)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.abandon("RME-DOES-NOT-EXIST", requested_by="operator@example.com")

    assert excinfo.value.reason == "execution_not_found"


def test_execution_view_projects_can_abandon_for_a_quiescent_running_sre_record() -> (
    None
):
    view = RemediationExecutionService.execution_view(
        {
            "status": "running",
            "provider": "sre-agent",
            "provider_job_id": THREAD_URL,
            "provider_submitted": True,
            "verification_evidence": _QUIESCENT_EVIDENCE,
            "attempts": [],
        }
    )

    assert view["can_abandon"] is True
    assert view["abandon_ineligibility_reason"] == ""
    # Mutually exclusive with cancellable -- a quiescent thread the operator
    # can abandon must never simultaneously be provider-cancellable.
    assert view["cancellable"] is False


def test_execution_view_projects_can_abandon_false_for_pending_approval() -> None:
    view = RemediationExecutionService.execution_view(
        {
            "status": "running",
            "provider": "sre-agent",
            "provider_job_id": THREAD_URL,
            "provider_submitted": True,
            "verification_evidence": {"approval_pending": True},
            "attempts": [],
        }
    )

    assert view["can_abandon"] is False
    assert view["abandon_ineligibility_reason"] == "approval_pending"
    assert view["cancellable"] is True


def test_execution_view_projects_can_abandon_false_for_non_running_status() -> None:
    view = RemediationExecutionService.execution_view(
        {
            "status": "succeeded",
            "provider": "sre-agent",
            "provider_job_id": THREAD_URL,
            "provider_submitted": True,
            "verification_evidence": {},
            "attempts": [],
        }
    )

    assert view["can_abandon"] is False
    assert view["abandon_ineligibility_reason"] == "execution_not_abandonable"
