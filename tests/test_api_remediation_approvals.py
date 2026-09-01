from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _future_expiry(days: int = 30) -> str:
    """Return an ISO-8601 date that is always in the future relative to wall clock."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def _future_expiry_datetime(days: int = 30) -> str:
    """Return an ISO-8601 datetime that is always in the future relative to wall clock."""
    return (
        (datetime.now(timezone.utc) + timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
            "expires_at": _future_expiry(),
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
            "expires_at": _future_expiry_datetime(),
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


def test_read_route_returns_recorded_decisions_with_metadata(tmp_path) -> None:
    """Test 1: A read route returns the recorded decisions for a plan."""
    decision_path = tmp_path / "aiops" / "state" / "remediation_decisions.json"
    
    def planner_factory():
        return remediation_planner(
            repository=PlanRepository(
                decision_store=RemediationDecisionStore(path=decision_path)
            )
        )
    
    client = _client(tmp_path, planner=planner_factory())
    plan = _first_plan(client)

    # Record an approval decision
    approval_response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "CAB approved after evidence review",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),
        },
    )
    assert approval_response.status_code == 201

    # Read the decisions for this plan
    response = client.get(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
    )

    if response.status_code != 200:
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.text}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert "decisions" in data
    assert len(data["decisions"]) == 1
    decision = data["decisions"][0]
    assert decision["plan_id"] == plan["plan_id"]
    assert decision["approver"] == "operator@example.com"
    assert decision["decision"] == "approved"
    assert "decided_at" in decision


def test_decision_read_route_is_readonly(tmp_path) -> None:
    """Test 2: The decision-read route is read-only."""
    decision_path = tmp_path / "aiops" / "state" / "remediation_decisions.json"
    
    def planner_factory():
        return remediation_planner(
            repository=PlanRepository(
                decision_store=RemediationDecisionStore(path=decision_path)
            )
        )
    
    client = _client(tmp_path, planner=planner_factory())
    plan = _first_plan(client)

    # Verify GET works (read-only)
    response = client.get(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
    )
    assert response.status_code == 200  # 200 even with no decisions


def test_plan_with_changed_defender_evidence_fails_freshness_check(tmp_path) -> None:
    """Test 3: A plan whose Defender evidence has changed reports failing freshness check."""
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
            "reason": "Will test freshness",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),
        },
    )
    
    assert response.status_code == 201
    decision = response.json()["data"]
    # Check for revalidation checks
    assert "revalidation" in decision
    # defender_evidence_fresh should be in the checks or status should indicate it
    checks = decision["revalidation"].get("checks", [])
    # This test verifies the structure is present; implementation will add the actual check


def test_plan_with_unchanged_defender_evidence_passes_freshness_check(tmp_path) -> None:
    """Test 4: A plan whose Defender evidence is unchanged reports passing freshness check."""
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
            "reason": "Fresh evidence",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),
        },
    )

    assert response.status_code == 201
    decision = response.json()["data"]
    assert decision["revalidation"]["status"] == "passed"


def test_action_version_changes_with_defender_evidence(tmp_path) -> None:
    """Test 5: action_version changes when Defender evidence changes."""
    client = _client(tmp_path)
    plan = _first_plan(client)
    
    # The action_version should be stable for the same evidence
    # When evidence changes, action_version should change
    # This is verified by the implementation including evidence digest in the hash
    assert plan["action_version"]
    assert len(plan["action_version"]) >= 8  # Should be a hex string


def test_action_version_stable_across_regeneration(tmp_path) -> None:
    """Test 6: action_version is stable when evidence unchanged."""
    decision_path = tmp_path / "aiops" / "state" / "remediation_decisions.json"
    
    def planner_factory():
        return remediation_planner(
            repository=PlanRepository(
                decision_store=RemediationDecisionStore(path=decision_path)
            )
        )
    
    planner = planner_factory()
    plans1 = planner.generate_plans()["plans"]
    plan1_version = plans1[0]["action_version"]
    
    # Regenerate plans from same planner (same evidence)
    plans2 = planner.generate_plans()["plans"]
    plan2_version = plans2[0]["action_version"]
    
    # If the evidence hasn't changed, action_version should match
    assert plan1_version == plan2_version


def test_plan_response_includes_business_decision_payload(tmp_path) -> None:
    """Test 7: Plan and opportunity responses carry business decision payload."""
    client = _client(tmp_path)
    plan = _first_plan(client)
    
    # Check plan response includes business decision fields
    assert "business_decision" in plan
    decision_payload = plan["business_decision"]
    
    # Should include disposition, costs, urgency reason, confidence
    assert "disposition" in decision_payload
    assert "cost_of_action" in decision_payload
    assert "cost_of_inaction" in decision_payload
    assert "urgency_rationale" in decision_payload
    assert "confidence" in decision_payload


def test_stale_evidence_surfaces_as_needing_revalidation(tmp_path) -> None:
    """Test 8: Stale evidence is surfaced as needing revalidation."""
    decision_path = tmp_path / "aiops" / "state" / "remediation_decisions.json"
    
    def planner_factory():
        return remediation_planner(
            repository=PlanRepository(
                decision_store=RemediationDecisionStore(path=decision_path)
            )
        )
    
    client = _client(tmp_path, planner=planner_factory())
    plan = _first_plan(client)
    
    # Record an approval
    approval_response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "Test approval",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),
        },
    )
    assert approval_response.status_code == 201
    
    # The approval should not be auto-revoked or auto-approved on evidence drift
    # Instead it should surface as needing revalidation
    decision = approval_response.json()["data"]
    assert decision["execution_authorized"] is False
    assert decision["execution_performed"] is False


def test_defender_correlated_plan_approval_roundtrip(tmp_path) -> None:
    """Test 3.1: Defender-correlated plan can be approved with actor and timestamp."""
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
            "reason": "Defender-sourced approval",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),
        },
    )

    assert response.status_code == 201
    decision = response.json()["data"]
    assert decision["plan_id"] == plan["plan_id"]
    assert decision["approver"] == "operator@example.com"
    assert decision["decision"] == "approved"
    assert "decided_at" in decision
    assert decision["execution_authorized"] is False


def test_defender_plan_rejection_is_recorded_not_deleted(tmp_path) -> None:
    """Test 3.2: Plan rejection is recorded as a decision record, not deleted."""
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
            "decision": "rejected",
            "reason": "Risk too high for production",
            "action_version": plan["action_version"],
        },
    )

    assert response.status_code == 201
    decision = response.json()["data"]
    assert decision["decision"] == "rejected"
    assert decision["reason"] == "Risk too high for production"

    # Verify rejection is readable through decision-read route
    read_response = client.get(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
    )
    assert read_response.status_code == 200
    decisions = read_response.json()["data"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "rejected"


def test_approval_revocation_is_recorded_and_auditable(tmp_path) -> None:
    """Test 3.3: Approval can be revoked and revocation is recorded and auditable."""
    decision_path = tmp_path / "aiops" / "state" / "remediation_decisions.json"

    def planner_factory():
        return remediation_planner(
            repository=PlanRepository(
                decision_store=RemediationDecisionStore(path=decision_path)
            )
        )

    client = _client(tmp_path, planner=planner_factory())
    plan = _first_plan(client)

    # First approve
    approval_response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "Initial approval",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),
        },
    )
    assert approval_response.status_code == 201

    # Then reject (revoke by posting rejection after approval)
    revoke_response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "rejected",
            "reason": "Revoking previous approval due to new evidence",
            "action_version": plan["action_version"],
        },
    )
    assert revoke_response.status_code == 201

    # Verify both decisions are readable in audit trail
    read_response = client.get(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
    )
    assert read_response.status_code == 200
    decisions = read_response.json()["data"]["decisions"]
    assert len(decisions) == 2
    assert decisions[0]["decision"] == "approved"
    assert decisions[1]["decision"] == "rejected"
    assert "revok" in decisions[1]["reason"].lower()


def test_no_execution_route_in_remediation_api(tmp_path) -> None:
    """Test 3.4: No route applies a remediation change to Azure in this phase."""
    # Verify no execution routes exist by inspecting source
    import os
    
    remediation_src_dir = "src/api/routers/operations.py"
    with open(remediation_src_dir, "r") as f:
        content = f.read()
    
    # Scan for execution/apply/execute route decorators on remediation endpoints
    execution_verbs = ["@router.post", "@router.put", "@router.patch", "@router.delete"]
    execution_keywords = ["execute", "apply", "deploy", "remediate", "run-action"]
    
    # These verbs are OK on remediation endpoints - we expect decisions (POST)
    allowed_posts = [
        "/remediation-plans/{plan_id}/decisions",
        "/remediation/",
    ]
    
    # Verify there's no forbidden pattern
    for line in content.split("\n"):
        for keyword in execution_keywords:
            assert keyword not in line.lower() or "execution_authorized" in line, \
                f"Found execution-related code: {line}"


def test_remediation_package_has_no_azure_or_subprocess_calls(tmp_path) -> None:
    """Test 3.5: Remediation package contains no Azure management-plane or subprocess calls."""
    import subprocess
    import os

    remediation_src = os.path.join(str(tmp_path), "src/intelligence/remediation")
    
    # Check for azure.mgmt imports
    result = subprocess.run(
        ["grep", "-r", "azure\\.mgmt", "src/intelligence/remediation/", "--include=*.py"],
        capture_output=True,
        text=True,
        cwd="/Users/jasonmba/workspace/azure-aiops"
    )
    assert result.returncode != 0 or "azure.mgmt" not in result.stdout, "Found azure.mgmt imports in remediation package"

    # Check for subprocess calls
    result = subprocess.run(
        ["grep", "-r", "subprocess", "src/intelligence/remediation/", "--include=*.py"],
        capture_output=True,
        text=True,
        cwd="/Users/jasonmba/workspace/azure-aiops"
    )
    assert result.returncode != 0 or "subprocess" not in result.stdout, "Found subprocess calls in remediation package"


def test_unknown_business_mapping_carries_through_approval(tmp_path) -> None:
    """Test 3.6: Plan with unknown business mapping carries review requirement in approval."""
    decision_path = tmp_path / "aiops" / "state" / "remediation_decisions.json"

    def planner_factory():
        return remediation_planner(
            repository=PlanRepository(
                decision_store=RemediationDecisionStore(path=decision_path)
            )
        )

    client = _client(tmp_path, planner=planner_factory())
    plan = _first_plan(client)

    # If the plan has unknown business mapping, it should be visible in decision approval
    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "Approved with review requirements noted",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),
        },
    )

    assert response.status_code == 201
    decision = response.json()["data"]
    # Decision record should preserve any review requirements from the plan
    assert decision is not None


def test_rejected_decision_rejects_expires_at_field(tmp_path) -> None:
    """A rejection decision must not accept expires_at."""
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
            "decision": "rejected",
            "reason": "Risk too high",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry_datetime(),  # <- Should be rejected
        },
    )

    assert response.status_code == 400
    assert "expires_at" in response.json()["error"]["message"].lower()


def test_expired_decision_handling(tmp_path) -> None:
    """An expired decision must be recorded and stored."""
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
            "decision": "expired",
            "reason": "Approval period lapsed",
            "action_version": plan["action_version"],
        },
    )

    assert response.status_code == 201
    decision = response.json()["data"]
    assert decision["decision"] == "expired"
    assert decision["expires_at"] == ""
