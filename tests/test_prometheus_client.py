from __future__ import annotations

import httpx
import pytest

from onboarding.monitor_prometheus import (
    DISK_FREE_PERCENT_QUERY,
    MEMORY_PERCENT_QUERY,
    PROMETHEUS_QUERY_SCOPE,
    AzureMonitorPrometheusClient,
    resource_scoped_endpoint,
    workspace_scoped_endpoint,
)


class Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str):
        self.scopes.append(scope)
        return type("Token", (), {"token": "prom-token"})()


def _vector_response(resource_id: str, value: float) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"microsoft_resourceid": resource_id, "state": "free"},
                    "value": [1700000000, str(value)],
                }
            ],
        },
    }


def test_resource_scoped_endpoint_builds_regional_url_and_scoping_header() -> None:
    endpoint = resource_scoped_endpoint("EastUS", "/subscriptions/sub-1")
    assert endpoint.query_url == "https://query.eastus.prometheus.monitor.azure.com/api/v1/query"
    assert endpoint.scoping_id == "/subscriptions/sub-1"


def test_resource_scoped_endpoint_rejects_invalid_region() -> None:
    with pytest.raises(ValueError):
        resource_scoped_endpoint("east us!", "/subscriptions/sub-1")


def test_workspace_scoped_endpoint_appends_query_path() -> None:
    endpoint = workspace_scoped_endpoint("https://amw-1.eastus.prometheus.monitor.azure.com")
    assert endpoint.query_url == "https://amw-1.eastus.prometheus.monitor.azure.com/api/v1/query"
    assert endpoint.scoping_id == ""


def test_query_guest_performance_merges_memory_and_disk_by_resource() -> None:
    resource_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
    calls: list[dict] = []

    def requester(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        query = kwargs["params"]["query"]
        if query == MEMORY_PERCENT_QUERY:
            return httpx.Response(200, json=_vector_response(resource_id, 42.5))
        if query == DISK_FREE_PERCENT_QUERY:
            return httpx.Response(200, json=_vector_response(resource_id, 88.0))
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}})

    credential = Credential()
    endpoint = resource_scoped_endpoint("eastus", "/subscriptions/sub-1")
    client = AzureMonitorPrometheusClient(credential, requester=requester)

    result = client.query_guest_performance(endpoint)

    assert result == {
        resource_id.casefold(): {"memory_percent": 42.5, "disk_free_percent": 88.0}
    }
    assert credential.scopes == [PROMETHEUS_QUERY_SCOPE, PROMETHEUS_QUERY_SCOPE]
    for call in calls:
        assert call["method"] == "GET"
        assert call["url"] == endpoint.query_url
        assert call["headers"]["x-ms-azure-scoping"] == "/subscriptions/sub-1"


def test_query_guest_performance_returns_empty_dict_on_empty_vector() -> None:
    def requester(method, url, **kwargs):
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}})

    client = AzureMonitorPrometheusClient(Credential(), requester=requester)
    endpoint = resource_scoped_endpoint("eastus", "/subscriptions/sub-1")

    assert client.query_guest_performance(endpoint) == {}


def test_query_guest_performance_raises_on_http_error() -> None:
    def requester(method, url, **kwargs):
        return httpx.Response(403, text="Forbidden")

    client = AzureMonitorPrometheusClient(Credential(), requester=requester)
    endpoint = resource_scoped_endpoint("eastus", "/subscriptions/sub-1")

    with pytest.raises(RuntimeError, match="Prometheus query failed"):
        client.query_guest_performance(endpoint)


def test_workspace_scoped_query_omits_scoping_header() -> None:
    captured: dict = {}

    def requester(method, url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}})

    client = AzureMonitorPrometheusClient(Credential(), requester=requester)
    endpoint = workspace_scoped_endpoint("https://amw-1.eastus.prometheus.monitor.azure.com")

    client.query_guest_performance(endpoint)

    assert "x-ms-azure-scoping" not in captured["headers"]
