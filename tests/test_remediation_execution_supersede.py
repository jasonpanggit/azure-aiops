"""Audited supersede tests (Phase 03.3 Recommendation 2 escape valve).

When a real, persistent external blocker (a genuine RBAC denial, for
example) legitimately exhausts the three-attempt submission budget, an
operator can supersede the exhausted execution: a brand-new, freshly
approved-and-revalidated execution that explicitly references the old one,
without ever mutating the old execution's audit trail (CONTEXT.md's
Supersession decision).
"""

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
from intelligence.remediation.approval_decisions import (
    RemediationDecisionStore,
    execution_snapshot_hash,
)
from intelligence.remediation.execution_service import (
    MAX_EXECUTION_ATTEMPTS,
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import (
    ExecutionClaimConflict,
    RemediationExecutionStore,
)
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.service import SubscriptionOnboardingService
from operations.patching.adapters import PatchExecutionResult, PatchExecutionUnavailable
from operations.patching.service import PatchingService
from tests.test_api_http import FakeSecretWriter

OPERATOR_TOKEN = "operator-token-0123456789abcd"
SCOPED_OPERATOR_TOKEN = "scoped-operator-token-012345"
VM_PAYMENTS_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 9, 4, tzinfo=UTC)


class _FakeVulnerabilityService:
    def __init__(self) -> None:
        self.freshness = "2026-09-04T00:00:00Z"

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


class _ToggleAdapter:
    """Fake patch adapter: raises a submitted rejection until told to succeed."""

    name = "toggle"

    def __init__(self) -> None:
        self.failing = True
        self.submissions: list = []

    def submit(self, run, target) -> PatchExecutionResult:
        self.submissions.append((run, target))
        if self.failing:
            raise PatchExecutionUnavailable(
                "RBAC role assignment missing",
                provider_submitted=True,
                failure_class="provider_authorization",
            )
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id="https://management.azure.com/op/fixed-1",
            state="submitted",
            message="Accepted by Azure",
        )


def _future_expiry() -> str:
    return (datetime.now(UTC) + timedelta(days=30)).isoformat()


def _auth(token: str = OPERATOR_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(tmp_path, *, adapter=None):
    decision_store = RemediationDecisionStore()
    planner = remediation_planner(repository=PlanRepository(decision_store=decision_store))
    original_generate_plans = planner.generate_plans

    def generate_eligible_plans():
        result = original_generate_plans()
        for row in result["plans"]:
            if row.get("action_id") == "controlled-patch-recovery":
                row["resource_key"] = VM_PAYMENTS_ID
                row["subscription_id"] = "sub-1"
                row["resource"] = {**(row.get("resource") or {}), "id": VM_PAYMENTS_ID}
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

    planner.generate_plans = generate_eligible_plans
    execution_store = RemediationExecutionStore()
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=adapter,
        require_human_approval=False,
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(
            tmp_path / "aiops", secret_writer=FakeSecretWriter()
        ),
        authenticator=StaticTokenAuthenticator(
            {
                OPERATOR_TOKEN: Principal(
                    subject="operator@example.com", grants=(Grant("operator"),)
                ),
                SCOPED_OPERATOR_TOKEN: Principal(
                    subject="scoped-operator@example.com",
                    grants=(Grant("operator", Scope({"subscription": ["sub-does-not-exist"]})),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: planner,
        execution_provider=lambda scope: RemediationExecutionService(
            plan_repository=planner.repository,
            patching_service=patching_service,
            execution_store=execution_store,
        ),
    )
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        planner,
        execution_store,
    )


def _plans(client: TestClient) -> list[dict]:
    response = client.get("/api/v1/remediation/plans", headers=_auth())
    assert response.status_code == 200, response.text
    return response.json()["data"]["plans"]


def _patch_recovery_plan(client: TestClient) -> dict:
    return next(
        p for p in _plans(client) if p["action_id"] == "controlled-patch-recovery"
    )


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
    # than one row). This test module exercises execution mechanics
    # assuming approval is already fully granted, not per-role separation
    # of duties (that is covered narrowly by dedicated tests elsewhere).
    distinct_role_ids = sorted(
        {
            str(row.get("role_id") or row.get("role") or "")
            for row in stored_plan.get("approval_requirements") or []
        }
    )
    if not distinct_role_ids:
        distinct_role_ids = [""]
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
        )


def _exhaust_via_router(client: TestClient, plan: dict) -> str:
    """Execute + retry twice through the router, leaving the budget spent."""
    executed = client.post(
        f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth()
    ).json()["data"]
    assert executed["status"] == "failed"
    execution_id = executed["execution_id"]
    for _ in range(MAX_EXECUTION_ATTEMPTS - 1):
        retried = client.post(
            f"/api/v1/remediation/executions/{execution_id}/retry", headers=_auth()
        ).json()["data"]
        assert retried["status"] == "failed"
    return execution_id


# ---------------------------------------------------------------------------
# Task 1: one full supersede path end-to-end, through the router
# ---------------------------------------------------------------------------


def test_supersede_creates_a_new_execution_and_preserves_old_history(tmp_path) -> None:
    adapter = _ToggleAdapter()
    client, planner, execution_store = _client(tmp_path, adapter=adapter)
    plan = _patch_recovery_plan(client)
    _approve(planner, plan)

    execution_id = _exhaust_via_router(client, plan)
    attempts_before = execution_store.get(execution_id)["attempts"]

    supersede_response = client.post(
        f"/api/v1/remediation/executions/{execution_id}/supersede",
        headers=_auth(),
        json={"reason": "RBAC role assignment corrected"},
    )

    assert supersede_response.status_code == 202, supersede_response.text
    new_data = supersede_response.json()["data"]
    new_execution_id = new_data["execution_id"]
    assert new_execution_id != execution_id
    assert new_data["supersedes"] == execution_id

    follow_up = client.get(
        f"/api/v1/remediation/executions/{execution_id}", headers=_auth()
    )
    assert follow_up.status_code == 200, follow_up.text
    old_data = follow_up.json()["data"]
    assert old_data["superseded_by"] == new_execution_id
    assert old_data["attempts"] == attempts_before


# ---------------------------------------------------------------------------
# Task 2: eligibility guards, legacy edge cases, execution_view projections
# ---------------------------------------------------------------------------


def _service_and_store(*, adapter) -> tuple[RemediationExecutionService, RemediationExecutionStore, dict]:
    store = RemediationExecutionStore()
    repository = PlanRepository()
    plan = {
        "plan_id": "RMP-SUPERSEDE-1",
        "action_id": "controlled-patch-recovery",
        "opportunity_type": "Patch and vulnerability debt",
        "action_version": "v1",
        "resource_key": VM_PAYMENTS_ID,
        "resource": {"id": VM_PAYMENTS_ID, "name": "vm-payments", "entity_type": "VirtualMachine"},
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
            "rollback_actions": ["Restore from last known-good snapshot"],
            "automatic_rollback": False,
            "execution_status": "Not Executed",
        },
    }
    repository.replace_generation([plan])
    snapshot = {
        "target_id": VM_PAYMENTS_ID,
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
    patching_service = PatchingService(
        _FakeVulnerabilityService(), adapter=adapter, require_human_approval=False
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        now=lambda: NOW,
    )
    return service, store, plan


def _exhaust(service: RemediationExecutionService, plan: dict) -> str:
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "failed"
    execution_id = result["execution_id"]
    for _ in range(MAX_EXECUTION_ATTEMPTS - 1):
        retried = service.retry(execution_id)
        assert retried["status"] == "failed"
    return execution_id


def test_supersede_refuses_an_active_execution() -> None:
    adapter = _ToggleAdapter()
    adapter.failing = False
    service, _store, plan = _service_and_store(adapter=adapter)
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "running"

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.supersede(result["execution_id"], requested_by="operator@example.com", reason="x")
    assert excinfo.value.reason == "execution_active"


def test_supersede_refuses_a_submission_ambiguous_execution() -> None:
    class _AmbiguousAdapter:
        name = "ambiguous"

        def submit(self, run, target) -> PatchExecutionResult:
            raise PatchExecutionUnavailable(
                "Azure Resource Manager was unreachable: connection reset",
                provider_submitted=True,
                failure_class="submission_ambiguous",
            )

    service, _store, plan = _service_and_store(adapter=_AmbiguousAdapter())
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "failed"

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.supersede(result["execution_id"], requested_by="operator@example.com", reason="x")
    assert excinfo.value.reason == "submission_ambiguous"


def test_supersede_refuses_an_already_superseded_execution() -> None:
    adapter = _ToggleAdapter()
    service, _store, plan = _service_and_store(adapter=adapter)
    execution_id = _exhaust(service, plan)

    adapter.failing = False
    first = service.supersede(execution_id, requested_by="operator@example.com", reason="fixed")
    assert first["status"] in {"running", "succeeded"}

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.supersede(execution_id, requested_by="operator@example.com", reason="again")
    assert excinfo.value.reason == "already_superseded"


def test_second_supersede_call_hits_the_store_cas_check_not_a_third_record() -> None:
    """A second supersede on the same old execution_id must raise, not silently
    create a third record."""
    adapter = _ToggleAdapter()
    service, store, plan = _service_and_store(adapter=adapter)
    execution_id = _exhaust(service, plan)

    adapter.failing = False
    service.supersede(execution_id, requested_by="operator@example.com", reason="fixed once")

    before_count = len(store.list_all())
    with pytest.raises(RemediationExecutionError):
        service.supersede(execution_id, requested_by="operator@example.com", reason="fixed twice")
    assert len(store.list_all()) == before_count


# ---------------------------------------------------------------------------
# WR-01: create_superseding enforces the same max_executions capacity
# invariant create_or_get already enforces.
# ---------------------------------------------------------------------------


def _snapshot(*, snapshot_hash: str) -> dict:
    return {
        "target_id": VM_PAYMENTS_ID,
        "patch_ids": ["KB600001"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": "v1",
        "snapshot_hash": snapshot_hash,
    }


def test_create_superseding_enforces_max_executions_capacity() -> None:
    """A store already at capacity must refuse `create_superseding` exactly
    as it already refuses `create_or_get` -- atomically, with no partial
    write and no growth past the configured cap."""
    store = RemediationExecutionStore(max_executions=1)
    record, created = store.create_or_get(
        "RMP-CAPACITY-1",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=_snapshot(snapshot_hash="hash-cap-1"),
    )
    assert created is True
    execution_id = record["execution_id"]
    store.transition(
        execution_id,
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="failed",
        actor="operator@example.com",
        provider_submitted=True,
        failure_class="provider_authorization",
        outcome="failed",
    )
    exhausted = store.get(execution_id)
    assert exhausted["status"] == "failed"

    with pytest.raises(ExecutionClaimConflict) as excinfo:
        store.create_superseding(
            execution_id,
            expected_revision=int(exhausted["revision"]),
            plan_id="RMP-CAPACITY-1",
            requested_by="operator@example.com",
            approved_by="approver@example.com",
            execution_snapshot=_snapshot(snapshot_hash="hash-cap-2"),
            reason="capacity test",
        )
    assert excinfo.value.reason == "execution_store_full"

    # Refused atomically -- the old record must be provably untouched (no
    # superseded_by set, no revision bump) and the store must not have grown.
    assert store.get(execution_id) == exhausted
    assert len(store.list_all()) == 1


# ---------------------------------------------------------------------------
# WR-02: supersede() resolves the target exactly once (no latent double-
# resolution trap).
# ---------------------------------------------------------------------------


def test_supersede_resolves_the_target_exactly_once(monkeypatch) -> None:
    """Before the fix, `supersede()` called `_resolve_target` explicitly and
    then `_submit_and_record` called it again internally on the same
    `(plan, decision)` pair -- wasted work with a latent divergence risk if
    `_resolve_target` ever gained a side effect. Prove exactly one call
    happens now."""
    adapter = _ToggleAdapter()
    service, _store, plan = _service_and_store(adapter=adapter)
    execution_id = _exhaust(service, plan)
    adapter.failing = False

    calls: list = []
    original_resolve_target = service._resolve_target

    def _counting_resolve_target(plan_arg, decision_arg):
        calls.append((plan_arg, decision_arg))
        return original_resolve_target(plan_arg, decision_arg)

    monkeypatch.setattr(service, "_resolve_target", _counting_resolve_target)

    result = service.supersede(
        execution_id, requested_by="operator@example.com", reason="RBAC fixed"
    )
    assert result["status"] == "running"
    assert len(calls) == 1


def test_execution_view_projects_supersedable_for_a_terminal_non_ambiguous_execution() -> None:
    adapter = _ToggleAdapter()
    service, store, plan = _service_and_store(adapter=adapter)
    execution_id = _exhaust(service, plan)

    view = service.execution_view(store.get(execution_id))
    assert view["supersedable"] is True
    assert view["supersede_ineligibility_reason"] == ""


def test_execution_view_projects_not_supersedable_for_an_active_execution() -> None:
    adapter = _ToggleAdapter()
    adapter.failing = False
    service, store, plan = _service_and_store(adapter=adapter)
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "running"

    view = service.execution_view(store.get(result["execution_id"]))
    assert view["supersedable"] is False
    assert view["supersede_ineligibility_reason"] == "execution_active"


# ---------------------------------------------------------------------------
# Task 3: the full E2E-shaped regression scenario from CONTEXT.md
# ---------------------------------------------------------------------------


def test_budget_exhausted_blocker_fixed_supersede_succeeds_old_history_untouched() -> None:
    """CONTEXT.md's own narrative, end to end:

    Repeated submitted failures exhaust the budget, retry is refused, the
    external blocker is fixed, supersede creates a new execution, the new
    execution succeeds, the old execution's history is provably untouched,
    and both records cross-reference each other.
    """
    adapter = _ToggleAdapter()
    service, store, plan = _service_and_store(adapter=adapter)

    # 1-2: exhaust the submission budget with a genuine (submitted) rejection.
    old_execution_id = _exhaust(service, plan)
    old_record_before = store.get(old_execution_id)
    assert old_record_before["attempts"][-1]["failure_class"] == "provider_authorization"

    old_view = service.execution_view(old_record_before)
    assert old_view["remaining_attempts"] == 0
    assert old_view["retryable"] is False
    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(old_execution_id)
    assert excinfo.value.reason == "max_attempts_exceeded"

    # 3: the external RBAC blocker is fixed.
    adapter.failing = False

    # 4: supersede with a non-empty reason.
    superseded_view = service.supersede(
        old_execution_id,
        requested_by="operator@example.com",
        reason="RBAC role assignment corrected",
    )
    new_execution_id = superseded_view["execution_id"]
    assert new_execution_id != old_execution_id

    # 5: the new execution reaches a submitted/running state (this fixture's
    # adapter succeeds synchronously; no verifier is configured here, so the
    # terminal state after a successful submission is "running").
    assert superseded_view["status"] == "running"

    # 6: the OLD execution's attempts are provably unchanged.
    old_record_after = store.get(old_execution_id)
    assert old_record_after["attempts"] == old_record_before["attempts"]
    assert len(old_record_after["attempts"]) == MAX_EXECUTION_ATTEMPTS

    # 7: bidirectional lineage.
    assert old_record_after["superseded_by"] == new_execution_id
    new_record = store.get(new_execution_id)
    assert new_record["supersedes"] == old_execution_id
