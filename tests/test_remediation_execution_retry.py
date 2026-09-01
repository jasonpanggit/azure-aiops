"""Bounded, idempotent, revalidated retries for a remediation execution.

A retry re-runs the exact same approval-gate checks as ``execute()``
against the plan's *current* state -- since the plan or its approval may
have changed since the original attempt -- is rejected once the execution
already succeeded (idempotency), and is bounded by ``MAX_EXECUTION_ATTEMPTS``
so a failing target cannot be retried indefinitely (T-03-10, T-03-11).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

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
            raise PatchExecutionUnavailable("Azure rejected the request")
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
        "rollback_plan": {
            "rollback_actions": ["Restore from last known-good snapshot"],
            "automatic_rollback": False,
            "execution_status": "Not Executed",
        },
    }
    plan.update(overrides)
    return plan


def _approve(repository: PlanRepository, plan: dict, *, expires_at: str = "") -> None:
    repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="approver@example.com",
        reason="Approved for patch recovery",
        scope={},
        action_version=plan["action_version"],
        expires_at=expires_at or (NOW + timedelta(days=1)).isoformat(),
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
    service, store, repository = _service(
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

    assert excinfo.value.reason == "already_succeeded"


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
