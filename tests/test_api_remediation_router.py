from __future__ import annotations

from fastapi.testclient import TestClient
from remediation_scenario import remediation_planner

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.runtime import _attach_live_defender_correlator
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.service import SubscriptionOnboardingService
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
    assert body["approval_requirements"] == plan["approval_requirements"]
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


def test_unrestricted_read_uses_snapshot_provider_without_explicit_subscription(tmp_path) -> None:
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
    assert captured_subscription_ids == []
    plans = response.json()["data"]["plans"]
    assert any(plan["action_id"] == "controlled-patch-recovery" for plan in plans)


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
