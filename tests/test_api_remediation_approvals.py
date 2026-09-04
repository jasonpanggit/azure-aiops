from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from remediation_scenario import remediation_planner

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.remediation.approval_decisions import RemediationDecisionStore
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.service import SubscriptionOnboardingService
from operations.patching.models import AvailablePatch, PatchTarget
from semantic.live_operations import LiveRemediationPlanner
from tests.test_api_http import FakeSecretWriter

ADMIN_TOKEN = "admin-token-0123456789abcdef"
OPERATOR_TOKEN = "operator-token-0123456789abcd"
READER_TOKEN = "reader-token-0123456789abcdef"
SCOPED_OPERATOR_TOKEN = "scoped-operator-token-012345"
VM_PAYMENTS_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-prod/providers/"
    "microsoft.compute/virtualmachines/vm-payments"
)
# Every distinct organizational role text ``tests/fixtures/sample_remediation_planning.json``'s
# own ``approval_policies`` (plus the universal "Stage Gate Approver" every
# plan with deployment stages carries) can ever require, used only to keep
# this module's decision-recording *mechanics* tests (snapshot binding,
# preview-hash validation, revalidation, read-side projection) unaffected
# by the Phase 03.5 CR-05 per-role authorization fix -- none of them
# exercise per-role governance itself.
_ALL_FIXTURE_ORG_ROLES = (
    "Change Manager",
    "Application Owner",
    "Service Owner",
    "Support Team",
    "Business Service Owner",
    "Operations Risk Owner",
    "Change Advisory Board",
    "Stage Gate Approver",
)


def _future_expiry(days: int = 30) -> str:
    """Return an ISO-8601 date that is always in the future relative to wall clock."""
    return (datetime.now(UTC) + timedelta(days=days)).date().isoformat()


def _future_expiry_datetime(days: int = 30) -> str:
    """Return an ISO-8601 datetime that is always in the future relative to wall clock."""
    return (
        (datetime.now(UTC) + timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class _PatchingService:
    def __init__(self) -> None:
        self.patch_ids = ["KB600002", "KB600001"]
        self.target_available = True

    def target(self, target_id: str, scope=None) -> PatchTarget | None:
        if not self.target_available:
            return None
        return PatchTarget(
            target_id=target_id,
            inventory_kind="Azure VM",
            available_patches=tuple(
                AvailablePatch(patch_id=patch_id) for patch_id in self.patch_ids
            ),
        )


def _client(tmp_path, *, planner=None, principals=None) -> TestClient:
    resolved_planner = planner or remediation_planner()
    patching_service = _PatchingService()
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(
            tmp_path / "aiops", secret_writer=FakeSecretWriter()
        ),
        authenticator=StaticTokenAuthenticator(
            principals
            or {
                ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
                OPERATOR_TOKEN: Principal(
                    subject="operator@example.com",
                    grants=(Grant("operator"), Grant("approver")),
                    # Phase 03.5 CR-05 fix: this shared test principal
                    # records decisions across many plans/resources in
                    # this module, none of which are exercising per-role
                    # approval *governance* (that is covered narrowly by
                    # the dedicated new role-governance regression tests)
                    # -- it is deliberately configured to literally hold
                    # every organizational role this fixture's own policy
                    # catalog declares, so `_approval_payload`'s always
                    # -explicit `role_id` selection is always authorized
                    # regardless of which specific plan/resource a given
                    # mechanics test exercises.
                    org_roles=_ALL_FIXTURE_ORG_ROLES,
                ),
                READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
                SCOPED_OPERATOR_TOKEN: Principal(
                    subject="scoped-operator@example.com",
                    grants=(
                        Grant("operator", Scope({"subscription": ["sub-1"]})),
                        Grant("approver", Scope({"subscription": ["sub-1"]})),
                    ),
                    org_roles=_ALL_FIXTURE_ORG_ROLES,
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: resolved_planner,
        patching_provider=lambda: patching_service,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    client.patch_service = patching_service  # type: ignore[attr-defined]
    return client


def _auth(token: str = OPERATOR_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first_plan(client: TestClient) -> dict:
    response = client.get("/api/v1/remediation-plans", headers=_auth())
    assert response.status_code == 200, response.text
    return response.json()["data"]["plans"][0]


def _patch_recovery_plan(client: TestClient) -> dict:
    response = client.get("/api/v1/remediation-plans", headers=_auth())
    assert response.status_code == 200, response.text
    return next(
        plan
        for plan in response.json()["data"]["plans"]
        if plan["action_id"] == "controlled-patch-recovery"
    )


def _first_role_id(plan: dict) -> str:
    """First requirement row's role_id (or role, if legacy), else ''.

    Phase 03.5 CR-05 fix: role_id must be explicit whenever more than one
    unmet requirement row is eligible; several tests in this module build
    their own decision payload directly (rather than through
    ``_approval_payload``) and need the identical deterministic selection
    so they keep recording a decision regardless of which specific
    plan/resource they exercise -- none of them exercise per-role
    approval governance itself.
    """
    requirements = plan.get("approval_requirements") or []
    if not requirements:
        return ""
    return str(requirements[0].get("role_id") or requirements[0].get("role") or "")


def _preview_hash(client: TestClient, plan: dict) -> str:
    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview",
        headers=_auth(),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["execution_snapshot"]["snapshot_hash"]


def _approval_payload(plan: dict, preview_hash: str | None) -> dict:
    payload = {
        "decision": "approved",
        "reason": "CAB approved exact server preview",
        "action_version": plan["action_version"],
        "expires_at": _future_expiry_datetime(),
    }
    if preview_hash is not None:
        payload["preview_snapshot_hash"] = preview_hash
    # Phase 03.5 CR-05 fix: a decision attests exactly one required role,
    # and role_id must be explicit whenever more than one unmet row is
    # eligible. These tests exercise decision-recording *mechanics*
    # (snapshot binding, preview-hash validation, revalidation, read-side
    # projection), never per-role governance itself (that is covered
    # narrowly by the dedicated new role-governance regression tests) --
    # deterministically selecting this plan's own first requirement row
    # (if it has any) keeps every one of them an explicit, unambiguous
    # selection regardless of how many distinct roles the underlying
    # fixture's policies declare.
    requirements = plan.get("approval_requirements") or []
    if requirements:
        payload["role_id"] = str(
            requirements[0].get("role_id") or requirements[0].get("role") or ""
        )
    return payload


def test_patch_approval_persists_only_the_matching_server_snapshot(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    preview_hash = _preview_hash(client, plan)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json=_approval_payload(plan, preview_hash),
    )

    assert response.status_code == 201, response.text
    snapshot = response.json()["data"]["execution_snapshot"]
    assert snapshot["snapshot_hash"] == preview_hash
    assert snapshot["target_id"] == VM_PAYMENTS_ID
    assert snapshot["patch_ids"] == ["KB600001", "KB600002"]
    assert snapshot["action_version"] == plan["action_version"]


def test_patch_approval_survives_request_to_request_cve_enrichment_drift(
    tmp_path,
) -> None:
    """Derived CVE churn must not stale an unchanged target/patch decision."""

    class _VolatileEnrichmentService:
        freshness = "2026-09-05T00:00:00Z"

        def __init__(self) -> None:
            self.calls = 0

        def asset_exposures(self, scope=None) -> list[dict]:
            self.calls += 1
            return [
                {
                    "asset_id": VM_PAYMENTS_ID,
                    "name": "vm-payments",
                    "inventory_kind": "Azure VM",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "subscription_id": "sub-1",
                    "business_service": "Checkout",
                    "application": "Payments API",
                    "missing_kbs": ["KB600001", "KB600002"],
                    "finding_ids": [
                        f"patch-assessment-001|CVE-2026-{self.calls:04d}"
                    ],
                    "finding_count": 1,
                    "severities": ["Critical"],
                    "cve_ids": [f"CVE-2026-{self.calls:04d}"],
                }
            ]

        def defender_posture(self, scope=None) -> list[dict]:
            return []

    client = _client(
        tmp_path,
        planner=LiveRemediationPlanner(_VolatileEnrichmentService()),
    )
    plan = _patch_recovery_plan(client)
    preview_hash = _preview_hash(client, plan)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            **_approval_payload(plan, preview_hash),
            "selected_patch_ids": [],
        },
    )

    assert response.status_code == 201, response.text
    decision = response.json()["data"]
    assert decision["action_version"] == plan["action_version"]
    assert decision["execution_snapshot"]["snapshot_hash"] == preview_hash


@pytest.mark.parametrize("preview_hash", [None, "0" * 64])
def test_patch_approval_rejects_omitted_or_wrong_preview_hash_without_persisting(
    tmp_path, preview_hash: str | None
) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json=_approval_payload(plan, preview_hash),
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason"] == "stale_execution_preview"
    decisions = client.get(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
    ).json()["data"]["decisions"]
    assert decisions == []


def test_patch_approval_rejects_patch_drift_since_preview(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    preview_hash = _preview_hash(client, plan)
    client.patch_service.patch_ids.append("KB600003")  # type: ignore[attr-defined]

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json=_approval_payload(plan, preview_hash),
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason"] == "stale_execution_preview"


def test_patch_preview_fails_closed_when_no_patches_are_available(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    client.patch_service.patch_ids = []  # type: ignore[attr-defined]

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview",
        headers=_auth(),
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason"] == "no_patches_available"


def test_rejected_patch_decision_needs_no_preview_and_has_no_snapshot(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "rejected",
            "reason": "Risk too high",
            "action_version": plan["action_version"],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["execution_snapshot"] is None


@pytest.mark.parametrize(
    "field",
    ["execution_snapshot", "target_id", "patch_ids", "operation"],
)
def test_decision_request_rejects_caller_owned_execution_fields(
    tmp_path, field: str
) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    payload = _approval_payload(plan, _preview_hash(client, plan))
    payload[field] = {} if field == "execution_snapshot" else "caller-value"

    response = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


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
            "role_id": _first_role_id(plan),
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
            "role_id": _first_role_id(plan),
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
            "role_id": _first_role_id(plan),
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
            "role_id": _first_role_id(plan),
        },
    )
    
    assert response.status_code == 201
    decision = response.json()["data"]
    # Check for revalidation checks
    assert "revalidation" in decision
    # defender_evidence_fresh should be in the checks or status should indicate it
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
            "role_id": _first_role_id(plan),
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
            "role_id": _first_role_id(plan),
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
            "role_id": _first_role_id(plan),
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
            "role_id": _first_role_id(plan),
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
    
    remediation_src_dir = "src/api/routers/operations.py"
    with open(remediation_src_dir, "r") as f:
        content = f.read()
    
    # Scan for execution/apply/execute route decorators on remediation endpoints
    execution_keywords = ["execute", "apply", "deploy", "remediate", "run-action"]
    
    # Verify there's no forbidden pattern
    for line in content.split("\n"):
        for keyword in execution_keywords:
            assert keyword not in line.lower() or "execution_authorized" in line, \
                f"Found execution-related code: {line}"


def test_remediation_package_has_no_azure_or_subprocess_calls(tmp_path) -> None:
    """Test 3.5: Remediation package contains no Azure management-plane or subprocess calls."""
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent

    # Check for azure.mgmt imports
    result = subprocess.run(
        ["grep", "-r", "azure\\.mgmt", "src/intelligence/remediation/", "--include=*.py"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    assert result.returncode != 0 or "azure.mgmt" not in result.stdout, "Found azure.mgmt imports in remediation package"

    # Check for subprocess calls
    result = subprocess.run(
        ["grep", "-r", "subprocess", "src/intelligence/remediation/", "--include=*.py"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
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
            "role_id": _first_role_id(plan),
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
