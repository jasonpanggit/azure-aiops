from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.patching.models import AvailablePatch, PatchTarget
from tests.test_api_http import FakeSecretWriter

from remediation_scenario import remediation_planner

ADMIN_TOKEN = "admin-token-0123456789abcdef"
OPERATOR_TOKEN = "operator-token-0123456789abcd"
READER_TOKEN = "reader-token-0123456789abcdef"
SCOPED_READER_TOKEN = "scoped-reader-token-012345678"
VM_PAYMENTS_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-prod/providers/"
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
