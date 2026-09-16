"""HTTP-level tests for the approval-gated remediation execution endpoints.

Covers: execute is unreachable for anything except an approved
controlled-patch-recovery plan (409), the executions/{id} endpoint is
immediately pollable after a successful call, and out-of-scope plans 404
before execute ever resolves a target.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from remediation_scenario import remediation_planner

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.remediation.approval_decisions import (
    RemediationDecisionStore,
    execution_snapshot_hash,
)
from intelligence.remediation.approval_gate import policy_version_for
from intelligence.remediation.execution_service import RemediationExecutionService
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.service import SubscriptionOnboardingService
from operations.defender_configuration import (
    ENABLE_DEFENDER_SERVERS_P1,
    DefenderConfigurationResult,
)
from operations.patching.adapters import RecordingPatchExecutionAdapter
from operations.patching.service import PatchingService
from tests.test_api_http import FakeSecretWriter

ADMIN_TOKEN = "admin-token-0123456789abcdef"
OPERATOR_TOKEN = "operator-token-0123456789abcd"
READER_TOKEN = "reader-token-0123456789abcdef"
SCOPED_OPERATOR_TOKEN = "scoped-operator-token-012345"
SUBSCRIPTION_OPERATOR_TOKEN = "subscription-operator-01234"

VM_PAYMENTS_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"

# Every distinct organizational role text ``tests/fixtures/sample_remediation_planning.json``'s
# own ``approval_policies`` (plus the universal "Stage Gate Approver"
# every plan with deployment stages carries) can ever require, used only
# to keep this module's RBAC-separation-of-duties tests unaffected by the
# Phase 03.5 CR-05 per-role authorization fix -- none of them exercise
# per-role governance itself (that is covered narrowly by the dedicated
# new role-governance regression tests).
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


class _DefenderConfigurationAdapter:
    def __init__(self) -> None:
        self.submissions: list[dict] = []

    def inspect(self, request):
        return {"etag": '"v1"', "state_hash": "state-1", "properties": {}}

    def submit(self, snapshot):
        self.submissions.append(snapshot)
        return DefenderConfigurationResult(
            provider="recording",
            provider_job_id=(
                "https://management.azure.com"
                f"{snapshot['request']['path']}?api-version=2024-01-01"
            ),
            state="submitted",
            message="recorded",
        )


def _client(
    tmp_path,
    *,
    planner=None,
    principals=None,
    adapter=None,
    defender_adapter=None,
) -> TestClient:
    decision_store = RemediationDecisionStore()
    resolved_planner = planner or remediation_planner(
        repository=PlanRepository(decision_store=decision_store)
    )
    original_generate_plans = resolved_planner.generate_plans

    def generate_eligible_plans():
        result = original_generate_plans()
        for row in result["plans"]:
            if row.get("action_id") == "controlled-patch-recovery":
                row["resource_key"] = VM_PAYMENTS_ID
                row["subscription_id"] = "sub-1"
                row["resource"] = {
                    **(row.get("resource") or {}),
                    "id": VM_PAYMENTS_ID,
                }
                row["business_decision"] = {
                    "disposition": "act_now",
                    "business_impact": {"status": "known"},
                    "review_requirements": [],
                    "unknowns": [],
                    "urgency_rationale": {
                        "evidence_citations": ["assessment:assess-001"]
                    },
                }
        resolved_planner.repository.replace_generation(result["plans"])
        return result

    resolved_planner.generate_plans = generate_eligible_plans
    execution_store = RemediationExecutionStore()
    decision_store = RemediationDecisionStore()
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
                OPERATOR_TOKEN: Principal(
                    subject="operator@example.com",
                    grants=(Grant("operator"), Grant("approver")),
                ),
                READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
                SCOPED_OPERATOR_TOKEN: Principal(
                    subject="scoped-operator@example.com",
                    grants=(Grant("operator", Scope({"subscription": ["sub-does-not-exist"]})),),
                ),
                SUBSCRIPTION_OPERATOR_TOKEN: Principal(
                    subject="subscription-operator@example.com",
                    grants=(Grant("operator", Scope({"subscription": ["sub-1"]})),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: resolved_planner,
        patching_provider=lambda: patching_service,
        execution_provider=lambda scope: RemediationExecutionService(
            plan_repository=resolved_planner.repository,
            patching_service=patching_service,
            defender_configuration_adapter=defender_adapter,
            execution_store=execution_store,
            # Shared across many tests here, none of which exercise SoD
            # refusal (that is covered narrowly by Plan 03.5-05's own
            # dedicated tests) -- consistent with this fixture's existing
            # approval-light `require_human_approval=False` intent.
            allow_self_approval=True,
            # Mirrors runtime.py::_execution_service_for_scope's identical
            # wiring (WR-02 fix): without this, the gate's policy_version
            # comparison defaults to "", which no longer trivially matches
            # a decision recorded through the real HTTP route once that
            # route successfully resolves the plan's actual originating
            # ApprovalEngine.policy_version (as it does for this fixture's
            # Fabric/catalog-shaped `remediation_planner()` default).
            policy_version_resolver=lambda: policy_version_for(resolved_planner),
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


def _first_role_id(plan: dict) -> str:
    """First requirement row's role_id (or role, if legacy), else ''.

    Phase 03.5 CR-05 fix: role_id must be explicit whenever more than one
    unmet requirement row is eligible; a few tests in this module record a
    decision through the real HTTP route directly (rather than via the
    ``_approve`` store-level helper) and need the identical deterministic
    selection.
    """
    requirements = plan.get("approval_requirements") or []
    if not requirements:
        return ""
    return str(requirements[0].get("role_id") or requirements[0].get("role") or "")


def _approve(planner, plan: dict) -> None:
    stored_plan = planner.repository.get(plan["plan_id"])
    stored_plan["business_decision"] = {
        "disposition": "act_now",
        "business_impact": {"status": "known"},
        "review_requirements": [],
        "unknowns": [],
        "urgency_rationale": {"evidence_citations": ["assessment:assess-001"]},
    }
    plans = [
        stored_plan if row["plan_id"] == plan["plan_id"] else row
        for row in planner.repository.list()
    ]
    planner.repository.replace_generation(plans)
    snapshot = {
        "target_id": VM_PAYMENTS_ID,
        "patch_ids": ["KB600001"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": plan["action_version"],
    }
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    # Record one decision per distinct role_id this plan's own
    # approval_requirements actually demands (Phase 03.5 CR-05 fix: one
    # decision attests exactly one required role via approval_role_id, so
    # a single decision listing every role in the legacy approver_roles
    # list -- as this helper did pre-fix -- can no longer satisfy more
    # than one row). These tests exercise execution mechanics assuming
    # approval is already fully granted, not per-role separation of
    # duties (that is covered narrowly by Plan 03.5-05's own dedicated
    # tests, and by the new Phase 03.5 CR-05 role-governance regression
    # tests), so looping to grant every distinct role is the correct
    # simulation of full multi-stakeholder sign-off.
    distinct_role_ids = sorted(
        {
            str(row.get("role_id") or row.get("role") or "")
            for row in stored_plan.get("approval_requirements") or []
        }
    )
    if not distinct_role_ids:
        distinct_role_ids = [""]
    policy_version = policy_version_for(planner)
    for role_id in distinct_role_ids:
        planner.repository.decisions.append(
            plan=stored_plan,
            decision="approved",
            approver="approver@example.com",
            reason="CAB approved after evidence review",
            scope={},
            action_version=plan["action_version"],
            expires_at=_future_expiry(),
            execution_snapshot=snapshot,
            approver_roles=[role_id] if role_id else [],
            approval_role_id=role_id,
            # WR-02 fix: the execution gate now compares this decision's
            # recorded policy_version against the plan's actual live
            # ApprovalEngine.policy_version (never a self-referential reuse
            # of this same field) -- this must be populated with the real
            # value, exactly as the real `record_remediation_decision`
            # route derives it, or every row falsely reads
            # `stale_policy_version`.
            approval_policy_version=policy_version,
        )


def test_execute_non_patch_recovery_plan_is_409(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    plans = _plans(client)
    plan = next(p for p in plans if p["action_id"] != "controlled-patch-recovery")

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"


def test_execute_unapproved_patch_recovery_plan_is_409(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "conflict"
    assert body["error"]["details"]["reason"] == "not_approved"


def test_execute_approved_plan_remains_running_and_is_pollable(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["status"] == "running"
    execution_id = body["execution_id"]

    poll = client.get(f"/api/v1/remediation/executions/{execution_id}", headers=_auth())
    assert poll.status_code == 200, poll.text
    execution = poll.json()["data"]
    assert execution["status"] == "running"
    assert execution["plan_id"] == plan["plan_id"]


def test_execute_same_approval_is_idempotent_but_fresh_terminal_approval_resubmits(
    tmp_path,
) -> None:
    adapter = RecordingPatchExecutionAdapter()
    client, planner, execution_store = _client(tmp_path, adapter=adapter)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    first_response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )
    repeated_response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert first_response.status_code == 202, first_response.text
    assert repeated_response.status_code == 202, repeated_response.text
    first = first_response.json()["data"]
    repeated = repeated_response.json()["data"]
    assert repeated["execution_id"] == first["execution_id"]
    assert repeated["approval_decision_id"] == first["approval_decision_id"]
    assert len(adapter.submissions) == 1

    execution_store.update(
        first["execution_id"],
        status="succeeded",
        evidence_reconciliation={
            "status": "reconciled_incomplete",
            "kbs_cleared": [],
            "kbs_remaining": ["KB600001"],
            "assessed_at": datetime.now(UTC).isoformat(),
        },
    )
    _approve(planner, plan)

    fresh_response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )

    assert fresh_response.status_code == 202, fresh_response.text
    fresh = fresh_response.json()["data"]
    assert fresh["execution_id"] != first["execution_id"]
    assert fresh["approval_decision_id"] != first["approval_decision_id"]
    assert len(adapter.submissions) == 2


def test_admin_decision_via_real_http_route_satisfies_shipped_fabric_planner_defaults(
    tmp_path,
) -> None:
    """CR-01/CR-05 regression: the real ``record_remediation_decision``
    route must let an admin satisfy this shipped Fabric/catalog planner's
    own production-representative default ``ApprovalEngine`` policies
    (``tests/fixtures/sample_remediation_planning.json``, the exact
    fixture the 03.5-REVIEW.md deep review used to prove both defects) --
    not just a hand-picked test helper that mirrors each requirement row's
    own presentation-text role directly, as :func:`_approve` does.

    Before the CR-01 fix, every one of this plan's real requirement rows
    refused as ``wrong_role_decision`` even for an admin decision. The
    CR-01 fix alone (a shared ``DEFAULT_ROLE_ID`` fallback) made the plan
    executable again, but at the cost of a *new* defect (CR-05): it let
    that *same single* admin decision satisfy *every* distinct
    organizational role on the plan at once, defeating multi-stakeholder
    governance entirely. This test proves the corrected behavior: an
    admin decision without a literal organizational role claim is an
    explicit, truthfully-recorded *override* (``admin_override: True``),
    attests exactly *one* selected role (``approval_role_id``), and a
    multi-role plan is not executable until a *separate* decision has
    been recorded for every distinct role it requires.
    """
    client, _, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    requirements = plan.get("approval_requirements") or []
    assert requirements, "fixture plan must carry real requirement rows"
    distinct_role_ids = sorted(
        {str(row.get("role_id") or row.get("role") or "") for row in requirements}
    )
    assert len(distinct_role_ids) > 1, "fixture plan must require more than one distinct role"

    preview = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth(ADMIN_TOKEN)
    )
    assert preview.status_code == 200, preview.text
    snapshot = preview.json()["data"]["execution_snapshot"]

    # A single admin decision, explicitly selecting exactly one role,
    # satisfies that one row only -- and is recorded as an explicit,
    # truthful admin override (the admin holds no literal organizational
    # role claim for it).
    first_role_id = distinct_role_ids[0]
    approval = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(ADMIN_TOKEN),
        json={
            "decision": "approved",
            "reason": "Admin approved after full evidence review",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": snapshot["snapshot_hash"],
            "role_id": first_role_id,
        },
    )
    assert approval.status_code == 201, approval.text
    recorded = approval.json()["data"]
    assert recorded["approver_roles"] == ["admin", "approver"]
    assert recorded["approval_role_id"] == first_role_id.strip().casefold()
    assert recorded["admin_override"] is True

    approvals_after_one = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/approvals", headers=_auth(ADMIN_TOKEN)
    ).json()["data"]
    satisfied_after_one = {
        row["satisfied"] for row in approvals_after_one["approval_requirements"]
    }
    # Exactly one decision cannot satisfy a multi-role plan (CR-05 fix):
    # some rows are satisfied, but not all of them.
    assert satisfied_after_one == {True, False}, approvals_after_one["approval_requirements"]

    # The plan remains unexecutable until every distinct role has its own
    # decision (CR-05 fix: one decision satisfies at most one requirement).
    premature_execution = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth(ADMIN_TOKEN)
    )
    assert premature_execution.status_code == 409, premature_execution.text
    assert (
        premature_execution.json()["error"]["details"]["reason"]
        == "approval_requirements_unmet"
    )

    # Record a separate, explicit decision for every remaining distinct
    # role -- each one is its own truthful admin override, attesting
    # exactly one role.
    for role_id in distinct_role_ids[1:]:
        remaining_approval = client.post(
            f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
            headers=_auth(ADMIN_TOKEN),
            json={
                "decision": "approved",
                "reason": "Admin approved after full evidence review",
                "action_version": plan["action_version"],
                "expires_at": _future_expiry(),
                "preview_snapshot_hash": snapshot["snapshot_hash"],
                "role_id": role_id,
            },
        )
        assert remaining_approval.status_code == 201, remaining_approval.text
        assert remaining_approval.json()["data"]["admin_override"] is True

    approvals = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/approvals", headers=_auth(ADMIN_TOKEN)
    ).json()["data"]
    assert approvals["approval_requirements"], "must have real requirement rows to prove the fix"
    assert all(row["satisfied"] for row in approvals["approval_requirements"]), (
        approvals["approval_requirements"]
    )

    execution = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth(ADMIN_TOKEN)
    )
    assert execution.status_code == 202, execution.text
    assert execution.json()["data"]["status"] == "running"


CHANGE_MANAGER_TOKEN = "change-manager-claim-token-0123"
SECURITY_OWNER_TOKEN = "security-owner-claim-token-01234"


def test_two_correctly_role_attested_decisions_satisfy_via_real_http_route(
    tmp_path,
) -> None:
    """Phase 03.5 CR-05 regression: two distinct principals, each holding a
    literal organizational role claim (not an admin override) for exactly
    one of this plan's distinct required roles, each record their own
    decision through the real HTTP route -- genuine, non-override,
    multi-stakeholder attestation. Neither decision alone satisfies the
    whole plan; together, both required rows are satisfied and the plan
    executes.
    """
    principals = {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        CHANGE_MANAGER_TOKEN: Principal(
            subject="change-manager@example.com",
            grants=(Grant("approver"),),
            org_roles=("Change Manager",),
        ),
        SECURITY_OWNER_TOKEN: Principal(
            subject="security-owner@example.com",
            grants=(Grant("approver"),),
            org_roles=("Change Advisory Board",),
        ),
    }
    client, _, _ = _client(tmp_path, principals=principals)
    plans_response = client.get("/api/v1/remediation/plans", headers=_auth(ADMIN_TOKEN))
    assert plans_response.status_code == 200, plans_response.text
    plan = next(
        p for p in plans_response.json()["data"]["plans"]
        if p["action_id"] == "controlled-patch-recovery"
    )
    requirements = plan.get("approval_requirements") or []
    change_manager_row = next(row for row in requirements if row["role"] == "Change Manager")
    cab_row = next(row for row in requirements if row["role"] == "Change Advisory Board")
    assert change_manager_row["role_id"] != cab_row["role_id"]

    preview = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth(CHANGE_MANAGER_TOKEN)
    ).json()["data"]
    snapshot_hash = preview["execution_snapshot"]["snapshot_hash"]

    first = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(CHANGE_MANAGER_TOKEN),
        json={
            "decision": "approved",
            "reason": "Change Manager approves the change record",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": snapshot_hash,
            "role_id": change_manager_row["role_id"],
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["data"]["admin_override"] is False

    execution_attempt = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth(ADMIN_TOKEN)
    )
    assert execution_attempt.status_code == 409, execution_attempt.text

    second = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(SECURITY_OWNER_TOKEN),
        json={
            "decision": "approved",
            "reason": "Change Advisory Board approves the change record",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": snapshot_hash,
            "role_id": cab_row["role_id"],
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["admin_override"] is False

    approvals = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/approvals", headers=_auth(ADMIN_TOKEN)
    ).json()["data"]
    change_manager_after = next(
        row for row in approvals["approval_requirements"] if row["role"] == "Change Manager"
    )
    cab_after = next(
        row for row in approvals["approval_requirements"] if row["role"] == "Change Advisory Board"
    )
    assert change_manager_after["satisfied"] is True
    assert change_manager_after["approver"] == "change-manager@example.com"
    assert cab_after["satisfied"] is True
    assert cab_after["approver"] == "security-owner@example.com"


def test_defender_configuration_preview_approval_and_execute_are_snapshot_bound(
    tmp_path,
) -> None:
    planner = remediation_planner()
    original_generate = planner.generate_plans

    def generate_with_configuration_plan():
        result = original_generate()
        source = next(
            row
            for row in result["plans"]
            if row["action_id"] == "controlled-patch-recovery"
        )
        configured = {
            **source,
            "action_id": ENABLE_DEFENDER_SERVERS_P1,
            "resource_key": VM_PAYMENTS_ID,
            "resource": {
                **source["resource"],
                "id": VM_PAYMENTS_ID,
            },
            "subscription_id": "sub-1",
            # This test exercises the Defender-configuration execute path's
            # snapshot binding, not per-role approval governance (that is
            # covered narrowly by Plan 03.5-05's own dedicated tests) --
            # the recording principal here holds only RBAC-derived
            # approver_roles (Phase 03.5, D-03), which cannot satisfy the
            # source patch plan's organizational-role policy set.
            "approval_requirements": [],
            "business_decision": {
                "disposition": "schedule",
                "business_impact": {"status": "known"},
                "review_requirements": [],
                "unknowns": [],
                "urgency_rationale": {
                    "evidence_citations": ["assessment:assessment-1"]
                },
            },
        }
        result["plans"] = [configured]
        planner.repository.replace_generation(result["plans"])
        return result

    planner.generate_plans = generate_with_configuration_plan
    defender_adapter = _DefenderConfigurationAdapter()
    client, _, _ = _client(
        tmp_path,
        planner=planner,
        defender_adapter=defender_adapter,
    )
    plan = _plans(client)[0]
    preview_response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview",
        headers=_auth(),
    )
    assert preview_response.status_code == 200, preview_response.text
    snapshot = preview_response.json()["data"]["execution_snapshot"]
    assert snapshot["action_id"] == ENABLE_DEFENDER_SERVERS_P1
    assert snapshot["request"]["body"] == {
        "properties": {"pricingTier": "Standard", "subPlan": "P1"}
    }

    approval = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(),
        json={
            "decision": "approved",
            "reason": "Security owner approved the exact configuration",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": snapshot["snapshot_hash"],
        },
    )
    assert approval.status_code == 201, approval.text
    assert (
        approval.json()["data"]["execution_snapshot"]["snapshot_hash"]
        == snapshot["snapshot_hash"]
    )
    approved_workflow = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow",
        headers=_auth(),
    ).json()["data"]
    assert approved_workflow["approval"]["current"] is True
    assert approved_workflow["recommended_step"] == "run"

    execution = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(),
    )
    assert execution.status_code == 202, execution.text
    assert execution.json()["data"]["status"] == "running"
    assert len(defender_adapter.submissions) == 1
    running_workflow = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow",
        headers=_auth(),
    ).json()["data"]
    assert running_workflow["execution"]["status"] == "running"
    assert running_workflow["recommended_step"] == "verify"


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


def test_scoped_execute_uses_the_same_hybrid_providers_as_preview_and_approval(
    tmp_path,
) -> None:
    unscoped_planner = remediation_planner(repository=PlanRepository())
    execution_store = RemediationExecutionStore()
    decision_store = RemediationDecisionStore()
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=RecordingPatchExecutionAdapter(),
        require_human_approval=False,
    )

    def scoped_planner_factory():
        planner = remediation_planner(
            repository=PlanRepository(decision_store=decision_store)
        )
        original_generate_plans = planner.generate_plans

        def generate_eligible_scoped_plans():
            result = original_generate_plans()
            for row in result["plans"]:
                if row.get("action_id") == "controlled-patch-recovery":
                    row["resource_key"] = VM_PAYMENTS_ID
                    row["subscription_id"] = "sub-1"
                    row["resource"] = {
                        **(row.get("resource") or {}),
                        "id": VM_PAYMENTS_ID,
                    }
                    # This test exercises scope routing across hybrid
                    # providers, not per-role approval governance -- the
                    # recording principal here holds only RBAC-derived
                    # approver_roles (Phase 03.5, D-03).
                    row["approval_requirements"] = []
                    row["business_decision"] = {
                        "disposition": "act_now",
                        "business_impact": {"status": "known"},
                        "review_requirements": [],
                        "unknowns": [],
                        "urgency_rationale": {
                            "evidence_citations": ["assessment:assess-001"]
                        },
                    }
            planner.repository.replace_generation(result["plans"])
            return result

        planner.generate_plans = generate_eligible_scoped_plans
        return planner

    def execution_service_for_scope(scope: Scope) -> RemediationExecutionService:
        if list(scope.values("subscription")) == ["sub-1"]:
            planner = scoped_planner_factory()
            planner.generate_plans()
            patching = patching_service
        else:
            planner = unscoped_planner
            patching = None
        return RemediationExecutionService(
            plan_repository=getattr(planner, "repository", None),
            patching_service=patching,
            execution_store=execution_store,
            allow_self_approval=True,
        )

    def fresh_scoped_planner(_subscription_ids):
        return scoped_planner_factory()

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(
            tmp_path / "aiops", secret_writer=FakeSecretWriter()
        ),
        authenticator=StaticTokenAuthenticator(
            {
                SUBSCRIPTION_OPERATOR_TOKEN: Principal(
                    subject="subscription-operator@example.com",
                    grants=(
                        Grant("operator", Scope({"subscription": ["sub-1"]})),
                        Grant("approver", Scope({"subscription": ["sub-1"]})),
                    ),
                )
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: unscoped_planner,
        patching_provider=lambda: None,
        hybrid_remediation_provider=fresh_scoped_planner,
        hybrid_patching_provider=lambda subscription_ids: (
            patching_service if subscription_ids == ["sub-1"] else None
        ),
        execution_provider=execution_service_for_scope,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    headers = _auth(SUBSCRIPTION_OPERATOR_TOKEN)
    plan = next(
        p
        for p in client.get("/api/v1/remediation/plans", headers=headers).json()["data"][
            "plans"
        ]
        if p["action_id"] == "controlled-patch-recovery"
    )
    preview = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=headers
    ).json()["data"]

    approval = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=headers,
        json={
            "decision": "approved",
            "reason": "CAB approved exact server preview",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": preview["execution_snapshot"]["snapshot_hash"],
        },
    )
    assert approval.status_code == 201, approval.text

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=headers,
    )

    assert response.status_code == 202, response.text
    assert response.json()["data"]["status"] == "running"


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
    assert "/api/v1/remediation/plans/{plan_id}/workflow" in paths
    assert "/api/v1/remediation/executions/{execution_id}" in paths


def test_execution_retry_and_list_endpoints_are_mounted(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    assert "/api/v1/remediation/executions/{execution_id}/retry" in paths
    assert "/api/v1/remediation/executions/{execution_id}/cancel" in paths
    assert "/api/v1/remediation/plans/{plan_id}/executions" in paths


def test_get_execution_response_includes_verification_and_history_fields(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )
    assert response.status_code == 202, response.text
    execution_id = response.json()["data"]["execution_id"]

    poll = client.get(f"/api/v1/remediation/executions/{execution_id}", headers=_auth())
    assert poll.status_code == 200, poll.text
    execution = poll.json()["data"]
    for field in (
        "status",
        "verified_state",
        "failure_details",
        "rollback_guidance",
        "attempt_count",
    ):
        assert field in execution


def test_retry_already_succeeded_execution_is_409(tmp_path) -> None:
    client, planner, execution_store = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    response = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    )
    execution_id = response.json()["data"]["execution_id"]
    execution_store.update(execution_id, status="succeeded")

    retry_response = client.post(
        f"/api/v1/remediation/executions/{execution_id}/retry", headers=_auth()
    )

    assert retry_response.status_code == 409, retry_response.text
    assert retry_response.json()["error"]["code"] == "conflict"


def test_cancel_authorizes_off_execution_scope_after_plan_disappears_from_repository(
    tmp_path,
) -> None:
    """CR-01/D-02: cancel must not 404 just because the plan regenerated away.

    ``cancel_execution`` used to narrow through ``_get_scoped_plan`` before
    ever reaching the execution service, so an execution whose originating
    plan disappeared (e.g. missing_kbs cleared and the row no longer
    surfaces) became permanently uncancellable via an opaque plan-not-found
    404. It must now authorize from the execution record's own scope
    attributes and reach the execution service regardless.
    """
    client, planner, execution_store = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)
    decision = planner.repository.decisions.list(plan["plan_id"])[-1]
    queued, _ = execution_store.create_or_get(
        plan["plan_id"],
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=decision["execution_snapshot"],
    )

    # Simulate regeneration dropping the row entirely.
    planner.repository.replace_generation([])
    assert planner.repository.get(plan["plan_id"]) is None

    response = client.post(
        f"/api/v1/remediation/executions/{queued['execution_id']}/cancel",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "cancelled"


def test_retry_after_plan_disappears_is_rejected_by_service_state_not_by_404(
    tmp_path,
) -> None:
    """The router no longer 404s retry via ``_get_scoped_plan``; any rejection
    for a missing plan now comes as a typed 409 from the execution service's
    own revalidation, distinguishable from "execution truly doesn't exist"."""
    client, planner, execution_store = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    executed = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    ).json()["data"]
    execution_id = executed["execution_id"]
    execution_store.update(execution_id, status="failed")

    # Simulate regeneration dropping the row entirely.
    planner.repository.replace_generation([])
    assert planner.repository.get(plan["plan_id"]) is None

    retry_response = client.post(
        f"/api/v1/remediation/executions/{execution_id}/retry", headers=_auth()
    )

    assert retry_response.status_code != 404, retry_response.text
    assert retry_response.status_code == 409, retry_response.text
    body = retry_response.json()
    assert body["error"]["code"] == "conflict"
    assert body["error"]["details"]["reason"] == "plan_not_found"


def test_get_execution_outside_plan_scope_is_404(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)
    created = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(),
    ).json()["data"]

    response = client.get(
        f"/api/v1/remediation/executions/{created['execution_id']}",
        headers=_auth(SCOPED_OPERATOR_TOKEN),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_execution_still_returns_200_after_plan_row_disappears_entirely(
    tmp_path,
) -> None:
    """Recommendation 1 acceptance (a): even when the row disappears from the
    next generation (not just its missing_kbs changing), the same in-scope
    caller who executed it must still be able to poll the execution."""
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    executed = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    ).json()["data"]
    execution_id = executed["execution_id"]

    # Simulate the target disappearing from the next generation entirely
    # (e.g. the asset no longer surfaces any patch findings at all) --
    # stronger than a missing_kbs mutation: the plan_id itself is now gone
    # from the repository, not just re-derived to the same value.
    planner.repository.replace_generation([])
    assert planner.repository.get(plan["plan_id"]) is None

    response = client.get(
        f"/api/v1/remediation/executions/{execution_id}", headers=_auth()
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["execution_id"] == execution_id


def test_cancel_queued_execution_and_return_server_eligibility(tmp_path) -> None:
    client, planner, store = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)
    decision = planner.repository.decisions.list(plan["plan_id"])[-1]
    queued, _ = store.create_or_get(
        plan["plan_id"],
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=decision["execution_snapshot"],
    )

    response = client.post(
        f"/api/v1/remediation/executions/{queued['execution_id']}/cancel",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    execution = response.json()["data"]
    assert execution["status"] == "cancelled"
    assert execution["retryable"] is True
    assert execution["cancellable"] is False
    # Cancelled before ever reaching Azure: the queued attempt never
    # consumed the Azure submission budget (Recommendation 2, Submission
    # Accounting decision), so the full attempt budget remains available.
    assert execution["remaining_attempts"] == 3


def test_submitted_provider_work_is_truthfully_not_cancellable(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)
    execution = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(),
    ).json()["data"]

    response = client.post(
        f"/api/v1/remediation/executions/{execution['execution_id']}/cancel",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    current = response.json()["data"]
    assert current["status"] == "running"
    assert current["cancellable"] is False
    assert current["ineligibility_reason"] == "provider_not_cancellable"
    assert current["history"][-1]["outcome"] == "provider_not_cancellable"


def test_execution_responses_publish_server_owned_eligibility(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    execution = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(),
    ).json()["data"]

    assert execution["retryable"] is False
    assert execution["cancellable"] is False
    assert execution["remaining_attempts"] == 2
    assert execution["ineligibility_reason"] == "provider_not_cancellable"


def test_diagnostics_route_reports_orphaned_executions_over_http(tmp_path) -> None:
    client, _planner, execution_store = _client(tmp_path)

    healthy = client.get("/api/v1/remediation/diagnostics/executions", headers=_auth())
    assert healthy.status_code == 200, healthy.text
    assert healthy.json()["data"]["orphaned_executions"] == []

    legacy = execution_store.create("RMP-does-not-exist", requested_by="legacy@example.com")

    response = client.get("/api/v1/remediation/diagnostics/executions", headers=_auth())

    assert response.status_code == 200, response.text
    orphans = response.json()["data"]["orphaned_executions"]
    assert len(orphans) == 1
    assert orphans[0]["execution_id"] == legacy["execution_id"]
    assert orphans[0]["reason"] == "legacy_scope_unresolvable"


def test_diagnostics_route_hides_orphans_from_a_scoped_operator(tmp_path) -> None:
    """CR-01: a caller with a narrowly-scoped operate grant must not see
    system-wide orphaned-execution data. Legacy/orphaned records have no
    derivable scope attributes by definition, so they fail closed for any
    restricted caller -- the same rule ``_authorize_execution_scope`` already
    applies to a single legacy execution read -- and remain visible only to
    an unrestricted (system-wide) caller."""
    client, _planner, execution_store = _client(tmp_path)
    execution_store.create("RMP-does-not-exist", requested_by="legacy@example.com")

    scoped = client.get(
        "/api/v1/remediation/diagnostics/executions",
        headers=_auth(SUBSCRIPTION_OPERATOR_TOKEN),
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["data"]["orphaned_executions"] == []

    unrestricted = client.get(
        "/api/v1/remediation/diagnostics/executions", headers=_auth()
    )
    assert unrestricted.status_code == 200, unrestricted.text
    assert len(unrestricted.json()["data"]["orphaned_executions"]) == 1


def test_diagnostics_route_does_not_collide_with_execution_by_id_route(tmp_path) -> None:
    client, planner, _ = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    executed = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    ).json()["data"]

    diagnostics = client.get("/api/v1/remediation/diagnostics/executions", headers=_auth())
    assert diagnostics.status_code == 200, diagnostics.text
    assert diagnostics.json()["data"]["orphaned_executions"] == []

    by_id = client.get(
        f"/api/v1/remediation/executions/{executed['execution_id']}", headers=_auth()
    )
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["data"]["execution_id"] == executed["execution_id"]



def test_supersede_response_includes_supersedes_field(tmp_path) -> None:
    client, planner, execution_store = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    executed = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    ).json()["data"]
    execution_id = executed["execution_id"]
    execution_store.update(execution_id, status="failed")

    response = client.post(
        f"/api/v1/remediation/executions/{execution_id}/supersede",
        headers=_auth(),
        json={"reason": "Blocker resolved"},
    )

    assert response.status_code == 202, response.text
    body = response.json()["data"]
    assert body["supersedes"] == execution_id
    assert body["execution_id"] != execution_id


def test_supersede_out_of_scope_execution_is_404(tmp_path) -> None:
    """Same 403/404 narrowing behavior as retry/cancel: an out-of-scope
    caller cannot supersede an execution outside their operate scope."""
    client, planner, execution_store = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)
    created = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(),
    ).json()["data"]
    execution_store.update(created["execution_id"], status="failed")

    response = client.post(
        f"/api/v1/remediation/executions/{created['execution_id']}/supersede",
        headers=_auth(SCOPED_OPERATOR_TOKEN),
        json={"reason": "Blocker resolved"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


APPROVER_ONLY_TOKEN = "approver-only-token-0123456"
OPERATE_ONLY_TOKEN = "operate-only-token-01234567"


def _separation_of_duties_principals() -> dict:
    return {
        OPERATOR_TOKEN: Principal(
            subject="operator@example.com",
            grants=(Grant("operator"), Grant("approver")),
            # Phase 03.5 CR-05 fix: these RBAC-separation tests record a
            # decision against this module's default multi-role
            # production-representative plan without exercising per-role
            # governance itself (that is covered narrowly by the
            # dedicated new role-governance regression tests) -- holding
            # every organizational role this fixture's own policies use
            # keeps whichever single row `_first_role_id`-style explicit
            # selection targets always authorized.
            org_roles=_ALL_FIXTURE_ORG_ROLES,
        ),
        APPROVER_ONLY_TOKEN: Principal(
            subject="approver-only@example.com",
            grants=(Grant("approver"),),
            org_roles=_ALL_FIXTURE_ORG_ROLES,
        ),
        OPERATE_ONLY_TOKEN: Principal(
            subject="operate-only@example.com", grants=(Grant("operator"),)
        ),
    }


def test_approver_only_can_record_decision_but_cannot_execute(tmp_path) -> None:
    client, _, _ = _client(tmp_path, principals=_separation_of_duties_principals())
    plan = _patch_recovery_plan(client)
    preview = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth(APPROVER_ONLY_TOKEN)
    ).json()["data"]

    approval = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(APPROVER_ONLY_TOKEN),
        json={
            "decision": "approved",
            "reason": "Approver-only recorded this decision",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": preview["execution_snapshot"]["snapshot_hash"],
            "role_id": _first_role_id(plan),
        },
    )
    assert approval.status_code == 201, approval.text

    execute = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(APPROVER_ONLY_TOKEN),
    )
    assert execute.status_code == 403, execute.text


def test_operate_only_can_execute_an_already_approved_plan_but_cannot_record_a_decision(
    tmp_path,
) -> None:
    client, planner, _ = _client(tmp_path, principals=_separation_of_duties_principals())
    # This test exercises RBAC separation (approve vs operate), not
    # per-role approval governance -- the recording principal here holds
    # only RBAC-derived approver_roles (Phase 03.5, D-03), which cannot
    # satisfy the source plan's rich organizational-role policy set. Wrap
    # generate_plans again (every route re-calls it) so the override
    # survives each fresh regeneration.
    inner_generate_plans = planner.generate_plans

    def generate_plans_with_empty_approval_requirements():
        result = inner_generate_plans()
        for row in result["plans"]:
            if row.get("action_id") == "controlled-patch-recovery":
                row["approval_requirements"] = []
        planner.repository.replace_generation(result["plans"])
        return result

    planner.generate_plans = generate_plans_with_empty_approval_requirements
    plan = _patch_recovery_plan(client)

    decision_attempt = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(OPERATE_ONLY_TOKEN),
        json={
            "decision": "approved",
            "reason": "Operate-only should not be able to record this",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
        },
    )
    assert decision_attempt.status_code == 403, decision_attempt.text

    preview = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth(APPROVER_ONLY_TOKEN)
    ).json()["data"]
    approval = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(APPROVER_ONLY_TOKEN),
        json={
            "decision": "approved",
            "reason": "Approver records the decision",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": preview["execution_snapshot"]["snapshot_hash"],
        },
    )
    assert approval.status_code == 201, approval.text

    execute = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute",
        headers=_auth(OPERATE_ONLY_TOKEN),
    )
    assert execute.status_code == 202, execute.text


def test_recorded_decision_approver_roles_names_the_satisfying_capacity_not_every_held_role(
    tmp_path,
) -> None:
    """An operator+approver combined persona's decision is durably recorded
    under 'approver' (the role that actually satisfies the approve action),
    never 'operator' alone (Phase 03.5, T-03.5-14)."""
    client, _, _ = _client(tmp_path, principals=_separation_of_duties_principals())
    plan = _patch_recovery_plan(client)
    preview = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth(OPERATOR_TOKEN)
    ).json()["data"]

    approval = client.post(
        f"/api/v1/remediation-plans/{plan['plan_id']}/decisions",
        headers=_auth(OPERATOR_TOKEN),
        json={
            "decision": "approved",
            "reason": "Combined-role persona approves",
            "action_version": plan["action_version"],
            "expires_at": _future_expiry(),
            "preview_snapshot_hash": preview["execution_snapshot"]["snapshot_hash"],
            "role_id": _first_role_id(plan),
        },
    )
    assert approval.status_code == 201, approval.text
    decision = approval.json()["data"]

    assert "approver" in decision["approver_roles"]
    assert "operator" not in decision["approver_roles"]
