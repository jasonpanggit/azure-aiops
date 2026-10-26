from __future__ import annotations

import httpx
import pytest

from onboarding.azure_clients import (
    AzureMonitorDiagnosticSettingsClient,
    DiagnosticSettingsReadError,
)

RESOURCE_ID = (
    "/subscriptions/sub-a/resourceGroups/rg-a/providers/"
    "Microsoft.Compute/virtualMachines/vm-a"
)
SETTINGS_PATH = (
    "/subscriptions/sub-a/resourceGroups/rg-a/providers/"
    "Microsoft.Compute/virtualMachines/vm-a/providers/"
    "Microsoft.Insights/diagnosticSettings"
)
API_VERSION = "2021-05-01-preview"


class Credential:
    def __init__(self, token="safe-token"):
        self.token = token
        self.scopes = []

    def get_token(self, scope):
        self.scopes.append(scope)
        return type("Token", (), {"token": self.token})()


class Requester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(payload, status=200):
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("GET", "https://management.azure.com"),
    )


def make_client(requester, credential=None, **kwargs):
    return AzureMonitorDiagnosticSettingsClient(
        credential or Credential(),
        requester=requester,
        **kwargs,
    )


def test_lists_settings_and_uses_existing_arm_credential_scope():
    requester = Requester([response({"value": [{"name": "workspace"}]})])
    credential = Credential()
    client = make_client(requester, credential)
    rows = client.list_resource_settings(
        RESOURCE_ID,
        authorized_subscription_ids={"sub-a"},
    )
    assert rows == ({"name": "workspace"},)
    assert credential.scopes == ["https://management.azure.com/.default"]
    method, url, kwargs = requester.calls[0]
    assert method == "GET"
    assert url == f"https://management.azure.com{SETTINGS_PATH}"
    assert kwargs["params"] == {"api-version": API_VERSION}
    assert kwargs["headers"]["Authorization"] == "Bearer safe-token"


def test_empty_settings_collection_is_a_complete_empty_observation():
    requester = Requester([response({"value": []})])
    rows = make_client(requester).list_resource_settings(
        RESOURCE_ID,
        authorized_subscription_ids={"sub-a"},
    )
    assert rows == ()


def test_follows_bounded_same_resource_pagination():
    continuation = (
        f"https://management.azure.com{SETTINGS_PATH}"
        f"?api-version={API_VERSION}&%24skipToken=page-2"
    )
    requester = Requester(
        [
            response({"value": [{"name": "first"}], "nextLink": continuation}),
            response({"value": [{"name": "second"}]}),
        ]
    )
    rows = make_client(requester).list_resource_settings(
        RESOURCE_ID,
        authorized_subscription_ids={"sub-a"},
    )
    assert [item["name"] for item in rows] == ["first", "second"]
    assert len(requester.calls) == 2
    assert requester.calls[1][1] == continuation
    assert requester.calls[1][2]["params"] is None


@pytest.mark.parametrize(
    "next_link",
    [
        "https://attacker.example/steal?api-version=2021-05-01-preview",
        f"https://management.azure.com/subscriptions/sub-b/providers/x?api-version={API_VERSION}",
        f"https://management.azure.com{SETTINGS_PATH}?api-version={API_VERSION}&token=x",
        f"http://management.azure.com{SETTINGS_PATH}?api-version={API_VERSION}",
    ],
)
def test_rejects_foreign_or_malformed_next_links(next_link):
    requester = Requester([response({"value": [], "nextLink": next_link})])
    with pytest.raises(DiagnosticSettingsReadError):
        make_client(requester).list_resource_settings(
            RESOURCE_ID,
            authorized_subscription_ids={"sub-a"},
        )
    assert len(requester.calls) == 1


def test_provider_errors_malformed_collections_and_page_limit_fail_closed():
    requester = Requester([response({"error": "denied"}, status=403)])
    with pytest.raises(DiagnosticSettingsReadError) as caught:
        make_client(requester).list_resource_settings(
            RESOURCE_ID,
            authorized_subscription_ids={"sub-a"},
        )
    assert caught.value.status_code == 403

    malformed = Requester([response({"value": {}})])
    with pytest.raises(DiagnosticSettingsReadError):
        make_client(malformed).list_resource_settings(
            RESOURCE_ID,
            authorized_subscription_ids={"sub-a"},
        )

    continuation = (
        f"https://management.azure.com{SETTINGS_PATH}?api-version={API_VERSION}"
        "&%24skipToken=next"
    )
    paged = Requester([response({"value": [], "nextLink": continuation})])
    with pytest.raises(DiagnosticSettingsReadError, match="page bound"):
        make_client(paged, max_pages=1).list_resource_settings(
            RESOURCE_ID,
            authorized_subscription_ids={"sub-a"},
        )


def test_denies_out_of_scope_or_unsafe_resource_ids_before_network_access():
    requester = Requester([])
    client = make_client(requester)
    with pytest.raises(PermissionError):
        client.list_resource_settings(
            RESOURCE_ID,
            authorized_subscription_ids={"sub-b"},
        )
    with pytest.raises(ValueError):
        client.list_resource_settings(
            RESOURCE_ID + "?bad=1",
            authorized_subscription_ids={"sub-a"},
        )
    assert requester.calls == []


@pytest.mark.parametrize(
    "resource_id",
    [
        RESOURCE_ID + "/../escape",
        RESOURCE_ID + "/./escape",
        RESOURCE_ID + "/child",
        RESOURCE_ID + "/bad\x00name/child",
    ],
)
def test_rejects_noncanonical_paths_before_acquiring_credential(resource_id):
    requester = Requester([])
    credential = Credential()
    with pytest.raises(ValueError):
        make_client(requester, credential).list_resource_settings(
            resource_id,
            authorized_subscription_ids={"sub-a"},
        )
    assert credential.scopes == []
    assert requester.calls == []
