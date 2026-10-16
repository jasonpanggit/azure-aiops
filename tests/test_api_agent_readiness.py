"""Read-only cached readiness never acquires or refreshes agent providers."""
from unittest.mock import Mock

import pytest
from test_api_multi_agent import TOKEN, _auth, _client

from api.auth import StaticTokenAuthenticator
from api.providers import ProviderRuntime, ProviderSpec, ProviderValue
from api.rbac import Grant, Principal
from api.scope import Scope

PATH = "/api/v1/agents/runtime-readiness"


def test_real_runtime_read_is_provider_free_and_preserves_source_times(tmp_path):
    client = _client(tmp_path)
    loader = Mock(return_value=ProviderValue(
        object(), freshness="2020-01-01T00:00:00Z", ontology_version="generation-a",
    ))
    deferred = Mock(side_effect=AssertionError("Deferred provider must not load"))
    runtime = ProviderRuntime({
        "semantic": ProviderSpec(loader=loader),
        "network": ProviderSpec(loader=deferred, scheduled=False),
        "copilot": ProviderSpec(loader=deferred, configured=False),
    })
    runtime.refresh(force=True)
    client.app.state.context.provider_runtime = runtime
    before = runtime.health(refresh=False)["providers"]
    response = client.get(PATH, headers=_auth())
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["source"] == "api.ProviderRuntime"
    assert data["report_kind"] == "cached_process_state"
    assert data["providers"]["semantic"]["state"] == "stale"
    assert data["providers"]["semantic"]["last_success_at"] == before["semantic"]["last_success_at"]
    assert data["providers"]["semantic"]["freshness"] == "2020-01-01T00:00:00Z"
    assert data["providers"]["network"]["state"] == "deferred"
    assert data["providers"]["copilot"]["state"] == "disabled"
    assert data["providers"]["network_agent"] is None
    assert "not a live Foundry, APIM or MCP probe" in response.json()["warnings"][0]
    loader.assert_called_once()
    deferred.assert_not_called()
    assert runtime.health(refresh=False)["providers"] == before


def test_readiness_projects_only_allowed_public_fields_and_fixed_provider_names(tmp_path):
    client = _client(tmp_path)
    runtime = Mock()
    runtime.health.return_value = {"providers": {
        "network_agent": {"state": "unavailable", "degraded_reason": "No published adapter", "private": "never-return-private"},
        "private_provider": {"state": "ready", "private": "never-return-private"},
    }}
    client.app.state.context.provider_runtime = runtime
    response = client.get(PATH, headers=_auth())
    assert response.status_code == 200
    assert "never-return-private" not in response.text
    assert "private_provider" not in response.json()["data"]["providers"]
    assert response.json()["data"]["providers"]["network_agent"]["state"] == "unavailable"
    runtime.health.assert_called_once_with(refresh=False)
    runtime.refresh.assert_not_called()


def test_readiness_requires_auth_before_reading_runtime(tmp_path):
    client = _client(tmp_path)
    runtime = Mock()
    client.app.state.context.provider_runtime = runtime
    assert client.get(PATH).status_code == 401
    runtime.health.assert_not_called()


def test_readiness_preserves_nine_dimension_read_scope_and_grant_narrowing(tmp_path):
    client = _client(tmp_path)
    context = client.app.state.context
    context.authenticator = StaticTokenAuthenticator({
        TOKEN: Principal(subject="reader@example.com", grants=(
            Grant("reader", Scope.from_mapping({"subscription": ["sub-prod"], "business_service": ["payroll"]})),
        )),
    })
    context.provider_runtime = ProviderRuntime({})
    params = {
        "subscription": "sub-prod", "subscription_connection": "conn-a",
        "business_service": "Payroll", "application": "API", "environment": "prod",
        "owner": "Finance", "support_team": "Ops", "region": "eastus", "criticality": "high",
    }
    response = client.get(PATH, params=params, headers=_auth())
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == Scope.from_mapping(params).to_dict()
    assert client.get(PATH, params={**params, "subscription": "foreign"}, headers=_auth()).status_code == 403


def test_missing_managed_runtime_is_explicitly_unavailable(tmp_path):
    response = _client(tmp_path).get(PATH, headers=_auth())
    assert response.status_code == 503
    assert "not configured" in response.text


@pytest.mark.parametrize("state", ["ready", "partial", "stale", "degraded", "unavailable", "loading", "disabled", "deferred"])
def test_cached_states_are_not_rewritten_as_activation_or_runtime_success(tmp_path, state):
    client = _client(tmp_path)
    runtime = Mock()
    runtime.health.return_value = {"providers": {"copilot": {"state": state, "loaded": False}}}
    client.app.state.context.provider_runtime = runtime
    response = client.get(PATH, headers=_auth())
    assert response.status_code == 200
    assert response.json()["data"]["providers"]["copilot"]["state"] == state
    assert response.json()["data"]["providers"]["copilot"]["loaded"] is False
    runtime.health.assert_called_once_with(refresh=False)


def test_runtime_observation_failure_is_not_an_empty_success(tmp_path):
    client = _client(tmp_path)
    runtime = Mock()
    runtime.health.side_effect = RuntimeError("observation failure")
    client.app.state.context.provider_runtime = runtime
    response = client.get(PATH, headers=_auth())
    assert response.status_code == 500
    assert "data" not in response.json()
    runtime.refresh.assert_not_called()
