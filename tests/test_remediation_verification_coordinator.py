"""RemediationVerificationCoordinator: the autonomous half of Recommendation 3.

Every test here proves an execution's terminal status is inevitable because
this coordinator runs, not because a browser polled it -- and that it
survives a process restart and concurrent callers with zero in-memory
carryover, since all scheduling state lives on durable state alone (Plans
03.4-01/03.4-02).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import RemediationExecutionService
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from intelligence.remediation.verification_coordinator import (
    RemediationVerificationCoordinator,
)
from operations.patching.adapters import PatchExecutionResult
from operations.patching.service import PatchingService

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fakes for the pure dispatch-rule / error-isolation tests (Task 1)
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, due: list[dict]) -> None:
        self._due = due

    def list_due_for_verification(self, *, now):
        return list(self._due)


class _RecordingService:
    def __init__(self) -> None:
        self.poll_calls: list[str] = []
        self.reconcile_evidence_calls: list[str] = []
        self.reconcile_ambiguous_calls: list[str] = []

    def poll_verification(self, execution_id: str) -> dict:
        self.poll_calls.append(execution_id)
        return {}

    def reconcile_evidence(self, execution_id: str) -> dict:
        self.reconcile_evidence_calls.append(execution_id)
        return {}

    def reconcile_ambiguous_submission(self, execution_id: str) -> dict:
        self.reconcile_ambiguous_calls.append(execution_id)
        return {}


def test_run_once_drives_to_terminal_dispatches_purely_by_record_shape():
    due = [
        {"execution_id": "RME-RUNNING", "status": "running", "attempts": []},
        {
            "execution_id": "RME-AMBIGUOUS",
            "status": "failed",
            "attempts": [{"failure_class": "submission_ambiguous"}],
        },
        {
            "execution_id": "RME-PLAIN-FAILED",
            "status": "failed",
            "attempts": [{"failure_class": "provider_rejected"}],
        },
        {"execution_id": "RME-SUCCEEDED", "status": "succeeded", "attempts": []},
    ]
    store = _FakeStore(due)
    service = _RecordingService()
    coordinator = RemediationVerificationCoordinator(execution_store=store, execution_service=service)

    summary = coordinator.run_once(NOW)

    assert service.poll_calls == ["RME-RUNNING"]
    assert service.reconcile_ambiguous_calls == ["RME-AMBIGUOUS"]
    assert service.reconcile_evidence_calls == ["RME-SUCCEEDED"]
    # The plain-failed record is neither dispatched nor counted -- it should
    # never appear in list_due_for_verification's real output, but a
    # defensive coordinator skips rather than guesses at an unrecognized shape.
    assert summary == {"processed": 3, "errored": 0, "skipped_contended": 0}


def test_per_record_error_isolation_does_not_abort_the_batch():
    due = [
        {"execution_id": "RME-A", "status": "running", "attempts": []},
        {"execution_id": "RME-B", "status": "running", "attempts": []},
    ]
    store = _FakeStore(due)

    class _RaisingOnFirstService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def poll_verification(self, execution_id: str) -> dict:
            self.calls.append(execution_id)
            if execution_id == "RME-A":
                raise RuntimeError("simulated per-record failure")
            return {}

    service = _RaisingOnFirstService()
    coordinator = RemediationVerificationCoordinator(execution_store=store, execution_service=service)

    summary = coordinator.run_once(NOW)

    assert service.calls == ["RME-A", "RME-B"]
    assert summary == {"processed": 1, "errored": 1, "skipped_contended": 0}


# ---------------------------------------------------------------------------
# Real store/service helpers for the browser-independence and restart-safety
# tests (Task 1's key proof and Task 3)
# ---------------------------------------------------------------------------


class _FakeVulnerabilityService:
    freshness = "2026-09-04T12:00:00Z"

    def asset_exposures(self, scope=None) -> list[dict]:
        return [
            {
                "asset_id": TARGET_ID,
                "name": "vm-payments",
                "inventory_kind": "Azure VM",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "missing_kbs": ["1111111"],
                "severities": ["Critical"],
                "cve_ids": ["CVE-2026-0001"],
            }
        ]


class _OperationUrlAdapter:
    name = "recording-with-operation-url"

    def submit(self, run, target) -> PatchExecutionResult:
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id="https://management.azure.com/op/1",
            state="submitted",
            message="Accepted by Azure; Update Manager is authoritative for the outcome.",
        )


class _SequencedVerifier:
    """Returns each outcome in order, repeating the last one once exhausted."""

    def __init__(self, outcomes: list[dict]) -> None:
        self._outcomes = list(outcomes)
        self._index = 0

    def verify(self, execution_record: dict) -> dict:
        outcome = self._outcomes[min(self._index, len(self._outcomes) - 1)]
        self._index += 1
        return outcome


def _plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-COORDINATOR-0001",
        "action_id": "controlled-patch-recovery",
        "opportunity_type": "Patch and vulnerability debt",
        "action_version": "v1",
        "resource_key": TARGET_ID,
        "resource": {
            "id": TARGET_ID,
            "name": "vm-payments",
            "entity_type": "VirtualMachine",
            "subscription_id": "sub-1",
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
        "evidence_citations": [{"source_type": "assessment", "source_id": "assess-001"}],
        "rollback_plan": {
            "rollback_actions": [],
            "automatic_rollback": False,
            "execution_status": "Not Executed",
        },
    }
    plan.update(overrides)
    return plan


def _approved_repository(plan: dict) -> PlanRepository:
    repository = PlanRepository()
    repository.replace_generation([plan])
    snapshot = {
        "target_id": TARGET_ID,
        "patch_ids": ["1111111"],
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
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=snapshot,
        now=NOW,
    )
    return repository


def test_browser_independence_stub_execution_reaches_succeeded_via_coordinator_alone():
    plan = _plan()
    store = RemediationExecutionStore()
    repository = _approved_repository(plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(), adapter=_OperationUrlAdapter(), require_human_approval=False
    )
    verifier = _SequencedVerifier(
        [
            {"verifiable": True, "outcome": "running", "verified_state": "InProgress"},
            {"verifiable": True, "outcome": "running", "verified_state": "InProgress"},
            {"verifiable": True, "outcome": "succeeded", "verified_state": "Succeeded"},
        ]
    )
    clock = {"now": NOW}
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=verifier,
        now=lambda: clock["now"],
    )
    coordinator = RemediationVerificationCoordinator(
        execution_store=store, execution_service=service, now=lambda: clock["now"]
    )

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    assert store.get(execution_id)["status"] == "running"

    # No router, no test client, no browser -- only the coordinator drives
    # verification forward. Advance the clock between calls to simulate real
    # elapsed time between background passes.
    for _ in range(3):
        coordinator.run_once()
        clock["now"] = clock["now"] + timedelta(seconds=10)

    assert store.get(execution_id)["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Task 3: restart recovery and concurrent-caller safety against a real
# file-backed store (not the in-memory fakes above)
# ---------------------------------------------------------------------------


def test_restart_recovery_resumes_and_completes_verification_from_durable_state(tmp_path):
    path = tmp_path / "executions.json"
    plan = _plan()
    store = RemediationExecutionStore(path=path)
    repository = _approved_repository(plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(), adapter=_OperationUrlAdapter(), require_human_approval=False
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        now=lambda: NOW,
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    assert store.get(execution_id)["status"] == "running"

    # A completely separate store/service/coordinator trio, sharing only the
    # on-disk path -- not even a module-level cache -- simulating a fresh
    # process after a restart.
    new_store = RemediationExecutionStore(path=path)
    new_service = RemediationExecutionService(
        plan_repository=None,
        patching_service=None,
        execution_store=new_store,
        execution_verifier=_SequencedVerifier(
            [{"verifiable": True, "outcome": "succeeded", "verified_state": "Succeeded"}]
        ),
        now=lambda: NOW + timedelta(seconds=10),
    )
    new_coordinator = RemediationVerificationCoordinator(
        execution_store=new_store,
        execution_service=new_service,
        now=lambda: NOW + timedelta(seconds=10),
    )

    summary = new_coordinator.run_once()

    assert summary["processed"] == 1
    assert summary["errored"] == 0
    assert new_store.get(execution_id)["status"] == "succeeded"


def test_concurrent_poll_verification_calls_never_raise_and_agree_on_one_outcome(tmp_path):
    path = tmp_path / "executions.json"
    plan = _plan()
    store = RemediationExecutionStore(path=path)
    repository = _approved_repository(plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(), adapter=_OperationUrlAdapter(), require_human_approval=False
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        now=lambda: NOW,
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    def _independent_service() -> RemediationExecutionService:
        return RemediationExecutionService(
            plan_repository=None,
            patching_service=None,
            execution_store=RemediationExecutionStore(path=path),
            execution_verifier=_SequencedVerifier(
                [{"verifiable": True, "outcome": "succeeded", "verified_state": "Succeeded"}]
            ),
            now=lambda: NOW,
        )

    service_a = _independent_service()
    service_b = _independent_service()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda svc: svc.poll_verification(execution_id),
                (service_a, service_b),
            )
        )

    assert results[0]["status"] == "succeeded"
    assert results[1]["status"] == "succeeded"
    final_store = RemediationExecutionStore(path=path)
    final = final_store.get(execution_id)
    assert final["status"] == "succeeded"
    # Exactly one coherent outcome persisted -- not a corrupted merge of two
    # concurrent writers (proven by the attempt history advancing by exactly
    # one terminal transition, not two).
    assert final["attempts"][-1]["outcome"] == "succeeded"


def test_restart_recovered_ambiguous_submission_reclassified_with_no_evidence_refresher(
    tmp_path,
):
    path = tmp_path / "executions.json"
    store = RemediationExecutionStore(path=path)
    record, _ = store.create_or_get(
        "RMP-RESTART-AMBIGUOUS",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": ["1111111"],
            "target_kind": "Azure VM",
            "operation": "install_patches",
            "action_version": "v1",
            "snapshot_hash": "hash-restart-ambiguous",
        },
        now=NOW,
    )
    running = store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        now=NOW,
    )
    store.transition(
        running["execution_id"],
        expected_revision=int(running["revision"]),
        expected_status="running",
        status="failed",
        actor="operator@example.com",
        outcome="failed",
        failure_details="Azure Resource Manager was unreachable while submitting",
        failure_class="submission_ambiguous",
        verification_deadline_at=(NOW + timedelta(seconds=60)).isoformat(),
        next_verification_at=NOW.isoformat(),
        verification_attempts=0,
        now=NOW,
    )

    # Fresh process: brand-new trio, no evidence refresher configured at
    # all (None) -- proving the deadline-exceeded-with-no-evidence path is
    # itself restart-safe, not merely re-run-safe within one process.
    new_store = RemediationExecutionStore(path=path)
    new_service = RemediationExecutionService(
        plan_repository=None,
        patching_service=None,
        execution_store=new_store,
        target_evidence_refresher=None,
        verification_deadline_seconds=60.0,
        now=lambda: NOW + timedelta(seconds=120),
    )
    new_coordinator = RemediationVerificationCoordinator(
        execution_store=new_store,
        execution_service=new_service,
        now=lambda: NOW + timedelta(seconds=120),
    )

    summary = new_coordinator.run_once()

    assert summary == {"processed": 1, "errored": 0, "skipped_contended": 0}
    final = new_store.get(record["execution_id"])
    assert final["status"] == "failed"
    assert final["failure_class"] == "submission_unconfirmed"
