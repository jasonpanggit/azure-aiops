from __future__ import annotations

import httpx
import pytest

from hermes_arg_connector.logs import (
    CONFIGURATION_DATA_QUERY,
    LOGS_QUERY_SCOPE,
    AzureMonitorLogsClient,
    LogsQueryLimits,
    parse_logs_tables,
)


class Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str):
        self.scopes.append(scope)
        return type("Token", (), {"token": "logs-token"})()


def test_configuration_data_client_uses_logs_query_api_and_fixed_kql() -> None:
    requests: list[dict] = []

    def requester(method: str, url: str, **kwargs):
        requests.append({"method": method, "url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "tables": [
                    {
                        "name": "PrimaryResult",
                        "columns": [
                            {"name": "ConfigDataType", "type": "string"},
                            {"name": "SoftwareName", "type": "string"},
                        ],
                        "rows": [["Software", "7-Zip"]],
                    }
                ]
            },
        )

    credential = Credential()
    rows = AzureMonitorLogsClient(credential, requester=requester).query("workspace-1")

    assert rows == [{"ConfigDataType": "Software", "SoftwareName": "7-Zip"}]
    assert credential.scopes == [LOGS_QUERY_SCOPE]
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"].endswith("/v1/workspaces/workspace-1/query")
    assert requests[0]["json"] == {"query": CONFIGURATION_DATA_QUERY}
    assert requests[0]["headers"]["Authorization"] == "Bearer logs-token"


def test_successful_zero_rows_is_valid() -> None:
    payload = {
        "tables": [
            {
                "columns": [{"name": "SoftwareName", "type": "string"}],
                "rows": [],
            }
        ]
    }
    assert parse_logs_tables(payload) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tables": []},
        {"tables": [{"columns": [{"name": "Name"}], "rows": [["a", "extra"]]}]},
        {"tables": [{"columns": [{"name": "Name"}, {"name": "Name"}], "rows": []}]},
    ],
)
def test_logs_parser_rejects_missing_or_malformed_schema(payload: dict) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_logs_tables(payload)


def test_logs_client_rejects_http_failure_and_response_limits() -> None:
    def failed_requester(method: str, url: str, **kwargs):
        return httpx.Response(503, text="workspace unavailable")

    with pytest.raises(RuntimeError, match="workspace unavailable"):
        AzureMonitorLogsClient(Credential(), requester=failed_requester).query("workspace-1")

    def oversized_requester(method: str, url: str, **kwargs):
        return httpx.Response(200, content=b"{}")

    with pytest.raises(RuntimeError, match="byte limit"):
        AzureMonitorLogsClient(
            Credential(),
            requester=oversized_requester,
            limits=LogsQueryLimits(max_response_bytes=1),
        ).query("workspace-1")


def test_logs_client_rejects_invalid_workspace_and_row_limit() -> None:
    with pytest.raises(ValueError, match="workspace ID"):
        AzureMonitorLogsClient(Credential()).query("../workspace")

    payload = {
        "tables": [
            {
                "columns": [{"name": "Name", "type": "string"}],
                "rows": [["a"], ["b"]],
            }
        ]
    }
    with pytest.raises(ValueError, match="row limit"):
        parse_logs_tables(payload, max_rows=1)


def test_logs_client_preserves_timeout_and_malformed_json_failures() -> None:
    def timeout_requester(method: str, url: str, **kwargs):
        raise httpx.ReadTimeout("workspace query timed out")

    with pytest.raises(httpx.ReadTimeout, match="timed out"):
        AzureMonitorLogsClient(Credential(), requester=timeout_requester).query(
            "workspace-1"
        )

    def malformed_requester(method: str, url: str, **kwargs):
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(RuntimeError, match="valid JSON"):
        AzureMonitorLogsClient(Credential(), requester=malformed_requester).query(
            "workspace-1"
        )
