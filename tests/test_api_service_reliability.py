"""Component authorization precedes every measurement and objective mutation."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from test_api_twin import TOKEN, _auth, _client
from test_service_reliability import END, RESOURCE, START, _aggregate

from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.scope import Scope
from intelligence.inventory.models import ResourceObservation
from intelligence.inventory.service import InventoryService, InventorySnapshot
from operations.service_reliability import ServiceObjectiveStore, authorized_components
from storage.onelake_documents import OneLakeDocumentStore

SUBSCRIPTION = RESOURCE.split("/")[2]
TAGS = {
    "business_service": "Payroll", "application": "API", "environment": "prod", "owner": "Finance",
    "support_team": "Operations", "region": "eastus", "criticality": "high",
    "subscription_connection": "conn-a",
}
SCOPE = {
    **{key: [value.casefold()] for key, value in TAGS.items()}, "subscription": [SUBSCRIPTION],
}
PARAMS = [(key, values[0]) for key, values in SCOPE.items()]


def _resource(tags=None, identity=RESOURCE):
    return ResourceObservation(
        resource_id=identity, resource_name="Payroll telemetry", resource_type="microsoft.insights/components",
        family="paas", tenant_id="tenant-a", subscription_id=SUBSCRIPTION, resource_group="apps",
        location="eastus", observed_at=END, ingestion_run_id="run-a", source_type="arg",
        source_table="Resources", provider_payload={"private": "unreturned-provider-marker"}, tags=TAGS if tags is None else tags,
    )


def _source(*rows):
    return InventoryService(InventorySnapshot(
        observations=(), source_status=(), resource_observations=rows or (_resource(),),
        observed_at=END, generation_id="generation-a",
    ))


def _http(tmp_path):
    client = _client(tmp_path)
    context = client.app.state.context
    context.authenticator = StaticTokenAuthenticator({
        TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        TOKEN + "-reader": Principal(subject="reader@example.com", grants=(Grant("reader"),)),
    })
    context.inventory_provider = lambda: _source()
    context.service_objective_store = ServiceObjectiveStore(OneLakeDocumentStore(tmp_path / "objectives"))
    context.service_request_metrics = Mock(return_value={
        "resource_id": RESOURCE, "window_started_at": START, "window_finished_at": END,
        "aggregate": _aggregate().model_dump(),
    })
    return client


def _save(client, revision=0, **updates):
    return client.put("/api/v1/service-reliability/objectives", headers=_auth(), params=PARAMS, json={
        "resource_id": RESOURCE, "expected_revision": revision,
        "success_target_basis_points": 9950, "window_hours": 24, **updates,
    })


def test_components_require_complete_nine_dimension_metadata_and_native_subscription():
    assert authorized_components([_resource()], Scope.from_mapping(SCOPE))[0]["resource_id"] == RESOURCE
    for key in TAGS:
        missing = {name: value for name, value in TAGS.items() if name != key}
        assert authorized_components([_resource(tags=missing)], Scope.from_mapping(SCOPE)) == []
    forged = {**TAGS, "subscription": "foreign"}
    assert authorized_components([_resource(tags=forged)], Scope.from_mapping(SCOPE))[0]["subscription_id"] == SUBSCRIPTION
    with pytest.raises(RuntimeError, match="ambiguous"):
        authorized_components([_resource(), _resource()], Scope.unrestricted())
    assert authorized_components([_resource(tags={})], Scope.unrestricted())[0]["business_service"] == ""
    with pytest.raises(RuntimeError, match="subscription"):
        authorized_components([_resource(identity=RESOURCE.replace(SUBSCRIPTION, "22222222-2222-2222-2222-222222222222"))], Scope.unrestricted())
    with pytest.raises(RuntimeError, match="identity"):
        authorized_components([_resource(identity="https://foreign.example/query")], Scope.unrestricted())


def test_http_explicit_admin_objective_and_reader_measurement_use_authorized_source(tmp_path):
    client = _http(tmp_path)
    context = client.app.state.context
    response = client.get("/api/v1/service-reliability/components", headers=_auth(), params=PARAMS)
    assert response.status_code == 200, response.text
    assert response.json()["pagination"]["total"] == 1
    assert response.json()["data"]["components"][0]["business_service"] == "payroll"
    assert "unreturned-provider-marker" not in response.text
    assert "tags" not in response.json()["data"]["components"][0]
    assert client.get("/api/v1/service-reliability/objectives", headers=_auth(), params=PARAMS).json()["data"]["objectives"] == []
    context.service_request_metrics.assert_not_called()
    saved = _save(client)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["updated_by"] == "admin@example.com"
    reader = {"Authorization": f"Bearer {TOKEN}-reader"}
    result = client.get("/api/v1/service-reliability/metrics", headers=reader, params=[*PARAMS, ("resource_id", RESOURCE)])
    assert result.status_code == 200, result.text
    assert result.json()["data"]["objective_policy_revision"] == 1
    assert result.json()["data"]["request_success_percent"] == 98.0
    assert result.json()["data"]["remaining_failed_request_budget"] == -1.5
    context.service_request_metrics.assert_called_once_with(RESOURCE, 24, "conn-a")
    assert client.get("/api/v1/service-reliability/objectives", headers=reader, params=PARAMS).json()["data"]["revision"] == 1
    assert client.put("/api/v1/service-reliability/objectives", headers=reader, params=PARAMS, json={
        "resource_id": RESOURCE, "expected_revision": 1, "success_target_basis_points": 9990, "window_hours": 24,
    }).status_code == 403


def test_policy_recovery_and_deletion_do_not_acquire_inventory_or_metrics(tmp_path):
    client = _http(tmp_path)
    assert _save(client).status_code == 200
    context = client.app.state.context
    context.inventory_provider = Mock(side_effect=AssertionError("Policy reads must be provider-free"))
    assert client.get("/api/v1/service-reliability/objectives", headers=_auth(), params=PARAMS).json()["data"]["revision"] == 1
    deleted = client.post("/api/v1/service-reliability/objectives/remove", headers=_auth(), params=PARAMS, json={
        "expected_revision": 1, "resource_id": RESOURCE,
    })
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["objectives"] == []
    context.inventory_provider.assert_not_called()
    context.service_request_metrics.assert_not_called()


@pytest.mark.parametrize("failure,expected", [
    ("no_objective", 404), ("foreign_component", 404), ("mapping_drift", 404),
    ("malformed_measurement", 503), ("foreign_measurement", 503), ("unavailable", 503),
])
def test_unconfirmed_measurements_never_return_success_or_implicitly_rewrite_targets(tmp_path, failure, expected):
    client = _http(tmp_path)
    context = client.app.state.context
    if failure != "no_objective":
        assert _save(client).status_code == 200
    resource_id = RESOURCE
    if failure == "foreign_component":
        resource_id += "-foreign"
    elif failure == "mapping_drift":
        context.inventory_provider = lambda: _source(_resource(tags={**TAGS, "business_service": "Other"}))
    elif failure == "malformed_measurement":
        context.service_request_metrics.return_value = {"aggregate": {}}
    elif failure == "foreign_measurement":
        context.service_request_metrics.return_value["resource_id"] += "-foreign"
    elif failure == "unavailable":
        context.service_request_metrics.side_effect = RuntimeError("private telemetry marker")
    response = client.get("/api/v1/service-reliability/metrics", headers=_auth(), params=[*PARAMS, ("resource_id", resource_id)])
    assert response.status_code == expected, response.text
    assert "private telemetry marker" not in response.text
    if expected == 404:
        context.service_request_metrics.assert_not_called()
    assert context.service_objective_store.read(Scope.from_mapping(SCOPE).to_dict())["revision"] == (0 if failure == "no_objective" else 1)


def test_mapping_drift_in_unrestricted_policy_requires_explicit_replacement(tmp_path):
    client = _http(tmp_path)
    context = client.app.state.context
    scoped = context.service_objective_store.read(Scope.from_mapping(SCOPE).to_dict())
    assert scoped["revision"] == 0
    response = client.put("/api/v1/service-reliability/objectives", headers=_auth(), json={
        "expected_revision": 0, "resource_id": RESOURCE, "success_target_basis_points": 9950, "window_hours": 24,
    })
    assert response.status_code == 200
    context.inventory_provider = lambda: _source(_resource(tags={**TAGS, "business_service": "Other"}))
    assert client.get("/api/v1/service-reliability/metrics", headers=_auth(), params={"resource_id": RESOURCE}).status_code == 409
    context.service_request_metrics.assert_not_called()


def test_scope_grants_conflicts_and_unknown_component_are_checked_before_measurement(tmp_path):
    client = _http(tmp_path)
    assert _save(client).status_code == 200
    assert _save(client).status_code == 409
    assert _save(client, 1, resource_id=RESOURCE + "-missing").status_code == 404
    context = client.app.state.context
    context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="reader", grants=(
        Grant("reader", Scope.from_mapping({"subscription": ["foreign"]})),
    ))})
    assert client.get("/api/v1/service-reliability/metrics", headers=_auth(), params=[*PARAMS, ("resource_id", RESOURCE)]).status_code == 403
    context.service_request_metrics.assert_not_called()


@pytest.mark.parametrize("failure", [KeyError, ValueError, TypeError])
def test_malformed_inventory_is_unavailable_not_absent_or_client_error(tmp_path, failure):
    client = _http(tmp_path)
    assert _save(client).status_code == 200
    context = client.app.state.context
    context.inventory_provider = Mock(side_effect=failure("private source marker"))
    for path, params in (("components", PARAMS), ("metrics", [*PARAMS, ("resource_id", RESOURCE)])):
        response = client.get(f"/api/v1/service-reliability/{path}", headers=_auth(), params=params)
        assert response.status_code == 503
        assert "private source marker" not in response.text
    context.service_request_metrics.assert_not_called()
    assert client.get("/api/v1/service-reliability/objectives", headers=_auth(), params=PARAMS).status_code == 200
    assert client.post("/api/v1/service-reliability/objectives/remove", headers=_auth(), params=PARAMS, json={
        "expected_revision": 1, "resource_id": RESOURCE + "-absent",
    }).status_code == 404


def test_runtime_connection_choice_is_unambiguous_and_uses_current_factory(tmp_path, monkeypatch):
    from api.runtime import _service_objective_store, _service_request_metrics

    connections = [
        SimpleNamespace(subscription_id=SUBSCRIPTION, connection_id="conn-a"),
        SimpleNamespace(subscription_id=SUBSCRIPTION, connection_id="conn-b"),
    ]
    onboarding = SimpleNamespace(registry=SimpleNamespace(list=Mock(return_value=connections)), resolver=object())
    config = object()
    with patch("api.runtime.build_connection_logs_client") as factory:
        with pytest.raises(RuntimeError, match="unambiguous"):
            _service_request_metrics(onboarding, config, RESOURCE, 24, "")
        with pytest.raises(RuntimeError, match="unambiguous"):
            _service_request_metrics(onboarding, config, RESOURCE, 24, "foreign")
        factory.assert_not_called()
        _service_request_metrics(onboarding, config, RESOURCE, 24, "conn-b")
        factory.assert_called_once_with(config, connections[1], onboarding.resolver)
        factory.return_value.query_request_telemetry.assert_called_once_with(RESOURCE, 24)
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path))
    assert _service_objective_store().read({})["objectives"] == []


def test_partial_admin_grant_never_authorizes_broader_shared_objective_writes(tmp_path):
    client = _http(tmp_path)
    context = client.app.state.context
    context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="mixed", grants=(
        Grant("reader"), Grant("admin", Scope.from_mapping({"subscription": ["foreign"]})),
    ))})
    assert _save(client).status_code == 403
    assert client.post("/api/v1/service-reliability/objectives/remove", headers=_auth(), params=PARAMS, json={
        "expected_revision": 0, "resource_id": RESOURCE,
    }).status_code == 403
    context.service_request_metrics.assert_not_called()
