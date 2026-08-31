from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.remediation.approval_decisions import RemediationDecisionStore
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.service import SubscriptionOnboardingService
from tests.test_api_http import FakeSecretWriter

from remediation_scenario import remediation_planner


ADMIN_TOKEN = "admin-token-0123456789abcdef"
OPERATOR_TOKEN = "operator-token-0123456789abcd"
READER_TOKEN = "reader-token-0123456789abcdef"
SCOPED_OPERATOR_TOKEN = "scoped-operator-token-012345"


def _client(tmp_path, *, planner=None, principals=None) -> TestClient:
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
                    grants=(Grant("operator", Scope({"subscription": ["sub-1"]})),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: planner or remediation_planner(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth(token: str = OPERATOR_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first_plan(client: TestClient) -> dict:
    response = client.get("/api/v1/remediation-plans", headers=_auth())
    assert response.status_code == 200, response.text
    return response.json()["data"]["plans"][0]


def test_operator_records_approval_decision_without_execution(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "CAB approved after evidence review",
            "action_version": plan["action_version"],
            "expires_at": "2026-09-01",
        },
    )

    assert response.status_code == 201, response.text
    decision = response.json()["data"]
    assert decision["plan_id"] == plan["plan_id"]
    assert decision["approver"] == "operator@example.com"
    assert decision["decision"] == "approved"
    assert decision["execution_authorized"] is False
    assert decision["execution_performed"] is False
    assert decision["read_only"] is True
    assert "action_version_current" in decision["revalidation"]["checks"]
    assert "approval_not_expired" in decision["revalidation"]["checks"]


def test_remediation_decision_survives_provider_rebuild(tmp_path) -> None:
    decision_path = tmp_path / "aiops" / "state" / "remediation_decisions.json"

    def planner_factory():
        return remediation_planner(
            repository=PlanRepository(
                decision_store=RemediationDecisionStore(path=decision_path)
            )
        )

    client = _client(tmp_path, planner=planner_factory())
    plan = _first_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "CAB approved after evidence review",
            "action_version": plan["action_version"],
            "expires_at": "2026-09-01T00:00:00Z",
        },
    )

    assert response.status_code == 201, response.text
    rebuilt = planner_factory()
    assert rebuilt.repository.decisions.list(plan["plan_id"])[0]["decision"] == "approved"


def test_approved_decision_rejects_invalid_expiry(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "Invalid expiry should fail",
            "action_version": plan["action_version"],
            "expires_at": "not-a-date",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_reader_cannot_record_remediation_decision(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(READER_TOKEN),
        json={
            "decision": "rejected",
            "reason": "No approval authority",
            "action_version": plan["action_version"],
        },
    )

    assert response.status_code == 403


def test_stale_action_version_is_rejected(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "rejected",
            "reason": "Outdated recommendation",
            "action_version": "stale",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_scoped_operator_cannot_decide_out_of_scope_plan(tmp_path) -> None:
    planner = remediation_planner()
    plan = next(
        row
        for row in planner.generate_plans()["plans"]
        if row["subscription_id"] != "sub-1"
    )
    client = _client(tmp_path, planner=planner)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(SCOPED_OPERATOR_TOKEN),
        json={
            "decision": "rejected",
            "reason": "Out of scope",
            "action_version": plan["action_version"],
        },
    )

    assert response.status_code == 404
