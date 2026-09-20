"""HTTP-level tests for the resource-health route.

Drives the real app factory with a fake hybrid provider so the envelope,
scope-enforcement and "requires an explicit subscription scope" contract are
validated end to end, without touching real Azure.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.routers import resource_health as resource_health_router
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
    return SimpleNamespace(
        connection_id="conn-1",
        tenant_id="tenant-1",
        subscription_id=PROD_SUB,
        credential=SimpleNamespace(
            credential_id="credential-1",
            kind="service_principal",
            tenant_id="tenant-1",
            client_id="client-1",
            secret_ref="keyvault://vault/secrets/conn-1/v1",
        ),
        is_active=True,
    )


def _client(tmp_path, *, with_provider: bool = True, call_counter: list[int] | None = None) -> TestClient:
    def hybrid_resource_health(subscription_ids: list[str]) -> ResourceHealthService:
        if call_counter is not None:
            call_counter.append(1)
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


@pytest.fixture(autouse=True)
def _clear_resource_health_cache():
    resource_health_router._resource_health_cache.clear()
    yield
    resource_health_router._resource_health_cache.clear()


@pytest.fixture
def client(tmp_path) -> TestClient:
    return _client(tmp_path)


def _auth(token: str = SCOPED_TOKEN) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


class _FakeInventoryReadPort:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    def get_resource(self, scope, resource_id: str) -> dict | None:
        self.calls.append(resource_id)
        for row in self.rows:
            if (
                str(row["resource_id"]).casefold() == resource_id.casefold()
                and scope.matches({"subscription": row["subscription_id"]})
            ):
                return dict(row)
        return None


def _inventory_row(
    name: str = "vm-1",
    *,
    resource_id: str | None = None,
    resource_type: str = "microsoft.compute/virtualmachines",
    subscription_id: str = PROD_SUB,
) -> dict:
    return {
        "resource_id": resource_id
        or (
            f"/subscriptions/{subscription_id}/resourceGroups/Rg/providers/"
            f"Microsoft.Compute/virtualMachines/{name}"
        ),
        "resource_name": name,
        "resource_type": resource_type,
        "subscription_id": subscription_id,
        "resource_group": "Rg",
    }


def _resource_client(tmp_path, rows: list[dict]):
    inventory = _FakeInventoryReadPort(rows)
    provider_calls: list[tuple[str, ...]] = []
    metrics_calls: list[str] = []
    lister_calls: list[str] = []

    class _CaptureMetricsClient:
        def query_resource_metrics(self, resource_id: str) -> dict:
            metrics_calls.append(resource_id)
            return {"Percentage CPU": {"value": 95.0}}

    def provider(subscription_ids: list[str]) -> ResourceHealthService:
        provider_calls.append(tuple(subscription_ids))
        return ResourceHealthService(
            connections=lambda: [_connection()],
            resource_lister=lambda _conn: lister_calls.append("listed") or [],
            metrics_client_factory=lambda _conn: _CaptureMetricsClient(),
        )

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "resource-aiops"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        hybrid_resource_health_provider=provider,
        inventory_read_port_provider=lambda: inventory,
    )
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        inventory,
        provider_calls,
        metrics_calls,
        lister_calls,
    )


def test_resource_endpoint_normalizes_authorized_inventory_identity(tmp_path):
    canonical_id = (
        "/subscriptions/prod-sub-1/resourceGroups/Rg/providers/"
        "Microsoft.Compute/virtualMachines/MixedCaseVm"
    )
    client, inventory, provider_calls, metrics_calls, lister_calls = _resource_client(
        tmp_path, [_inventory_row("MixedCaseVm", resource_id=canonical_id)]
    )

    response = client.get(
        "/api/v1/resource-health/resource",
        params={"resource_id": canonical_id.swapcase()},
        headers=_auth(),
    )

    assert response.status_code == 200
    body = response.json()
    assert inventory.calls == [canonical_id.swapcase()]
    assert provider_calls == [(PROD_SUB,)]
    assert metrics_calls == [canonical_id]
    assert lister_calls == []
    assert body["data"]["resources"][0]["resource_id"] == canonical_id
    assert body["data"]["resources"][0]["resource_group"] == "Rg"
    assert body["scope"] == {"subscription": [PROD_SUB]}


@pytest.mark.parametrize(
    "row",
    [
        None,
        _inventory_row(subscription_id="other-sub"),
        _inventory_row(resource_type="microsoft.network/virtualnetworks"),
    ],
)
def test_resource_endpoint_returns_same_not_found_before_provider_access(tmp_path, row):
    rows = [] if row is None else [row]
    client, _inventory, provider_calls, metrics_calls, _lister_calls = _resource_client(
        tmp_path, rows
    )
    requested_id = (
        _inventory_row()["resource_id"] if row is None else row["resource_id"]
    )

    response = client.get(
        "/api/v1/resource-health/resource",
        params={"resource_id": requested_id},
        headers=_auth(),
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Resource health was not found",
    }
    assert provider_calls == []
    assert metrics_calls == []


def test_resource_endpoint_missing_matching_connection_is_not_found(tmp_path):
    row = _inventory_row()
    inventory = _FakeInventoryReadPort([row])
    provider_calls: list[tuple[str, ...]] = []

    def provider(subscription_ids: list[str]) -> ResourceHealthService:
        provider_calls.append(tuple(subscription_ids))
        return ResourceHealthService(
            connections=lambda: [],
            resource_lister=lambda _conn: pytest.fail("must not list resources"),
            metrics_client_factory=lambda _conn: pytest.fail("must not build metrics"),
        )

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "missing-connection"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        hybrid_resource_health_provider=provider,
        inventory_read_port_provider=lambda: inventory,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/resource-health/resource",
        params={"resource_id": row["resource_id"]},
        headers=_auth(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Resource health was not found"
    assert provider_calls == [(PROD_SUB,)]


def test_resource_endpoint_cache_isolated_by_resource_and_force_refresh(tmp_path):
    first = _inventory_row("vm-1")
    second = _inventory_row("vm-2")
    client, _inventory, provider_calls, metrics_calls, _lister_calls = _resource_client(
        tmp_path, [first, second]
    )

    first_response = client.get(
        "/api/v1/resource-health/resource",
        params={"resource_id": first["resource_id"]},
        headers=_auth(),
    )
    cached_response = client.get(
        "/api/v1/resource-health/resource",
        params={"resource_id": first["resource_id"].swapcase()},
        headers=_auth(),
    )
    second_response = client.get(
        "/api/v1/resource-health/resource",
        params={"resource_id": second["resource_id"]},
        headers=_auth(),
    )
    refreshed_response = client.get(
        "/api/v1/resource-health/resource",
        params={"resource_id": first["resource_id"], "force_refresh": "true"},
        headers=_auth(),
    )

    assert [
        response.status_code
        for response in (
            first_response,
            cached_response,
            second_response,
            refreshed_response,
        )
    ] == [200, 200, 200, 200]
    assert first_response.json()["data"]["cached"] is False
    assert cached_response.json()["data"]["cached"] is True
    assert second_response.json()["data"]["cached"] is False
    assert refreshed_response.json()["data"]["cached"] is False
    assert provider_calls == [(PROD_SUB,), (PROD_SUB,), (PROD_SUB,)]
    assert metrics_calls == [
        first["resource_id"],
        second["resource_id"],
        first["resource_id"],
    ]


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


def test_connection_scoped_page_read_resolves_its_subscription(tmp_path):
    captured: list[list[str]] = []
    onboarding = SubscriptionOnboardingService(tmp_path / "aiops")
    onboarding.registry.list = (  # type: ignore[method-assign]
        lambda *, include_disabled=False: [_connection()]
    )

    def hybrid_resource_health(subscription_ids: list[str]) -> ResourceHealthService:
        captured.append(subscription_ids)
        return ResourceHealthService(
            connections=lambda: [_connection()],
            resource_lister=lambda _conn: [_vm_row("vm-1")],
            metrics_client_factory=lambda _conn: _FakeMetricsClient(),
        )

    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        hybrid_resource_health_provider=hybrid_resource_health,
    )
    scoped_client = TestClient(create_app(context), raise_server_exceptions=False)

    response = scoped_client.get(
        "/api/v1/resource-health?subscription_connection=conn-1",
        headers=_auth(),
    )

    assert response.status_code == 200
    assert captured == [[PROD_SUB]]


def test_carries_evidence_naming_the_engine(client):
    body = client.get("/api/v1/resource-health", headers=_auth()).json()
    evidence = body["evidence"][0]
    assert evidence["source_engine"] == "intelligence.health.ResourceHealthService"
    assert evidence["timestamp"]


def test_admin_without_subscription_scope_and_no_onboarded_subscriptions_gets_unavailable_error(client):
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


def test_admin_without_subscription_scope_defaults_to_all_onboarded_subscriptions(tmp_path):
    """No filter selected (unrestricted scope) means "all onboarded
    subscriptions" for resource health too, matching every other page --
    it should not require the caller to pick one explicitly."""
    onboarding = SubscriptionOnboardingService(tmp_path / "aiops-2")
    onboarding.registry.list = lambda *, include_disabled=False: [_connection()]  # type: ignore[method-assign]

    def hybrid_resource_health(subscription_ids: list[str]) -> ResourceHealthService:
        assert subscription_ids == [PROD_SUB]
        return ResourceHealthService(
            connections=lambda: [_connection()],
            resource_lister=lambda _conn: [_vm_row("vm-1")],
            metrics_client_factory=lambda _conn: _FakeMetricsClient(),
        )

    scoped_context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        hybrid_resource_health_provider=hybrid_resource_health,
    )
    scoped_client = TestClient(create_app(scoped_context), raise_server_exceptions=False)

    response = scoped_client.get("/api/v1/resource-health", headers=_auth(ADMIN_TOKEN))

    assert response.status_code == 200
    resources = response.json()["data"]["resources"]
    assert len(resources) == 1
    assert resources[0]["resource_name"] == "vm-1"


def test_second_request_within_ttl_is_served_from_cache(tmp_path):
    calls: list[int] = []
    client = _client(tmp_path, call_counter=calls)

    first = client.get("/api/v1/resource-health", headers=_auth())
    second = client.get("/api/v1/resource-health", headers=_auth())

    assert first.status_code == second.status_code == 200
    assert len(calls) == 1
    assert first.json()["data"]["cached"] is False
    assert second.json()["data"]["cached"] is True


def test_force_refresh_bypasses_the_cache(tmp_path):
    calls: list[int] = []
    client = _client(tmp_path, call_counter=calls)

    client.get("/api/v1/resource-health", headers=_auth())
    refreshed = client.get(
        "/api/v1/resource-health?force_refresh=true", headers=_auth()
    )

    assert refreshed.status_code == 200
    assert len(calls) == 2
    assert refreshed.json()["data"]["cached"] is False


def test_expired_cache_entry_triggers_a_live_refresh(tmp_path, monkeypatch):
    calls: list[int] = []
    client = _client(tmp_path, call_counter=calls)

    fake_time = [1000.0]
    monkeypatch.setattr(resource_health_router.time, "monotonic", lambda: fake_time[0])

    client.get("/api/v1/resource-health", headers=_auth())
    fake_time[0] += resource_health_router._RESOURCE_HEALTH_CACHE_TTL_SECONDS + 1
    expired = client.get("/api/v1/resource-health", headers=_auth())

    assert len(calls) == 2
    assert expired.json()["data"]["cached"] is False


def test_different_subscription_scopes_do_not_share_a_cache_entry(tmp_path):
    other_token = "other-token-0123456789abcdef"
    principals = _principals()
    principals[other_token] = Principal(
        subject="other@example.com",
        grants=(Grant("reader", Scope.from_mapping({"subscription": ["other-sub"]})),),
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        hybrid_resource_health_provider=(
            lambda subscription_ids: ResourceHealthService(
                connections=lambda: [_connection()],
                resource_lister=lambda _conn: [_vm_row("vm-1")],
                metrics_client_factory=lambda _conn: _FakeMetricsClient(),
            )
        ),
    )
    scoped_client = TestClient(create_app(context), raise_server_exceptions=False)

    scoped_client.get("/api/v1/resource-health", headers=_auth())
    scoped_client.get("/api/v1/resource-health", headers=_auth(other_token))

    assert (
        len(resource_health_router._resource_health_cache) == 2
    ), "each distinct subscription scope should get its own cache entry"


def test_replaced_connection_identity_does_not_reuse_cached_subscription_data(
    tmp_path,
) -> None:
    calls: list[str] = []
    current_connection = [
        SimpleNamespace(
            connection_id="conn-a",
            tenant_id="tenant-a",
            subscription_id=PROD_SUB,
            credential=SimpleNamespace(
                credential_id="credential-a",
                kind="service_principal",
                tenant_id="tenant-a",
                client_id="client-a",
                secret_ref="keyvault://vault/secrets/conn-a/v1",
            ),
            is_active=True,
        )
    ]
    onboarding = SubscriptionOnboardingService(tmp_path / "aiops")
    onboarding.registry.list = (  # type: ignore[method-assign]
        lambda *, include_disabled=False: list(current_connection)
    )

    def hybrid_resource_health(subscription_ids: list[str]) -> ResourceHealthService:
        calls.append(current_connection[0].connection_id)
        return ResourceHealthService(
            connections=lambda: list(current_connection),
            resource_lister=lambda _conn: [_vm_row("vm-1")],
            metrics_client_factory=lambda _conn: _FakeMetricsClient(),
        )

    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        hybrid_resource_health_provider=hybrid_resource_health,
    )
    scoped_client = TestClient(create_app(context), raise_server_exceptions=False)

    first = scoped_client.get("/api/v1/resource-health", headers=_auth())
    current_connection[0] = SimpleNamespace(
        connection_id="conn-b",
        tenant_id="tenant-b",
        subscription_id=PROD_SUB,
        credential=SimpleNamespace(
            credential_id="credential-b",
            kind="service_principal",
            tenant_id="tenant-b",
            client_id="client-b",
            secret_ref="keyvault://vault/secrets/conn-b/v1",
        ),
        is_active=True,
    )
    second = scoped_client.get("/api/v1/resource-health", headers=_auth())

    assert first.status_code == second.status_code == 200
    assert calls == ["conn-a", "conn-b"]
    assert len(resource_health_router._resource_health_cache) == 2
