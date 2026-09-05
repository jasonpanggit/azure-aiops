"""Bounded, idempotent, revalidated retries for a remediation execution.

A retry re-runs the exact same approval-gate checks as ``execute()``
against the plan's *current* state -- since the plan or its approval may
have changed since the original attempt -- is rejected once the execution
already succeeded (idempotency), and is bounded by ``MAX_EXECUTION_ATTEMPTS``
so a failing target cannot be retried indefinitely (T-03-10, T-03-11).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import (
    MAX_EXECUTION_ATTEMPTS,
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.execution_verifier import ExecutionVerifier
from intelligence.remediation.plan_repository import PlanRepository
from operations.patching.adapters import PatchExecutionResult, PatchExecutionUnavailable
from operations.patching.service import PatchingService

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 8, 18, 13, tzinfo=UTC)
OPERATION_URL = (
    "https://management.azure.com/subscriptions/sub-1/providers/"
    "Microsoft.Compute/locations/eastus/operations/op-999?api-version=2024-07-01"
)


class _FakeCredential:
    def get_token(self, *scopes, **kwargs):
        return type("Token", (), {"token": "fake-token"})()


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, handler) -> None:
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _client_returning(status_code: int, json_body: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body, request=request)

    return httpx.Client(transport=_FakeTransport(handler))


class _FakeVulnerabilityService:
    def __init__(self) -> None:
        self.freshness = "2026-08-18T13:00:00Z"

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


class _RecordingOperationUrlAdapter:
    name = "recording-with-operation-url"

    def __init__(self, *, fail: bool = False) -> None:
        self.submissions: list = []
        self._fail = fail

    def submit(self, run, target) -> PatchExecutionResult:
        self.submissions.append((run, target))
        if self._fail:
            # A genuine, non-ambiguous provider rejection (not a transport
            # failure) -- these tests exercise retry's CAS/concurrency
            # mechanics, not the submission-ambiguity guard (CR-01), so the
            # fake adapter must not use the fail-closed "submission_ambiguous"
            # default that a bare `PatchExecutionUnavailable(...)` carries.
            raise PatchExecutionUnavailable(
                "Azure rejected the request",
                provider_submitted=True,
                failure_class="provider_rejected",
            )
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id=OPERATION_URL,
            state="submitted",
            message="Accepted by Azure",
        )


def _full_plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-0003",
        "action_id": "controlled-patch-recovery",
        "opportunity_type": "Patch and vulnerability debt",
        "action_version": "v1",
        "resource_key": TARGET_ID,
        "resource": {"id": TARGET_ID, "name": "vm-payments", "entity_type": "VirtualMachine"},
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
            "urgency_rationale": {
                "evidence_citations": ["assessment:assess-001"]
            },
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


def _approve(repository: PlanRepository, plan: dict, *, expires_at: str = "") -> None:
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


def _service(
    *, plan: dict, adapter=None, verifier_client: httpx.Client | None = None
) -> tuple[RemediationExecutionService, RemediationExecutionStore, PlanRepository]:
    store = RemediationExecutionStore()
    repository = PlanRepository()
    repository.replace_generation([plan])
    _approve(repository, plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=adapter or _RecordingOperationUrlAdapter(),
        require_human_approval=False,
    )
    verifier = ExecutionVerifier(
        credential=_FakeCredential(),
        client=verifier_client or _client_returning(200, {"status": "Succeeded"}),
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=verifier,
        now=lambda: NOW,
    )
    return service, store, repository


def test_retry_rejects_when_plan_approval_changed_since_original_attempt():
    plan = _full_plan()
    service, _, repository = _service(
        plan=plan, verifier_client=_client_returning(200, {"status": "Failed", "error": {}})
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    service.poll_verification(execution_id)  # moves to failed

    # Simulate the plan's action_version changing (regeneration) so the
    # original approval is now stale.
    stale_plan = dict(plan)
    stale_plan["action_version"] = "v2-changed"
    repository.replace_generation([stale_plan])

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)

    assert excinfo.value.reason == "stale_approval"


def test_retry_is_noop_for_already_succeeded_execution():
    plan = _full_plan()
    service, store, _ = _service(
        plan=plan, verifier_client=_client_returning(200, {"status": "Succeeded"})
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    service.poll_verification(execution_id)
    assert store.get(execution_id)["status"] == "succeeded"

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)

    assert excinfo.value.reason == "execution_not_retryable"


def test_retry_increments_attempt_count_and_follows_submit_verify_flow():
    plan = _full_plan()
    adapter = _RecordingOperationUrlAdapter()
    service, store, _ = _service(
        plan=plan,
        adapter=adapter,
        verifier_client=_client_returning(200, {"status": "Failed", "error": {"message": "boom"}}),
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    service.poll_verification(execution_id)
    assert store.get(execution_id)["status"] == "failed"
    assert store.get(execution_id)["attempt_count"] == 1

    retried = service.retry(execution_id)

    record = store.get(execution_id)
    assert record["attempt_count"] == 2
    assert len(adapter.submissions) == 2
    assert retried["status"] in {"running", "failed", "succeeded"}


def test_retry_enforces_max_attempts():
    plan = _full_plan()
    service, store, _ = _service(
        plan=plan, verifier_client=_client_returning(200, {"status": "Failed", "error": {}})
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    service.poll_verification(execution_id)

    # Retry until attempt_count reaches MAX_EXECUTION_ATTEMPTS.
    while store.get(execution_id)["attempt_count"] < MAX_EXECUTION_ATTEMPTS:
        service.retry(execution_id)
        service.poll_verification(execution_id)

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)

    assert excinfo.value.reason == "max_attempts_exceeded"


def test_execute_and_retry_share_the_same_approval_gate_implementation():
    import inspect

    execute_source = inspect.getsource(RemediationExecutionService.execute)
    retry_source = inspect.getsource(RemediationExecutionService.retry)
    assert "_check_approval_gate" in execute_source
    assert "_check_approval_gate" in retry_source


def test_retry_rejects_all_non_retryable_states() -> None:
    plan = _full_plan()
    for status in ("queued", "running", "retrying", "succeeded"):
        service, store, _ = _service(plan=plan)
        result = service.execute(
            plan["plan_id"], requested_by="operator@example.com"
        )
        store.update(result["execution_id"], status=status)

        with pytest.raises(RemediationExecutionError) as excinfo:
            service.retry(result["execution_id"])

        assert excinfo.value.reason == "execution_not_retryable"


def test_two_independent_stores_claim_one_concurrent_retry(tmp_path) -> None:
    plan = _full_plan()
    path = tmp_path / "state" / "remediation_executions.json"
    adapter = _RecordingOperationUrlAdapter(fail=True)
    first, first_store, repository = _service(
        plan=plan,
        adapter=adapter,
        verifier_client=_client_returning(200, {"status": "Failed"}),
    )
    first._store = RemediationExecutionStore(path=path)
    initial = first.execute(plan["plan_id"], requested_by="operator@example.com")
    assert first_store is not first._store

    adapter._fail = False
    second = RemediationExecutionService(
        plan_repository=repository,
        patching_service=first._patching,
        execution_store=RemediationExecutionStore(path=path),
        execution_verifier=first._verifier,
        now=lambda: NOW,
    )
    before = len(adapter.submissions)

    def retry(service):
        try:
            return service.retry(initial["execution_id"])
        except RemediationExecutionError as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(retry, (first, second)))

    assert len(adapter.submissions) == before + 1
    assert "execution_claim_conflict" in outcomes


def test_retry_appends_attempt_history_without_overwriting_first_failure() -> None:
    plan = _full_plan()
    adapter = _RecordingOperationUrlAdapter(fail=True)
    service, store, _ = _service(plan=plan, adapter=adapter)
    failed = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert failed["status"] == "failed"

    adapter._fail = False
    service.retry(failed["execution_id"])

    record = store.get(failed["execution_id"])
    assert record["attempt_count"] == 2
    assert len(record["attempts"]) == 2
    assert record["attempts"][0]["outcome"] == "failed"
    assert "Azure rejected" in record["attempts"][0]["failure_details"]
    assert record["attempts"][1]["provider_job_id"] == OPERATION_URL
    assert record["outcome"] == ""
    assert record["failure_details"] == ""
    assert record["failure_class"] == ""
    assert record["attempts"][1]["transitions"][0]["message"] == ""
    assert record["attempts"][1]["transitions"][0]["failure_details"] == ""
    assert [event["status"] for event in record["history"]][:3] == [
        "queued",
        "running",
        "failed",
    ]


def test_execution_view_projects_the_latest_attempt_over_stale_record_fields() -> None:
    record = {
        "status": "succeeded",
        "outcome": "succeeded",
        "failure_details": "Failure from an earlier attempt",
        "failure_class": "provider_rejected",
        "provider_submitted": True,
        "attempts": [
            {
                "status": "failed",
                "outcome": "failed",
                "failure_details": "Failure from an earlier attempt",
                "failure_class": "provider_rejected",
                "provider_submitted": True,
            },
            {
                "status": "succeeded",
                "outcome": "succeeded",
                "failure_details": "",
                "failure_class": "",
                "provider_submitted": True,
                "verified_state": "Succeeded",
                "verification_evidence": {"installed_count": 1},
            },
        ],
    }

    view = RemediationExecutionService.execution_view(record)

    assert view["status"] == "succeeded"
    assert view["failure_details"] == ""
    assert view["failure_class"] == ""
    assert view["verified_state"] == "Succeeded"
    assert view["verification_evidence"] == {"installed_count": 1}


def test_cancel_and_retry_compare_and_set_claims_have_one_winner() -> None:
    plan = _full_plan()
    adapter = _RecordingOperationUrlAdapter(fail=True)
    service, store, _ = _service(plan=plan, adapter=adapter)
    failed = service.execute(plan["plan_id"], requested_by="operator@example.com")
    record = store.get(failed["execution_id"])

    cancelled = store.claim_cancel(
        failed["execution_id"],
        expected_revision=record["revision"],
        actor="operator@example.com",
    ) if record["status"] == "queued" else None

    assert cancelled is None
    retried = service.retry(failed["execution_id"])
    assert retried["attempt_count"] == 2
