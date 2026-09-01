from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from onboarding.azure_clients import (
    AzureCliArgClient,
    AzureCostManagementClient,
    AzureMcpClient,
    AzureMonitorMetricsClient,
    AzureResourceGraphClient,
    CommandResult,
)
from onboarding.query_catalog import QuerySpec


@dataclass
class FakeRunner:
    responses: list[CommandResult]

    def __post_init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str], timeout: int) -> CommandResult:
        self.commands.append(command)
        return self.responses.pop(0)


def test_azure_mcp_lists_subscriptions_using_pinned_package() -> None:
    payload = {"status": 200, "results": [{"subscriptionId": "sub-1", "tenantId": "tenant-1"}]}
    runner = FakeRunner([CommandResult(0, json.dumps(payload), "")])
    client = AzureMcpClient(
        runner=runner,
        command_prefix=("npx", "-y", "@azure/mcp@3.0.0-beta.35"),
    )

    subscriptions = client.list_subscriptions()

    assert subscriptions == payload["results"]
    assert runner.commands[0][:4] == ["npx", "-y", "@azure/mcp@3.0.0-beta.35", "subscription"]
    assert runner.commands[0][4:] == ["list"]


def test_azure_mcp_defaults_to_preinstalled_executable() -> None:
    payload = {"status": 200, "results": {"subscriptions": []}}
    runner = FakeRunner([CommandResult(0, json.dumps(payload), "")])

    AzureMcpClient(runner=runner).list_subscriptions()

    assert runner.commands[0] == ["azmcp", "subscription", "list"]


def test_azure_mcp_accepts_nested_subscription_payload() -> None:
    payload = {
        "status": 200,
        "results": {"subscriptions": [{"subscriptionId": "sub-1", "tenantId": "tenant-1"}]},
    }
    runner = FakeRunner([CommandResult(0, json.dumps(payload), "")])

    subscriptions = AzureMcpClient(runner=runner).list_subscriptions()

    assert subscriptions == payload["results"]["subscriptions"]


def test_arg_client_follows_skip_tokens() -> None:
    first = {"data": [{"id": "a"}], "skip_token": "next"}
    second = {"data": [{"id": "b"}]}
    runner = FakeRunner([
        CommandResult(0, json.dumps(first), ""),
        CommandResult(0, json.dumps(second), ""),
    ])
    client = AzureCliArgClient(runner=runner, page_size=1000)
    spec = QuerySpec("resources", "Resources", "Resources | project id", False)

    rows = client.query(spec, ["sub-1"])

    assert rows == [{"id": "a"}, {"id": "b"}]
    assert "--skip-token" not in runner.commands[0]
    assert runner.commands[1][-2:] == ["--skip-token", "next"]


def test_arg_client_raises_actionable_error() -> None:
    runner = FakeRunner([CommandResult(1, "", "not logged in")])
    client = AzureCliArgClient(runner=runner)
    spec = QuerySpec("resources", "Resources", "Resources", False)

    try:
        client.query(spec, ["sub-1"])
    except RuntimeError as exc:
        assert "not logged in" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_arg_client_uses_management_group_scope() -> None:
    runner = FakeRunner([CommandResult(0, json.dumps({"data": []}), "")])
    client = AzureCliArgClient(runner=runner)
    spec = QuerySpec(
        "management_groups",
        "ResourceContainers",
        "ResourceContainers",
        False,
        "management_groups",
    )

    client.query(spec, ["mg-root"])

    assert "--management-groups" in runner.commands[0]
    assert "--subscriptions" not in runner.commands[0]


def test_resource_graph_client_uses_connection_credential_and_subscription_scope() -> None:
    class Token:
        token = "connection-token"

    class Credential:
        def __init__(self) -> None:
            self.scopes: list[str] = []

        def get_token(self, scope: str):
            self.scopes.append(scope)
            return Token()

    requests: list[dict] = []

    def requester(method: str, url: str, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json={"data": [{"id": "resource-1"}]})

    credential = Credential()
    client = AzureResourceGraphClient(credential, requester=requester)
    spec = QuerySpec("resources", "Resources", "Resources | project id", False)

    assert client.query(spec, ["connection-subscription"]) == [{"id": "resource-1"}]
    assert credential.scopes == ["https://management.azure.com/.default"]
    assert requests[0]["headers"]["Authorization"] == "Bearer connection-token"
    assert requests[0]["json"]["subscriptions"] == ["connection-subscription"]


def test_cost_management_client_queries_daily_actual_costs() -> None:
    class Token:
        token = "connection-token"

    class Credential:
        def __init__(self) -> None:
            self.scopes: list[str] = []

        def get_token(self, scope: str):
            self.scopes.append(scope)
            return Token()

    requests: list[dict] = []

    def requester(method: str, url: str, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "properties": {
                    "columns": [
                        {"name": "PreTaxCost"},
                        {"name": "UsageDate"},
                        {"name": "Currency"},
                        {"name": "ResourceId"},
                        {"name": "ResourceGroupName"},
                        {"name": "ServiceName"},
                    ],
                    "rows": [
                        [
                            12.34,
                            "20260823",
                            "AUD",
                            "/subscriptions/sub-1/resourceGroups/rg/providers/x/y",
                            "rg",
                            "Virtual Machines",
                        ]
                    ],
                }
            },
        )

    rows = AzureCostManagementClient(Credential(), requester=requester).query_actual_costs(
        ["sub-1"]
    )

    assert rows[0]["usageDate"] == "2026-08-23"
    assert rows[0]["cost"] == 12.34
    assert rows[0]["currency"] == "AUD"
    assert rows[0]["serviceName"] == "Virtual Machines"
    assert requests[0]["json"]["type"] == "ActualCost"
    assert requests[0]["json"]["dataset"]["granularity"] == "Daily"
    assert requests[0]["url"].endswith(
        "/subscriptions/sub-1/providers/Microsoft.CostManagement/query"
    )


def test_cost_management_client_retries_throttled_requests() -> None:
    class Token:
        token = "connection-token"

    class Credential:
        def get_token(self, scope: str):
            return Token()

    responses = [
        httpx.Response(429, json={"error": {"code": "429"}}, headers={"Retry-After": "0"}),
        httpx.Response(
            200,
            json={
                "properties": {
                    "columns": [{"name": "PreTaxCost"}, {"name": "UsageDate"}],
                    "rows": [[1.23, "20260824"]],
                }
            },
        ),
    ]
    sleeps: list[float] = []

    def requester(method: str, url: str, **kwargs):
        return responses.pop(0)

    rows = AzureCostManagementClient(
        Credential(),
        requester=requester,
        retry_sleep=sleeps.append,
    ).query_actual_costs(["sub-1"])

    assert rows[0]["cost"] == 1.23
    assert rows[0]["usageDate"] == "2026-08-24"
    assert sleeps == [0.0]


def test_cost_management_client_isolates_a_throttled_subscription() -> None:
    """One throttled subscription must not discard other subscriptions' costs."""

    class Token:
        token = "connection-token"

    class Credential:
        def get_token(self, scope: str):
            return Token()

    def requester(method: str, url: str, **kwargs):
        if "sub-throttled" in url:
            return httpx.Response(
                429,
                json={"error": {"code": "429", "message": "Too many requests."}},
                headers={"Retry-After": "0"},
            )
        return httpx.Response(
            200,
            json={
                "properties": {
                    "columns": [{"name": "PreTaxCost"}, {"name": "UsageDate"}],
                    "rows": [[4.56, "20260824"]],
                }
            },
        )

    rows = AzureCostManagementClient(
        Credential(),
        requester=requester,
        retry_sleep=lambda _: None,
    ).query_actual_costs(["sub-throttled", "sub-ok"])

    assert [row["subscriptionId"] for row in rows] == ["sub-ok"]
    assert rows[0]["cost"] == 4.56


def test_cost_management_client_raises_when_every_subscription_fails() -> None:
    class Token:
        token = "connection-token"

    class Credential:
        def get_token(self, scope: str):
            return Token()

    def requester(method: str, url: str, **kwargs):
        return httpx.Response(429, json={"error": {"code": "429"}}, headers={"Retry-After": "0"})

    try:
        AzureCostManagementClient(
            Credential(),
            requester=requester,
            retry_sleep=lambda _: None,
        ).query_actual_costs(["sub-1", "sub-2"])
    except RuntimeError as exc:
        assert "every subscription" in str(exc)
    else:  # pragma: no cover - guard
        raise AssertionError("expected RuntimeError when all subscriptions fail")


def test_cost_management_retry_honours_vendor_ratelimit_header() -> None:
    """Cost Management publishes its budget via a vendor header, not Retry-After."""

    class Token:
        token = "connection-token"

    class Credential:
        def get_token(self, scope: str):
            return Token()

    responses = [
        httpx.Response(
            429,
            json={"error": {"code": "429"}},
            headers={
                "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "7",
            },
        ),
        httpx.Response(
            200,
            json={
                "properties": {
                    "columns": [{"name": "PreTaxCost"}, {"name": "UsageDate"}],
                    "rows": [[1.0, "20260824"]],
                }
            },
        ),
    ]
    sleeps: list[float] = []

    AzureCostManagementClient(
        Credential(),
        requester=lambda method, url, **kwargs: responses.pop(0),
        retry_sleep=sleeps.append,
    ).query_actual_costs(["sub-1"])

    assert sleeps == [7.0]


def test_monitor_metrics_client_returns_latest_average_per_metric() -> None:
    class Token:
        token = "connection-token"

    class Credential:
        def __init__(self) -> None:
            self.scopes: list[str] = []

        def get_token(self, scope: str):
            self.scopes.append(scope)
            return Token()

    requests: list[dict] = []

    def requester(method: str, url: str, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": {"value": "Percentage CPU"},
                        "unit": "Percent",
                        "timeseries": [
                            {
                                "data": [
                                    {"timeStamp": "2026-08-23T00:00:00Z", "average": None},
                                    {"timeStamp": "2026-08-23T00:05:00Z", "average": 42.5},
                                ]
                            }
                        ],
                    },
                    {
                        "name": {"value": "Network In Total"},
                        "unit": "Bytes",
                        "timeseries": [{"data": [{"timeStamp": "t", "average": 1024.0}]}],
                    },
                ]
            },
        )

    credential = Credential()
    resource_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"
    client = AzureMonitorMetricsClient(credential, requester=requester)

    metrics = client.query_resource_metrics(resource_id)

    assert metrics["Percentage CPU"]["value"] == 42.5
    assert metrics["Percentage CPU"]["unit"] == "Percent"
    assert metrics["Percentage CPU"]["series"] == [
        {"timestamp": "2026-08-23T00:05:00Z", "value": 42.5}
    ]
    assert metrics["Network In Total"]["value"] == 1024.0
    assert credential.scopes == ["https://management.azure.com/.default"]
    assert requests[0]["headers"]["Authorization"] == "Bearer connection-token"
    assert requests[0]["url"].endswith(
        "subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1/providers/microsoft.insights/metrics"
    )
    assert "Percentage CPU" in requests[0]["params"]["metricnames"]
    # The timespan must never contain a literal "+" (UTC offset), since some
    # transports decode "+" back to a space and Azure Monitor then rejects the
    # timespan as an invalid ISO 8601 interval.
    timespan = requests[0]["params"]["timespan"]
    assert "+" not in timespan
    assert timespan.count("Z") == 2


def test_monitor_metrics_client_retries_throttled_requests() -> None:
    class Token:
        token = "connection-token"

    class Credential:
        def get_token(self, scope: str):
            return Token()

    responses = [
        httpx.Response(429, json={"error": {"code": "429"}}, headers={"Retry-After": "0"}),
        httpx.Response(
            200,
            json={
                "value": [
                    {
                        "name": {"value": "Percentage CPU"},
                        "unit": "Percent",
                        "timeseries": [{"data": [{"timeStamp": "t", "average": 10.0}]}],
                    }
                ]
            },
        ),
    ]
    sleeps: list[float] = []

    def requester(method: str, url: str, **kwargs):
        return responses.pop(0)

    metrics = AzureMonitorMetricsClient(
        Credential(),
        requester=requester,
        retry_sleep=sleeps.append,
    ).query_resource_metrics("/subscriptions/sub-1/resourceGroups/rg/providers/x/y")

    assert metrics["Percentage CPU"]["value"] == 10.0
    assert sleeps == [0.0]


def test_monitor_metrics_client_rejects_blank_resource_id() -> None:
    class Credential:
        def get_token(self, scope: str):
            raise AssertionError("should not fetch a token for an invalid request")

    client = AzureMonitorMetricsClient(Credential(), requester=lambda *a, **k: None)

    try:
        client.query_resource_metrics("   ")
    except ValueError as exc:
        assert "resource id" in str(exc)
    else:
        raise AssertionError("expected ValueError")
