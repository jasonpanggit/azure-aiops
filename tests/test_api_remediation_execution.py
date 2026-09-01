"""HTTP-level tests for the approval-gated remediation execution endpoints.

Covers: execute is unreachable for anything except an approved
controlled-patch-recovery plan (409), the executions/{id} endpoint is
immediately pollable after a successful call, and out-of-scope plans 404
before execute ever resolves a target.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.remediation.approval_decisions import RemediationDecisionStore
from intelligence.remediation.execution_service import RemediationExecutionService
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.service import SubscriptionOnboardingService
from operations.patching.adapters import RecordingPatchExecutionAdapter
from operations.patching.service import PatchingService
from tests.test_api_http import FakeSecretWriter

from remediation_scenario import remediation_planner

ADMIN_TOKEN = "admin-token-0123456789abcdef"
OPERATOR_TOKEN = "operator-token-0123456789abcd"
READER_TOKEN = "reader-token-0123456789abcdef"
SCOPED_OPERATOR_TOKEN = "scoped-operator-token-012345"

VM_PAYMENTS_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"


class _FakeVulnerabilityService:
    def __init__(self) -> None:
        self.freshness = "2026-08-18T13:00:00Z"

    def asset_exposures(self, scope=None) -> list[dict]:
        return [
            {
                "asset_id": VM_PAYMENTS_ID,
                "name": "vm-payments",
                "inventory_kind": "Azure VM",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "missing_kbs": ["KB600001"],
                "severities": ["Critical"],
                "cve_ids": ["CVE-2026-0001"],
            }
        ]


def _future_expiry() -> str:
    return (datetime.now(UTC) + timedelta(days=30)).isoformat()


def _client(tmp_path, *, planner=None, principals=None, adapter=None) -> TestClient:
    decision_store = RemediationDecisionStore()
    resolved_planner = planner or remediation_planner(
        repository=PlanRepository(decision_store=decision_store)
    )
    execution_store = RemediationExecutionStore()
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=adapter or RecordingPatchExecutionAdapter(),
        require_human_approval=False,
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(
            tmp_path / "aiops", secret_writer=FakeSecretWriter()
        ),
        authenticator=StaticTokenAuthenticator(
            principals
            or {
                ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
                OPERATOR_TOKEN: Principal(subject="operator@example.com", grants=(Grant("operator"),)),
                READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
                SCOPED_OPERATOR_TOKEN: Principal(
                    subject="scoped-operator@example.com",
                    grants=(Grant("operator", Scope({"subscription": ["sub-does-not-exist"]})),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: resolved_planner,
        execution_provider=lambda: RemediationExecutionService(
            plan_repository=resolved_planner.repository,
            patching_service=patching_service,
            execution_store=execution_store,
        ),
    )
    return TestClient(create_app(context), raise_server_exceptions=False), resolved_planner, execution_store


def _auth(token: str = OPERATOR_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _plans(client: TestClient) -> list[dict]:
    response = client.get("/api/v1/remediation/plans", headers=_auth())
    assert response.status_code == 200, response.text
    return response.json()["data"]["plans"]


def _patch_recovery_plan(client: TestClient) -> dict:
    plans = _plans(client)
    plan = next(p for p in plans if p["action_id"] == "controlled-patch-recovery")
    return plan


def _approve(planner, plan: dict) -> None:
    planner.repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="approver@example.com",
        reason="CAB approved after evidence review",
        scope={},
        action_version=plan["action_version"],
        expires_at=_future_expiry(),
    )


def test_execute_non_patch_recovery_plan_is_409(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plans = _plans(client)
    plan = next(p for p in plans if p["action_id"] != "controlled-patch-recovery")

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"


def test_execute_unapproved_patch_recovery_plan_is_409(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "conflict"
    assert body["error"]["details"]["reason"] == "not_approved"


def test_execute_approved_plan_succeeds_and_is_pollable(tmp_path) -> None:
    client, planner, execution_store = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "succeeded"
    execution_id = body["execution_id"]

    poll = client.get(f"/api/v1/remediation/executions/{execution_id}", headers=_auth())
    assert poll.status_code == 200, poll.text
    execution = poll.json()["data"]
    assert execution["status"] == "succeeded"
    assert execution["plan_id"] == plan["plan_id"]


def test_execute_out_of_scope_plan_is_404_not_409(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(SCOPED_OPERATOR_TOKEN),
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


def test_get_unknown_execution_is_404(tmp_path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get(
        "/api/v1/remediation/executions/RME-DOES-NOT-EXIST", headers=_auth()
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_execute_endpoints_are_mounted_in_the_running_app(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    assert "/api/v1/remediation/plans/{plan_id}/execute" in paths
    assert "/api/v1/remediation/executions/{execution_id}" in paths
