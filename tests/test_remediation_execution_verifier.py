"""Post-submission verification: poll the real upstream source of truth.

An accepted ARM response only means "accepted". Update Manager and AKS
remain the authority on the actual outcome, so ``ExecutionVerifier`` polls
the operation URL Azure handed back at submission time and never infers
success from the 2xx response alone.
"""

from __future__ import annotations

import httpx
import pytest

from intelligence.remediation.execution_verifier import (
    ExecutionVerificationUnavailable,
    ExecutionVerifier,
)

OPERATION_URL = (
    "https://management.azure.com/subscriptions/sub-1/providers/"
    "Microsoft.Compute/locations/eastus/operations/op-123?api-version=2024-07-01"
)


class _FakeCredential:
    def get_token(self, *scopes, **kwargs):
        return type("Token", (), {"token": "fake-token"})()


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, handler) -> None:
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _client_returning(status_code: int, json_body: dict | None = None, *, text: str = "") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if json_body is not None:
            return httpx.Response(status_code, json=json_body, request=request)
        return httpx.Response(status_code, text=text, request=request)

    return httpx.Client(transport=_FakeTransport(handler))


def _client_raising_transport_error() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.Client(transport=_FakeTransport(handler))


def _record(provider_job_id: str = OPERATION_URL) -> dict:
    return {"execution_id": "RME-0001", "provider_job_id": provider_job_id}


def test_verify_maps_succeeded_status_to_verified_succeeded_outcome():
    client = _client_returning(200, {"status": "Succeeded"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["verifiable"] is True
    assert result["outcome"] == "succeeded"
    assert result["verified_state"] == "Succeeded"


def test_verify_maps_failed_status_to_verified_failed_outcome_with_details():
    client = _client_returning(
        200,
        {"status": "Failed", "error": {"code": "PatchFailed", "message": "Reboot timed out"}},
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["verifiable"] is True
    assert result["outcome"] == "failed"
    assert result["verified_state"] == "Failed"
    assert "Reboot timed out" in result["failure_details"]


def test_verify_maps_in_progress_status_to_running_outcome_and_is_repeatable():
    client = _client_returning(200, {"status": "InProgress"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    first = verifier.verify(_record())
    second = verifier.verify(_record())

    assert first["outcome"] == "running"
    assert second["outcome"] == "running"
    assert first["verifiable"] is True


def test_verify_maps_running_status_alias_to_running_outcome():
    client = _client_returning(200, {"status": "Running"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "running"


@pytest.mark.parametrize("status", ["Canceled", "Cancelled"])
def test_verify_maps_arm_cancellation_to_cancelled_outcome(status: str):
    verifier = ExecutionVerifier(
        credential=_FakeCredential(),
        client=_client_returning(200, {"status": status}),
    )

    result = verifier.verify(_record())

    assert result["outcome"] == "cancelled"
    assert result["verified_state"] == status


def test_verify_raises_typed_error_on_network_failure():
    client = _client_raising_transport_error()
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    with pytest.raises(ExecutionVerificationUnavailable):
        verifier.verify(_record())


def test_verify_reports_not_verifiable_when_no_provider_job_id():
    client = _client_returning(200, {"status": "Succeeded"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record(provider_job_id=""))

    assert result["verifiable"] is False
    assert result["reason"] == "no provider job id"


# --- Task 2: wiring verification into the execution lifecycle ------------

from datetime import UTC, datetime, timedelta

from intelligence.remediation.approval_decisions import (
    execution_snapshot_hash,
)
from intelligence.remediation.execution_service import RemediationExecutionService
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from operations.patching.adapters import (
    PatchExecutionResult,
)
from operations.patching.service import PatchingService

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 8, 18, 13, tzinfo=UTC)


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


class _OperationUrlAdapter:
    """Records submissions like RecordingPatchExecutionAdapter, but hands
    back a real-looking operation URL so verification has something to poll."""

    name = "recording-with-operation-url"

    def __init__(self) -> None:
        self.submissions: list = []

    def submit(self, run, target) -> PatchExecutionResult:
        self.submissions.append((run, target))
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id=OPERATION_URL,
            state="submitted",
            message="Accepted by Azure; Update Manager is authoritative for the outcome.",
        )


def _full_plan_with_rollback(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-0002",
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
            "rollback_actions": ["Restore from last known-good snapshot", "Notify on-call"],
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
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=snapshot,
        now=NOW,
    )
    return repository


def _service_with_verifier(
    *, plan: dict, adapter=None, verifier_client: httpx.Client | None = None
) -> tuple[RemediationExecutionService, RemediationExecutionStore]:
    store = RemediationExecutionStore()
    repository = _approved_repository(plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=adapter or _OperationUrlAdapter(),
        require_human_approval=False,
    )
    verifier = ExecutionVerifier(
        credential=_FakeCredential(),
        client=verifier_client or _client_returning(200, {"status": "InProgress"}),
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=verifier,
        now=lambda: NOW,
    )
    return service, store


def test_execute_leaves_status_running_not_succeeded_until_verified():
    plan = _full_plan_with_rollback()
    service, store = _service_with_verifier(plan=plan)

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    execution = store.get(result["execution_id"])
    assert execution["status"] == "running"


def test_poll_verification_updates_status_to_succeeded_on_terminal_outcome():
    plan = _full_plan_with_rollback()
    service, store = _service_with_verifier(
        plan=plan, verifier_client=_client_returning(200, {"status": "InProgress"})
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    service._verifier = ExecutionVerifier(
        credential=_FakeCredential(), client=_client_returning(200, {"status": "Succeeded"})
    )
    polled = service.poll_verification(execution_id)

    assert polled["status"] == "succeeded"
    assert store.get(execution_id)["status"] == "succeeded"


def test_poll_verification_is_noop_while_still_running():
    plan = _full_plan_with_rollback()
    service, store = _service_with_verifier(
        plan=plan, verifier_client=_client_returning(200, {"status": "InProgress"})
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    polled = service.poll_verification(execution_id)

    assert polled["status"] == "running"
    assert store.get(execution_id)["status"] == "running"


def test_execution_record_carries_rollback_guidance_from_creation():
    plan = _full_plan_with_rollback()
    service, store = _service_with_verifier(plan=plan)

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    execution = store.get(result["execution_id"])
    assert execution["rollback_guidance"] == [
        "Restore from last known-good snapshot",
        "Notify on-call",
    ]


def test_execution_verifier_module_never_calls_a_mutating_method():
    import inspect

    import intelligence.remediation.execution_verifier as verifier_module

    source = inspect.getsource(verifier_module)
    assert ".submit(" not in source
    assert ".trigger(" not in source


def test_execute_without_verifier_stays_running_and_reports_degraded_verification():
    plan = _full_plan_with_rollback()
    store = RemediationExecutionStore()
    repository = _approved_repository(plan)
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _FakeVulnerabilityService(),
            adapter=_OperationUrlAdapter(),
            require_human_approval=False,
        ),
        execution_store=store,
        now=lambda: NOW,
    )

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    polled = service.poll_verification(result["execution_id"])

    assert result["status"] == "running"
    assert polled["status"] == "running"
    assert "verification unavailable" in polled["message"].casefold()


def test_poll_verification_persists_arm_cancellation():
    plan = _full_plan_with_rollback()
    service, store = _service_with_verifier(
        plan=plan,
        verifier_client=_client_returning(200, {"status": "Cancelled"}),
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    polled = service.poll_verification(result["execution_id"])

    assert polled["status"] == "cancelled"
    assert polled["verified_state"] == "Cancelled"
    assert store.get(result["execution_id"])["attempts"][0]["outcome"] == "cancelled"
