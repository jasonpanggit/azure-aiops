"""HTTP-level tests for the resource-health route.

Drives the real app factory with a fake hybrid provider so the envelope,
scope-enforcement and "requires an explicit subscription scope" contract are
validated end to end, without touching real Azure.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.health.service import ResourceHealthService
from onboarding.service import SubscriptionOnboardingService

ADMIN_TOKEN = "admin-token-0123456789abcdef"
SCOPED_TOKEN = "scoped-token-0123456789abcdef"
PROD_SUB = "prod-sub-1"


def _principals() -> dict[str, Principal]:
    return {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        SCOPED_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("reader", Scope.from_mapping({"subscription": [PROD_SUB]})),),
        ),
    }


def _vm_row(name: str) -> dict:
    return {
        "id": f"/subscriptions/{PROD_SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/{name}",
        "name": name,
        "type": "microsoft.compute/virtualmachines",
        "subscriptionId": PROD_SUB,
        "resourceGroup": "rg",
    }


class _FakeMetricsClient:
    def query_resource_metrics(self, resource_id: str) -> dict:
        return {"Percentage CPU": {"value": 95.0, "unit": "Percent", "timestamp": "t"}}


def _connection():
    from types import SimpleNamespace

    return SimpleNamespace(connection_id="conn-1", subscription_id=PROD_SUB, is_active=True)


def _client(tmp_path, *, with_provider: bool = True) -> TestClient:
    def hybrid_resource_health(subscription_ids: list[str]) -> ResourceHealthService:
        return ResourceHealthService(
            connections=lambda: [_connection()],
            resource_lister=lambda _conn: [_vm_row("vm-1")],
            metrics_client_factory=lambda _conn: _FakeMetricsClient(),
        )

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        hybrid_resource_health_provider=(
            hybrid_resource_health if with_provider else None
        ),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path) -> TestClient:
    return _client(tmp_path)


def _auth(token: str = SCOPED_TOKEN) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_returns_live_utilization_for_scoped_resources(client):
    response = client.get("/api/v1/resource-health", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    resources = body["data"]["resources"]
    assert len(resources) == 1
    assert resources[0]["resource_name"] == "vm-1"
    assert resources[0]["cpu_percent"] == 95.0
    assert resources[0]["status"] == "critical"
    assert body["data"]["unavailable_metrics"] == ["memory_percent", "disk_free_percent"]


def test_carries_evidence_naming_the_engine(client):
    body = client.get("/api/v1/resource-health", headers=_auth()).json()
    evidence = body["evidence"][0]
    assert evidence["source_engine"] == "intelligence.health.ResourceHealthService"
    assert evidence["timestamp"]


def test_admin_without_subscription_scope_gets_unavailable_error(client):
    response = client.get("/api/v1/resource-health", headers=_auth(ADMIN_TOKEN))

    assert response.status_code >= 400
    body = response.json()
    assert body["error"]["details"]["capability"] == "resource_health"


def test_missing_provider_reports_unavailable(tmp_path):
    client = _client(tmp_path, with_provider=False)

    response = client.get("/api/v1/resource-health", headers=_auth())

    assert response.status_code >= 400
    body = response.json()
    assert body["error"]["details"]["capability"] == "resource_health"
