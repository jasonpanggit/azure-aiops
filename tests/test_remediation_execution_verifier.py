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
    """Configurable fake credential.

    Defaults preserve every existing call site's behavior (a fixed
    ``"fake-token"``). ``token``/``error`` let CR-04-style regression tests
    exercise the acquisition-failure and empty-token paths without ever
    letting a real value near a log line -- the token used here is a fake,
    test-only literal, never a real secret.
    """

    def __init__(self, *, token: str | None = "fake-token", error: Exception | None = None) -> None:
        self._token = token
        self._error = error

    def get_token(self, *scopes, **kwargs):
        if self._error is not None:
            raise self._error
        return type("Token", (), {"token": self._token})()


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


def _client_capturing_headers(
    recorder: list[httpx.Request], status_code: int = 200, json_body: dict | None = None
) -> httpx.Client:
    """Return a client whose fake transport records every request it sees.

    Used by the CR-04 regression tests to inspect the *actual* outgoing
    ``Authorization`` header rather than merely ignoring header content, the
    way every pre-existing test in this file does.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        return httpx.Response(status_code, json=json_body if json_body is not None else {"status": "Succeeded"}, request=request)

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


# --- Task 1: nested Azure result parsing (verifier-only, thinnest path) ---


def test_verify_nested_completed_with_warnings_and_failed_count_is_never_clean_success():
    client = _client_returning(
        200,
        {
            "status": "Succeeded",
            "properties": {
                "status": "CompletedWithWarnings",
                "failedPatchCount": 2,
                "installedPatchCount": 3,
            },
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["verifiable"] is True
    assert result["outcome"] == "failed"
    evidence = result["verification_evidence"]
    assert evidence["detail_status"] == "CompletedWithWarnings"
    assert evidence["installed_count"] == 3
    assert evidence["failed_count"] == 2
    assert evidence["pending_count"] == 0
    assert evidence["not_selected_count"] == 0
    assert isinstance(evidence["provider_errors"], list)


# --- Task 2: exhaustive nested-result parsing coverage ---------------------


def test_verify_nested_succeeded_with_zero_failed_count_is_clean_success():
    client = _client_returning(
        200,
        {
            "status": "Succeeded",
            "properties": {
                "status": "Succeeded",
                "failedPatchCount": 0,
                "installedPatchCount": 5,
            },
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "succeeded"
    assert result["verification_evidence"]["failed_count"] == 0


def test_verify_top_level_update_center_result_preserves_patch_counts():
    client = _client_returning(
        200,
        {
            "status": "Succeeded",
            "installedPatchCount": 1,
            "failedPatchCount": 0,
            "pendingPatchCount": 0,
            "notSelectedPatchCount": 0,
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "succeeded"
    assert result["verification_evidence"] == {
        "detail_status": "Succeeded",
        "installed_count": 1,
        "failed_count": 0,
        "pending_count": 0,
        "not_selected_count": 0,
        "provider_errors": [],
    }


def test_verify_in_progress_with_no_properties_body_never_raises():
    client = _client_returning(200, {"status": "InProgress"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "running"
    assert result["verification_evidence"] == {
        "detail_status": "",
        "installed_count": 0,
        "failed_count": 0,
        "pending_count": 0,
        "not_selected_count": 0,
        "provider_errors": [],
    }


def test_verify_envelope_failed_with_properties_error_surfaces_provider_errors():
    client = _client_returning(
        200,
        {
            "status": "Failed",
            "properties": {
                "error": {"code": "OperationFailed", "message": "Reboot required but suppressed"},
            },
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "failed"
    assert "Reboot required but suppressed" in result["failure_details"]
    assert result["verification_evidence"]["provider_errors"] == [
        "Reboot required but suppressed"
    ]


def test_verify_succeeded_with_error_details_but_no_failure_signal_stays_clean():
    client = _client_returning(
        200,
        {
            "status": "Succeeded",
            "properties": {
                "status": "Succeeded",
                "failedPatchCount": 0,
                "errorDetails": [
                    {"code": "InfoOne", "message": "Informational note one"},
                    {"code": "InfoTwo", "message": "Informational note two"},
                ],
            },
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "succeeded"
    assert result["verification_evidence"]["provider_errors"] == [
        "Informational note one",
        "Informational note two",
    ]


def test_verify_defender_configuration_path_omits_verification_evidence():
    client = _client_returning(200, {"properties": {"enabled": True}})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)
    record = _record()
    record["execution_snapshot"] = {
        "snapshot_kind": "defender_configuration",
        "desired_properties": {"enabled": True},
    }

    result = verifier.verify(record)

    assert result["outcome"] == "succeeded"
    assert "verification_evidence" not in result


def test_verify_non_dict_response_body_resolves_to_safe_running_outcome():
    client = _client_returning(200, [1, 2, 3])
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "running"
    assert result["verification_evidence"]["failed_count"] == 0
    assert result["verification_evidence"]["provider_errors"] == []


# -- CR-04 regression: the poll must send the real bearer token, never a --
# -- literal placeholder, and must never touch the network if the token --
# -- cannot be acquired.                                                --


def test_poll_sends_the_real_bearer_token_from_the_credential():
    """The verifier's poll must send ``Bearer <token>`` using the actual
    value ``_token()`` acquires from the credential, not a hardcoded
    placeholder string. Captured via a fake transport that records the
    real ``httpx.Request`` object the class builds, not a test that
    merely ignores header content.
    """
    calls: list[httpx.Request] = []
    client = _client_capturing_headers(calls, 200, {"status": "Succeeded"})
    verifier = ExecutionVerifier(credential=_FakeCredential(token="fake-verifier-token"), client=client)

    verifier.verify(_record())

    assert len(calls) == 1
    auth_header = calls[0].headers["authorization"]
    assert auth_header == "Bearer fake-verifier-token"
    assert auth_header.startswith("Bearer ")
    # The literal placeholder this class must never emit again (CR-04).
    assert "*" * 6 not in auth_header


def test_poll_never_invokes_http_when_token_acquisition_fails():
    """A credential that cannot mint a token must fail closed *before* any
    request is attempted -- token acquisition is a pre-submission refusal,
    never a network call.
    """
    calls: list[httpx.Request] = []
    client = _client_capturing_headers(calls)
    verifier = ExecutionVerifier(
        credential=_FakeCredential(error=RuntimeError("no identity")),
        client=client,
    )

    with pytest.raises(ExecutionVerificationUnavailable, match="management token") as excinfo:
        verifier.verify(_record())

    assert calls == []
    assert excinfo.value.capability == "azure_arm_token"


def test_poll_never_invokes_http_when_credential_returns_an_empty_token():
    """An empty token string is just as unusable as a raised error, and must
    be refused before any request is made -- never sent as a blank/partial
    Authorization header.
    """
    calls: list[httpx.Request] = []
    client = _client_capturing_headers(calls)
    verifier = ExecutionVerifier(credential=_FakeCredential(token=""), client=client)

    with pytest.raises(ExecutionVerificationUnavailable, match="empty management token") as excinfo:
        verifier.verify(_record())

    assert calls == []
    assert excinfo.value.capability == "azure_arm_token"
