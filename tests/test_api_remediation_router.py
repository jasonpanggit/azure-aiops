from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from remediation_scenario import remediation_planner

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.runtime import _attach_live_defender_correlator
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.remediation.execution_service import RemediationExecutionService
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.service import SubscriptionOnboardingService
from operations.defender_configuration import ENABLE_DEFENDER_SERVERS_P1
from operations.patching.models import AvailablePatch, PatchTarget
from semantic.live_operations import LiveRemediationPlanner
from tests.test_api_http import FakeSecretWriter

ADMIN_TOKEN = "admin-token-0123456789abcdef"
OPERATOR_TOKEN = "operator-token-0123456789abcd"
READER_TOKEN = "reader-token-0123456789abcdef"
SCOPED_READER_TOKEN = "scoped-reader-token-012345678"
VM_PAYMENTS_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-prod/providers/"
    "microsoft.compute/virtualmachines/vm-payments"
)
LIVE_SUBSCRIPTION_ID = "33333333-3333-3333-3333-333333333333"
LIVE_VM_PAYMENTS_ID = (
    f"/subscriptions/{LIVE_SUBSCRIPTION_ID}/resourcegroups/rg-prod/providers/"
    "microsoft.compute/virtualmachines/vm-payments"
)


class _PatchingService:
    def __init__(self) -> None:
        self.patch_ids = ["KB600002", "KB600001"]

    def target(self, target_id: str, scope=None) -> PatchTarget | None:
        return PatchTarget(
            target_id=target_id,
            inventory_kind="Azure VM",
            available_patches=tuple(
                AvailablePatch(patch_id=patch_id) for patch_id in self.patch_ids
            ),
        )


class _LiveVulnerabilityService:
    freshness = "2026-09-02T00:00:00Z"

    def __init__(self, *, duplicate_asset_rows: bool = False) -> None:
        self.asset_scope: Scope | None = None
        self.duplicate_asset_rows = duplicate_asset_rows

    def exposures(self, scope=None) -> list[dict]:
        return []

    def defender_overview(self, scope=None) -> dict:
        return {
            "coverage": {
                "recommendations": {"availability": "available", "freshness": "fresh"},
                "alerts": {"availability": "available", "freshness": "fresh"},
                "attack_paths": {"availability": "available", "freshness": "fresh"},
                "secure_score": {"availability": "available", "freshness": "fresh"},
            }
        }

    def defender_posture(self, scope=None) -> list[dict]:
        return [
            {
                "assessment_id": "assessment-live-patch",
                "asset_id": LIVE_VM_PAYMENTS_ID,
                "severity": "High",
                "recommendation": "Install missing security updates",
                "last_assessed_at": self.freshness,
            }
        ]

    def security_alerts(self, scope=None, active_only: bool = False) -> list[dict]:
        return []

    def defender_attack_paths_for_scope(self, scope=None) -> list[dict]:
        return []

    def secure_score_controls(self, scope=None) -> list[dict]:
        return []

    def asset_exposures(self, scope=None) -> list[dict]:
        self.asset_scope = scope
        rows = [
            {
                "asset_id": LIVE_VM_PAYMENTS_ID,
                "name": "vm-payments",
                "inventory_kind": "Azure VM",
                "resource_type": "microsoft.compute/virtualmachines",
                "subscription_id": LIVE_SUBSCRIPTION_ID,
                "business_service": "Checkout",
                "application": "Payments API",
                "environment": "production",
                "owner": "ops@example.com",
                "missing_kbs": ["KB600001"],
                "cve_ids": ["CVE-2026-0001", "CVE-2026-0002"],
                "severities": ["High", "Critical"],
                "priority_score": 95.0,
                "expected_risk_reduction": 80.0,
                "finding_count": 2,
                "cve_count": 2,
                "finding_ids": ["finding-1", "finding-2"],
            }
        ]
        if self.duplicate_asset_rows:
            rows.append({**rows[0], "finding_ids": ["finding-3"]})
        return rows


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
                OPERATOR_TOKEN: Principal(subject="operator@example.com", grants=(Grant("operator"),)),
                READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
                SCOPED_READER_TOKEN: Principal(
                    subject="scoped-reader@example.com",
                    grants=(
                        Grant(
                            "reader",
                            Scope({"subscription": ["sub-does-not-exist"]}),
                        ),
                    ),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: resolved_planner,
        patching_provider=lambda: patching_service,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _client_with_execution_store(
    tmp_path, *, planner=None
) -> tuple[TestClient, Any, RemediationExecutionStore]:
    """A client wired with a real execution store so tests can drive an
    execution directly to any status/ineligibility_reason via the store's
    own transition API, then read it back through /workflow."""
    resolved_planner = planner or remediation_planner()
    store = RemediationExecutionStore()

    def execution_service(scope: Scope) -> RemediationExecutionService:
        return RemediationExecutionService(
            plan_repository=resolved_planner.repository,
            patching_service=None,
            execution_store=store,
        )

    patching_service = _PatchingService()
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(
            tmp_path / "aiops", secret_writer=FakeSecretWriter()
        ),
        authenticator=StaticTokenAuthenticator(
            {
                ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
                OPERATOR_TOKEN: Principal(subject="operator@example.com", grants=(Grant("operator"),)),
                READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: resolved_planner,
        patching_provider=lambda: patching_service,
        execution_provider=execution_service,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    return client, resolved_planner, store


def _auth(token: str = READER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first_plan(client: TestClient) -> dict:
    response = client.get("/api/v1/remediation/plans", headers=_auth())
    assert response.status_code == 200, response.text
    return response.json()["data"]["plans"][0]


def _patch_recovery_plan(client: TestClient) -> dict:
    response = client.get("/api/v1/remediation/plans", headers=_auth())
    assert response.status_code == 200, response.text
    return next(
        plan
        for plan in response.json()["data"]["plans"]
        if plan["action_id"] == "controlled-patch-recovery"
    )


def test_list_plans_returns_envelope_with_plans(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/v1/remediation/plans", headers=_auth())

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["data"]["plans"], list)
    assert len(body["data"]["plans"]) > 0
    assert body["evidence"][0]["source_engine"] == "intelligence.RemediationPlanner"


def test_workflow_projects_five_governed_steps_for_patch_plan(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert [step["label"] for step in workflow["steps"]] == [
        "Select fix",
        "Review impact",
        "Approve",
        "Run",
        "Verify",
    ]
    assert workflow["action"]["action_id"] == "controlled-patch-recovery"
    assert workflow["action"]["family"] == "patch"
    assert workflow["action"]["executable"] is True
    assert workflow["action"]["manual_review_reason"] == ""
    # READER_TOKEN (this test's default _auth()) holds neither operate nor
    # approve -- both new RBAC-derived fields (Phase 03.5, D-03) reflect
    # that server-side, never client-guessable.
    assert workflow["action"]["can_operate"] is False
    assert "operate_ineligible_reason" in workflow["action"]
    assert workflow["approval"]["can_approve"] is False
    assert "approve_ineligible_reason" in workflow["approval"]
    assert workflow["approval"]["status"] == "none"
    assert workflow["preview"]["execution_snapshot"]["patch_ids"]
    assert workflow["recommended_step"] == "approve"
    assert workflow["audit"] == {"decisions": [], "executions": []}


def test_workflow_fails_closed_to_manual_review_for_non_allowlisted_handler(
    tmp_path,
) -> None:
    client = _client(tmp_path)
    plans = client.get(
        "/api/v1/remediation/plans", headers=_auth()
    ).json()["data"]["plans"]
    plan = next(
        row
        for row in plans
        if row["action_id"] == "configuration-baseline-recovery"
    )

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["action"]["family"] == "configuration"
    assert workflow["action"]["executable"] is False
    assert workflow["recommended_step"] == "manual_review"
    assert workflow["preview"]["execution_snapshot"] is None
    assert {
        step["status"]
        for step in workflow["steps"]
        if step["id"] in {"approve", "run", "verify"}
    } == {"blocked"}


def test_workflow_keeps_review_visible_when_executable_preview_is_unavailable(
    tmp_path,
) -> None:
    planner = remediation_planner()
    original_generate = planner.generate_plans

    def generate_defender_plan():
        result = original_generate()
        plan = next(
            row
            for row in result["plans"]
            if row["action_id"] == "controlled-patch-recovery"
        )
        plan["action_id"] = ENABLE_DEFENDER_SERVERS_P1
        planner.repository.replace_generation([plan])
        return {**result, "plans": [plan]}

    planner.generate_plans = generate_defender_plan
    client = _client(tmp_path, planner=planner)
    plan = client.get(
        "/api/v1/remediation/plans", headers=_auth()
    ).json()["data"]["plans"][0]

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["preview"] is None
    assert workflow["preview_error"] == "provider_unavailable"
    assert workflow["recommended_step"] == "review"
    approve = next(step for step in workflow["steps"] if step["id"] == "approve")
    assert approve["status"] == "blocked"


def test_list_plans_filters_by_nested_resource_key(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)
    resource_key = (
        plan.get("resource_key")
        or plan["resource"].get("resource_key")
        or plan["resource"].get("id")
    )

    response = client.get(
        "/api/v1/remediation/plans",
        params={"resource_key": resource_key},
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    plans = response.json()["data"]["plans"]
    assert plan["plan_id"] in {row["plan_id"] for row in plans}
    assert {
        (
            row.get("resource_key")
            or row.get("resource", {}).get("resource_key")
            or row.get("resource", {}).get("id")
        )
        for row in plans
    } == {resource_key}


def test_get_plan_returns_full_plan(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.get(f"/api/v1/remediation/plans/{plan['plan_id']}", headers=_auth())

    assert response.status_code == 200, response.text
    assert response.json()["data"]["plan_id"] == plan["plan_id"]


def test_get_unknown_plan_is_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/remediation/plans/RMP-DOES-NOT-EXIST", headers=_auth())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_plan_outside_scope_is_404(tmp_path) -> None:
    client = _client(tmp_path)
    admin_client = client
    plan = _first_plan(admin_client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}",
        headers=_auth(SCOPED_READER_TOKEN),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_preview_returns_target_operation_preconditions_effect_and_collateral(
    tmp_path,
) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth()
    )

    assert response.status_code == 200, response.text
    preview = response.json()["data"]
    assert set(preview.keys()) == {
        "target",
        "operation",
        "preconditions",
        "expected_effect",
        "collateral_impact",
        "execution_snapshot",
        "executable",
        "ineligibility_reason",
    }
    assert preview["target"]["resource_key"]
    assert isinstance(preview["preconditions"], list)
    assert "business_impact" in preview["expected_effect"]
    assert "risk_drivers" in preview["collateral_impact"]


def test_patch_preview_returns_exact_server_derived_execution_snapshot(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth()
    )

    assert response.status_code == 200, response.text
    snapshot = response.json()["data"]["execution_snapshot"]
    assert snapshot["target_id"] == VM_PAYMENTS_ID
    assert snapshot["patch_ids"] == ["KB600001", "KB600002"]
    assert snapshot["target_kind"] == "Azure VM"
    assert snapshot["operation"] == "install_patches"
    assert snapshot["action_version"] == plan["action_version"]
    assert len(snapshot["snapshot_hash"]) == 64


def test_preview_outside_scope_is_404(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview",
        headers=_auth(SCOPED_READER_TOKEN),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_approvals_returns_requirements_and_decisions(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/approvals", headers=_auth()
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["plan_id"] == plan["plan_id"]
    # Requirement rows are now satisfied/unmet-decorated (Phase 03.5, D-01)
    # rather than the raw stored requirements -- every original field is
    # preserved, plus the new boolean-backed satisfaction signal.
    assert len(body["approval_requirements"]) == len(plan["approval_requirements"])
    for original, projected in zip(
        plan["approval_requirements"], body["approval_requirements"], strict=True
    ):
        assert projected["policy_id"] == original["policy_id"]
        assert projected["role"] == original["role"]
        assert projected["stage"] == original["stage"]
        assert projected["satisfied"] is False
        assert projected["unmet_reason"] == "pending"
    assert isinstance(body["decisions"], list)


def test_business_decision_returns_plan_business_decision_verbatim(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _first_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/business-decision",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == plan["business_decision"]


def test_all_handlers_use_single_planner_resolution_helper(tmp_path) -> None:
    """All read handlers resolve the planner through one shared call site."""
    import inspect

    from api.routers import remediation as remediation_module

    source = inspect.getsource(remediation_module)
    # Every handler goes through `_planner(` (directly or via `_get_scoped_plan`),
    # never re-implementing hybrid-provider resolution inline.
    assert source.count("_require(") == 1
    assert source.count("_planner(context, scope)") >= 3


def test_remediation_router_is_mounted_in_the_running_app(tmp_path) -> None:
    """Regression test: `/api/v1/remediation/plans*` must be reachable via app.routes,
    not merely importable, and pre-existing operationsApi routes must remain present.
    """
    client = _client(tmp_path)
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    assert "/api/v1/remediation/plans" in paths
    assert "/api/v1/remediation/plans/{plan_id}" in paths
    assert "/api/v1/remediation/plans/{plan_id}/preview" in paths
    assert "/api/v1/remediation/plans/{plan_id}/approvals" in paths
    assert "/api/v1/remediation/plans/{plan_id}/business-decision" in paths

    # The web UI's existing operationsApi surface must remain untouched by this
    # additive router: none of these pre-existing routes were renamed or removed.
    assert "/api/v1/remediation-plans" in paths
    assert "/api/v1/remediation-opportunities" in paths
    assert "/api/v1/remediation/defender-cases" in paths
    assert "/api/v1/remediation-plans/{plan_id}/decisions" in paths


def test_plan_detail_and_preview_publish_server_owned_eligibility(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    detail = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}", headers=_auth()
    ).json()["data"]
    preview = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth()
    ).json()["data"]

    assert detail["executable"] is False
    assert detail["ineligibility_reason"] == "execution_unavailable"
    assert preview["executable"] is False
    assert preview["ineligibility_reason"] == "execution_unavailable"


def test_live_planner_generates_one_unique_plan_per_patch_target() -> None:
    service = _LiveVulnerabilityService()
    planner = LiveRemediationPlanner(service, repository=PlanRepository())

    result = planner.generate_plans()

    assert len(result["plans"]) == 1
    plan = result["plans"][0]
    assert plan["plan_id"].startswith("live-patch-")
    assert plan["action_id"] == "controlled-patch-recovery"
    assert plan["resource"]["id"] == LIVE_VM_PAYMENTS_ID
    assert plan["evidence_citations"]
    assert plan["business_decision"]["business_impact"]["status"] == "known"
    assert planner.repository.get(plan["plan_id"]) == plan


def test_live_planner_collapses_duplicate_asset_rows_for_same_patch_target() -> None:
    service = _LiveVulnerabilityService(duplicate_asset_rows=True)
    planner = LiveRemediationPlanner(service, repository=PlanRepository())

    result = planner.generate_plans()

    assert len(result["plans"]) == 1
    assert len({plan["plan_id"] for plan in result["plans"]}) == 1


def test_unrestricted_read_uses_live_provider_for_all_onboarded_subscriptions(tmp_path) -> None:
    """No subscription picked in the operating-context selector should still
    show live plans across every onboarded subscription, not an empty static
    snapshot."""
    service = _LiveVulnerabilityService()
    captured_subscription_ids: list[str] = []
    onboarding = SubscriptionOnboardingService(
        tmp_path / "aiops", secret_writer=FakeSecretWriter()
    )
    onboarding.add(
        connection_id="prod-core",
        name="Prod core",
        tenant_id="11111111-1111-1111-1111-111111111111",
        subscription_id=LIVE_SUBSCRIPTION_ID,
        client_id="22222222-2222-2222-2222-222222222222",
        secret_ref="keyvault://example-kv/secrets/prod-core",
    )

    def live_planner(subscription_ids: list[str]) -> LiveRemediationPlanner:
        captured_subscription_ids.extend(subscription_ids)
        return LiveRemediationPlanner(service, repository=PlanRepository())

    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(
            {READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: remediation_planner(repository=PlanRepository()),
        hybrid_remediation_provider=live_planner,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get("/api/v1/remediation/plans", headers=_auth())

    assert response.status_code == 200, response.text
    assert captured_subscription_ids == [LIVE_SUBSCRIPTION_ID]
    plans = response.json()["data"]["plans"]
    assert any(plan["action_id"] == "controlled-patch-recovery" for plan in plans)


def test_unrestricted_read_falls_back_to_snapshot_when_nothing_onboarded() -> None:
    """With no onboarded subscriptions at all, fall back to the static
    Fabric snapshot provider rather than calling the live provider with an
    empty subscription list."""
    captured_subscription_ids: list[str] = []

    def live_planner(subscription_ids: list[str]) -> LiveRemediationPlanner:
        captured_subscription_ids.extend(subscription_ids)
        return LiveRemediationPlanner(_LiveVulnerabilityService(), repository=PlanRepository())

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(FakeSecretWriter()),
        authenticator=StaticTokenAuthenticator(
            {READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: remediation_planner(repository=PlanRepository()),
        hybrid_remediation_provider=live_planner,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get("/api/v1/remediation/plans", headers=_auth())

    assert response.status_code == 200, response.text
    assert captured_subscription_ids == []
    plans = response.json()["data"]["plans"]
    assert any(plan["action_id"] == "controlled-patch-recovery" for plan in plans)


def test_unrestricted_read_projects_eligibility_from_live_execution_repository(
    tmp_path,
) -> None:
    """An all-subscriptions plan list must not lose its live plan repository."""
    service = _LiveVulnerabilityService()
    onboarding = SubscriptionOnboardingService(
        tmp_path / "aiops", secret_writer=FakeSecretWriter()
    )
    onboarding.add(
        connection_id="prod-core",
        name="Prod core",
        tenant_id="11111111-1111-1111-1111-111111111111",
        subscription_id=LIVE_SUBSCRIPTION_ID,
        client_id="22222222-2222-2222-2222-222222222222",
        secret_ref="keyvault://example-kv/secrets/prod-core",
    )

    def live_planner(subscription_ids: list[str]) -> LiveRemediationPlanner:
        return LiveRemediationPlanner(service, repository=PlanRepository())

    def execution_service(scope: Scope) -> RemediationExecutionService:
        planner = live_planner(
            [
                str(connection.subscription_id)
                for connection in onboarding.registry.list(include_disabled=False)
            ]
            if scope.is_unrestricted()
            else list(scope.values("subscription"))
        )
        planner.generate_plans()
        return RemediationExecutionService(
            plan_repository=planner.repository,
            patching_service=None,
        )

    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(
            {READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: None,
        hybrid_remediation_provider=live_planner,
        execution_provider=execution_service,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get("/api/v1/remediation/plans", headers=_auth())

    assert response.status_code == 200, response.text
    plan = response.json()["data"]["plans"][0]
    assert plan["executable"] is False
    assert plan["ineligibility_reason"] == "not_approved"


def test_unrestricted_workflow_uses_live_patching_provider_for_preview(tmp_path) -> None:
    """Review must resolve targets from the same live estate as plan listing."""
    service = _LiveVulnerabilityService()
    patching_service = _PatchingService()
    onboarding = SubscriptionOnboardingService(
        tmp_path / "aiops", secret_writer=FakeSecretWriter()
    )
    onboarding.add(
        connection_id="prod-core",
        name="Prod core",
        tenant_id="11111111-1111-1111-1111-111111111111",
        subscription_id=LIVE_SUBSCRIPTION_ID,
        client_id="22222222-2222-2222-2222-222222222222",
        secret_ref="keyvault://example-kv/secrets/prod-core",
    )

    def live_planner(subscription_ids: list[str]) -> LiveRemediationPlanner:
        return LiveRemediationPlanner(service, repository=PlanRepository())

    def execution_service(scope: Scope) -> RemediationExecutionService:
        planner = live_planner(list(scope.values("subscription")) or [LIVE_SUBSCRIPTION_ID])
        planner.generate_plans()
        return RemediationExecutionService(
            plan_repository=planner.repository,
            patching_service=patching_service,
        )

    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(
            {READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: None,
        hybrid_remediation_provider=live_planner,
        hybrid_patching_provider=lambda subscription_ids: patching_service,
        execution_provider=execution_service,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    plans = client.get("/api/v1/remediation/plans", headers=_auth()).json()["data"]["plans"]
    plan_id = plans[0]["plan_id"]

    response = client.get(
        f"/api/v1/remediation/plans/{plan_id}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["preview_error"] == ""
    assert workflow["preview"]["execution_snapshot"]["patch_ids"] == [
        "KB600001",
        "KB600002",
    ]


def test_subscription_scoped_read_uses_live_remediation_provider(tmp_path) -> None:
    service = _LiveVulnerabilityService()
    captured_subscription_ids: list[str] = []

    def live_planner(subscription_ids: list[str]) -> LiveRemediationPlanner:
        captured_subscription_ids.extend(subscription_ids)
        return LiveRemediationPlanner(service, repository=PlanRepository())

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(FakeSecretWriter()),
        authenticator=StaticTokenAuthenticator(
            {READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: remediation_planner(resources=[], repository=PlanRepository()),
        hybrid_remediation_provider=live_planner,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/remediation/plans",
        params={"subscription": LIVE_SUBSCRIPTION_ID},
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert captured_subscription_ids == [LIVE_SUBSCRIPTION_ID]
    plans = response.json()["data"]["plans"]
    assert len(plans) == 1
    assert plans[0]["resource"]["id"] == LIVE_VM_PAYMENTS_ID


def test_defender_cases_fall_back_to_live_onboarded_subscriptions(tmp_path) -> None:
    service = _LiveVulnerabilityService()
    onboarding = SubscriptionOnboardingService(
        tmp_path / "aiops",
        secret_writer=FakeSecretWriter(),
    )
    onboarding.add(
        connection_id="prod-core",
        name="Prod core",
        tenant_id="11111111-1111-1111-1111-111111111111",
        subscription_id=LIVE_SUBSCRIPTION_ID,
        client_id="22222222-2222-2222-2222-222222222222",
        secret_ref="keyvault://example-kv/secrets/prod-core",
    )

    def live_planner(subscription_ids: list[str]) -> LiveRemediationPlanner:
        assert subscription_ids == [LIVE_SUBSCRIPTION_ID]
        planner = LiveRemediationPlanner(service, repository=PlanRepository())
        return _attach_live_defender_correlator(planner, service)

    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(
            {READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: remediation_planner(repository=PlanRepository()),
        hybrid_remediation_provider=live_planner,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get("/api/v1/remediation/defender-cases", headers=_auth())

    assert response.status_code == 200, response.text
    cases = response.json()["data"]["cases"]
    assert len(cases) == 1
    assert cases[0]["resource_key"] == LIVE_VM_PAYMENTS_ID


# ---------------------------------------------------------------------------
# Phase 03.6 Plan 02: Honest Step Projection, Blocker Contract, Degradation
# Contract.
# ---------------------------------------------------------------------------


def _seed_execution(
    store: RemediationExecutionStore,
    plan_id: str,
    *,
    status: str,
    evidence_reconciliation: dict | None = None,
    ineligibility_reason: str = "",
    patch_ids: list[str] | None = None,
    snapshot_kind: str = "",
) -> dict:
    selected_patch_ids = ["KB600001"] if patch_ids is None else patch_ids
    record, _ = store.create_or_get(
        plan_id,
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments",
            "patch_ids": selected_patch_ids,
            "target_kind": "Azure VM",
            "operation": "install_patches",
            "action_version": "v1",
            "snapshot_hash": "hash-1",
            **({"snapshot_kind": snapshot_kind} if snapshot_kind else {}),
        },
    )
    running = store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        provider_job_id="https://management.azure.com/op/1",
        provider_submitted=True,
    )
    fields: dict = {}
    if evidence_reconciliation is not None:
        fields["evidence_reconciliation"] = evidence_reconciliation
    if ineligibility_reason:
        fields["ineligibility_reason"] = ineligibility_reason
    return store.transition(
        record["execution_id"],
        expected_revision=int(running["revision"]),
        expected_status="running",
        status=status,
        actor="execution-verifier",
        outcome=status,
        **fields,
    )


def test_verify_step_blocked_when_execution_failed(tmp_path) -> None:
    client, _planner, store = _client_with_execution_store(tmp_path)
    plan = _patch_recovery_plan(client)
    _seed_execution(store, plan["plan_id"], status="failed")

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    verify = next(step for step in workflow["steps"] if step["id"] == "verify")
    assert verify["status"] == "blocked"


def test_verify_step_blocked_when_succeeded_but_reconciled_incomplete(tmp_path) -> None:
    client, _planner, store = _client_with_execution_store(tmp_path)
    plan = _patch_recovery_plan(client)
    _seed_execution(
        store,
        plan["plan_id"],
        status="succeeded",
        evidence_reconciliation={
            "status": "reconciled_incomplete",
            "kbs_cleared": [],
            "kbs_remaining": ["KB600001"],
            "assessed_at": "2026-09-04T12:00:00Z",
        },
    )

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    verify = next(step for step in workflow["steps"] if step["id"] == "verify")
    assert verify["status"] == "blocked"


def test_verify_step_complete_when_succeeded_and_reconciled_clean(tmp_path) -> None:
    client, _planner, store = _client_with_execution_store(tmp_path)
    plan = _patch_recovery_plan(client)
    _seed_execution(
        store,
        plan["plan_id"],
        status="succeeded",
        evidence_reconciliation={
            "status": "reconciled_clean",
            "kbs_cleared": ["KB600001"],
            "kbs_remaining": [],
            "assessed_at": "2026-09-04T12:00:00Z",
        },
    )

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    verify = next(step for step in workflow["steps"] if step["id"] == "verify")
    assert verify["status"] == "complete"


def test_verify_step_complete_when_succeeded_with_no_reconciliation_applicable(tmp_path) -> None:
    client, _planner, store = _client_with_execution_store(tmp_path)
    plan = _patch_recovery_plan(client)
    _seed_execution(
        store,
        plan["plan_id"],
        status="succeeded",
        patch_ids=[],
        snapshot_kind="defender_configuration",
    )

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    verify = next(step for step in workflow["steps"] if step["id"] == "verify")
    assert verify["status"] == "complete"


def test_verify_step_not_complete_for_unreconciled_patch_success(tmp_path) -> None:
    client, _planner, store = _client_with_execution_store(tmp_path)
    plan = _patch_recovery_plan(client)
    _seed_execution(store, plan["plan_id"], status="succeeded")

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    verify = next(step for step in workflow["steps"] if step["id"] == "verify")
    assert verify["status"] == "current"


def test_blockers_include_preview_error_row_at_review_step(tmp_path) -> None:
    planner = remediation_planner()
    original_generate = planner.generate_plans

    def generate_defender_plan():
        result = original_generate()
        plan = next(
            row
            for row in result["plans"]
            if row["action_id"] == "controlled-patch-recovery"
        )
        plan["action_id"] = ENABLE_DEFENDER_SERVERS_P1
        planner.repository.replace_generation([plan])
        return {**result, "plans": [plan]}

    planner.generate_plans = generate_defender_plan
    client = _client(tmp_path, planner=planner)
    plan = client.get(
        "/api/v1/remediation/plans", headers=_auth()
    ).json()["data"]["plans"][0]

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["preview_error"] == "provider_unavailable"
    blocker = next(row for row in workflow["blockers"] if row["code"] == "provider_unavailable")
    assert blocker["step"] == "review"


def test_blockers_include_not_approved_row_at_approve_step(tmp_path) -> None:
    client, _planner, _store = _client_with_execution_store(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["plan"]["ineligibility_reason"] == "not_approved"
    blocker = next(row for row in workflow["blockers"] if row["code"] == "not_approved")
    assert blocker["step"] == "approve"


def test_blockers_include_action_not_executable_row_at_approve_step(tmp_path) -> None:
    client = _client(tmp_path)
    plans = client.get(
        "/api/v1/remediation/plans", headers=_auth()
    ).json()["data"]["plans"]
    plan = next(
        row for row in plans if row["action_id"] == "configuration-baseline-recovery"
    )

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["action"]["executable"] is False
    blocker = next(
        row for row in workflow["blockers"] if row["code"] == "action_not_executable"
    )
    assert blocker["step"] == "approve"


def test_blockers_include_submission_ambiguous_row_but_exclude_already_succeeded(
    tmp_path,
) -> None:
    client, _planner, store = _client_with_execution_store(tmp_path)
    plan = _patch_recovery_plan(client)
    _seed_execution(
        store,
        plan["plan_id"],
        status="failed",
        ineligibility_reason="submission_ambiguous",
    )

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    blocker = next(
        row for row in workflow["blockers"] if row["code"] == "submission_ambiguous"
    )
    assert blocker["step"] == "verify"

    client2, _planner2, store2 = _client_with_execution_store(tmp_path, planner=_planner)
    plan2 = _patch_recovery_plan(client2)
    _seed_execution(store2, plan2["plan_id"], status="succeeded")
    response2 = client2.get(
        f"/api/v1/remediation/plans/{plan2['plan_id']}/workflow", headers=_auth()
    )
    workflow2 = response2.json()["data"]
    assert not any(
        row["code"] == "already_succeeded" for row in workflow2["blockers"]
    )


def test_degradation_reflects_defender_configuration_source_family_status(tmp_path) -> None:
    planner = remediation_planner()
    original_generate = planner.generate_plans

    def generate_with_degraded_source() -> dict:
        result = original_generate()
        plan = result["plans"][0]
        business_decision = plan.setdefault("business_decision", {})
        business_decision["source_family_status"] = {
            "defender_recommendation": {
                "availability": "degraded",
                "freshness": "2026-09-01T00:00:00Z",
            }
        }
        planner.repository.replace_generation(result["plans"])
        return result

    planner.generate_plans = generate_with_degraded_source
    client = _client(tmp_path, planner=planner)
    plans = client.get("/api/v1/remediation/plans", headers=_auth()).json()["data"]["plans"]
    target_plan = plans[0]

    response = client.get(
        f"/api/v1/remediation/plans/{target_plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["degradation"] != []
    assert workflow["degradation"][0]["availability"] == "degraded"


def test_degradation_is_empty_list_when_nothing_degraded(tmp_path) -> None:
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    workflow = response.json()["data"]
    assert workflow["degradation"] == []


def test_degradation_collection_never_raises_when_provider_runtime_absent(tmp_path) -> None:
    """context.provider_runtime is absent in this file's default _client
    fixture -- plan_workflow must still return 200 with degradation present."""
    client = _client(tmp_path)
    plan = _patch_recovery_plan(client)

    response = client.get(
        f"/api/v1/remediation/plans/{plan['plan_id']}/workflow", headers=_auth()
    )

    assert response.status_code == 200, response.text
    assert "degradation" in response.json()["data"]
