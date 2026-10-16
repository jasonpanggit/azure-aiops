"""Authorized search exploration and non-hydrating readiness contracts."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.providers import ProviderRuntime, ProviderSpec
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

TOKEN = "search-exploration-token-0123456789"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def client_for(tmp_path, *, restricted=False, runtime=None, truncated=False):
    rows = [
        {"id": str(i), "name": f"vm-{i}", "entity_type": "VirtualMachine",
         "subscription_id": "sub-a", "source": "ARG"}
        for i in range(31)
    ] + [
        {"id": "service", "entity_type": "BusinessService", "subscription_id": "sub-a", "source": "ontology"},
        {"id": "private", "entity_type": "SecretType", "subscription_id": "sub-b", "source": "PrivateSource"},
    ]
    provider = SimpleNamespace(search=Mock(return_value={
        "intent": "test", "results": rows, "count": len(rows), "truncated": truncated,
    }))
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator({TOKEN: Principal(
            subject="reader@example.com",
            grants=(Grant("reader", Scope.from_mapping({"subscription": ["sub-a"]}) if restricted else Scope()),),
        )}),
        authorizer=Authorizer(), telemetry=ApiTelemetry(),
        semantic_provider=lambda: provider, provider_runtime=runtime,
    )
    return TestClient(create_app(context), raise_server_exceptions=False), provider


def test_search_facets_and_paging_are_computed_after_authorization(tmp_path):
    client, _ = client_for(tmp_path, restricted=True)
    response = client.get("/api/v1/search", params={"q": "test", "limit": 25}, headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]["results"]) == 25
    assert body["pagination"] == {"offset": 0, "limit": 25, "total": 32, "next_offset": 25}
    assert body["data"]["facets"]["entity_type"] == {"BusinessService": 1, "VirtualMachine": 31}
    assert "PrivateSource" not in response.text
    assert "SecretType" not in response.text
    assert body["data"]["represented_count"] == 32


def test_search_facets_filter_the_complete_represented_set_not_one_page(tmp_path):
    client, _ = client_for(tmp_path, restricted=True)
    response = client.get("/api/v1/search", params={
        "q": "test", "limit": 25, "offset": 25, "entity_type": "VirtualMachine", "source": "ARG",
    }, headers=HEADERS)
    body = response.json()
    assert response.status_code == 200, response.text
    assert len(body["data"]["results"]) == 6
    assert body["pagination"]["total"] == 31
    assert body["pagination"]["next_offset"] is None
    assert body["data"]["facets"]["entity_type"]["BusinessService"] == 1


def test_search_preserves_legacy_shape_and_truncation_boundary(tmp_path):
    client, _ = client_for(tmp_path, truncated=True)
    legacy = client.get("/api/v1/search?q=test", headers=HEADERS).json()
    assert len(legacy["data"]["results"]) == 33
    assert "pagination" not in legacy
    paged = client.get("/api/v1/search?q=test&limit=25", headers=HEADERS).json()
    assert paged["data"]["truncated"] is True
    assert paged["data"]["aggregate_basis"] == "authorized_provider_results"


@pytest.mark.parametrize("query", ["limit=101", "limit=0", "offset=-1", "offset=100001", "entity_type=" + "a" * 129])
def test_search_rejects_invalid_exploration_bounds(tmp_path, query):
    client, provider = client_for(tmp_path)
    assert client.get("/api/v1/search?q=test&" + query, headers=HEADERS).status_code == 400
    provider.search.assert_not_called()


def test_search_capabilities_does_not_load_deferred_semantics(tmp_path):
    loader = Mock(side_effect=AssertionError("Must not hydrate"))
    runtime = ProviderRuntime(specs={"semantic": ProviderSpec(loader=loader, scheduled=False)})
    client, _ = client_for(tmp_path, runtime=runtime)
    response = client.get("/api/v1/search/capabilities", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["semantic"]["can_query"] is False
    assert response.json()["data"]["live"]["can_query"] is False
    loader.assert_not_called()


def test_search_capabilities_is_authenticated(tmp_path):
    client, _ = client_for(tmp_path)
    assert client.get("/api/v1/search/capabilities").status_code == 401


def test_filter_without_limit_still_has_bounded_pagination(tmp_path):
    client, _ = client_for(tmp_path, restricted=True)
    result = client.get("/api/v1/search?q=test&entity_type=VirtualMachine", headers=HEADERS)
    assert result.status_code == 200, result.text
    assert len(result.json()["data"]["results"]) == 25
    assert result.json()["pagination"] == {"offset": 0, "limit": 25, "total": 31, "next_offset": 25}
