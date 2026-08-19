from __future__ import annotations

import json
from dataclasses import dataclass

from hermes_arg_connector.azure import AzureCliArgClient, AzureMcpClient, CommandResult
from hermes_arg_connector.queries import QuerySpec


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
