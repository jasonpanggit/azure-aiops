from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from api.scope import Scope
from fabric.auth import FabricAuthConfig, build_credential, build_delta_storage_options
from fabric.config import FabricRuntimeConfig
from fabric.fabric_client import FabricClient
from fabric.lakehouse_manager import LakehouseManager
from fabric.workspace_manager import WorkspaceManager
from operations.tools import FabricIQToolAdapter


@dataclass
class FakeToken:
    token: str = "token"
    expires_on: int = 4_102_444_800


class FakeCredential:
    def get_token(self, *scopes: str) -> FakeToken:
        assert scopes == ("https://api.fabric.microsoft.com/.default",)
        return FakeToken()


def test_service_principal_requires_secret_from_environment() -> None:
    config = FabricAuthConfig(
        mode="service_principal",
        tenant_id="tenant",
        client_id="client",
        client_secret_env="FABRIC_CLIENT_SECRET",
    )

    with pytest.raises(ValueError, match="FABRIC_CLIENT_SECRET"):
        build_credential(config, env={})


def test_managed_identity_uses_optional_client_id(monkeypatch) -> None:
    captured = {}

    class FakeManagedIdentityCredential:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("fabric.auth.ManagedIdentityCredential", FakeManagedIdentityCredential)

    credential = build_credential(
        FabricAuthConfig(mode="managed_identity", managed_identity_client_id="identity-client")
    )

    assert isinstance(credential, FakeManagedIdentityCredential)
    assert captured == {"client_id": "identity-client"}


def test_delta_storage_options_use_scoped_bearer_token() -> None:
    class StorageCredential:
        def get_token(self, *scopes: str) -> FakeToken:
            assert scopes == ("https://storage.azure.com/.default",)
            return FakeToken()

    options = build_delta_storage_options(StorageCredential())

    assert options == {
        "azure_storage_token": "token",
        "azure_use_fabric_endpoint": "true",
    }


def test_fabric_client_retries_transient_response_and_paginates() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(429, request=request, headers={"Retry-After": "0"})
        token = request.url.params.get("continuationToken")
        if not token:
            return httpx.Response(
                200,
                request=request,
                json={"value": [{"id": "w1"}], "continuationToken": "next"},
            )
        return httpx.Response(200, request=request, json={"value": [{"id": "w2"}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = FabricClient(FakeCredential(), http_client=http, sleep=lambda _: None)

    rows = list(client.iter_items("/workspaces"))

    assert [row["id"] for row in rows] == ["w1", "w2"]
    assert len(calls) == 3
    assert calls[-1].endswith("continuationToken=next")


def test_fabric_client_follows_continuation_uri() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(
                200,
                request=request,
                json={
                    "value": [{"id": "o1"}],
                    "continuationUri": "https://api.fabric.microsoft.com/v1/next-page",
                },
            )
        return httpx.Response(200, request=request, json={"value": [{"id": "o2"}]})

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    assert [row["id"] for row in client.iter_items("/workspaces/w/ontologies")] == [
        "o1",
        "o2",
    ]
    assert calls[-1] == "https://api.fabric.microsoft.com/v1/next-page"


def test_fabric_client_does_not_strip_embedded_continuation_token_from_uri() -> None:
    """continuationUri (as returned by e.g. GET .../lakehouses/{id}/tables)
    already embeds its own continuationToken query string. Requesting it with
    an empty params dict would make httpx replace that query string
    entirely, stripping the token and causing the same page to be re-fetched
    forever instead of advancing.
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "continuationToken=embedded-token" in str(request.url):
            return httpx.Response(200, request=request, json={"data": [{"name": "t2"}]})
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [{"name": "t1"}],
                "continuationUri": (
                    "https://api.fabric.microsoft.com/v1/workspaces/w/lakehouses/l/tables"
                    "?continuationToken=embedded-token"
                ),
            },
        )

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    rows = list(client.iter_items("/workspaces/w/lakehouses/l/tables"))

    assert [row["name"] for row in rows] == ["t1", "t2"]
    assert calls[1].endswith("continuationToken=embedded-token")


def test_fabric_client_paginates_data_keyed_responses() -> None:
    """GET .../lakehouses/{id}/tables returns items under "data" rather than
    "value" (unlike most other Fabric list endpoints). iter_items must not
    silently yield zero results for this response shape.
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        token = request.url.params.get("continuationToken")
        if not token:
            return httpx.Response(
                200,
                request=request,
                json={"data": [{"name": "t1"}], "continuationToken": "next"},
            )
        return httpx.Response(200, request=request, json={"data": [{"name": "t2"}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = FabricClient(FakeCredential(), http_client=http, sleep=lambda _: None)

    rows = list(client.iter_items("/workspaces/w/lakehouses/l/tables"))

    assert [row["name"] for row in rows] == ["t1", "t2"]


def test_fabric_client_follows_completed_operation_location() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lakehouses"):
            return httpx.Response(
                202,
                request=request,
                headers={"Location": "https://api.fabric.microsoft.com/v1/operations/op1", "Retry-After": "0"},
            )
        if request.url.path.endswith("/operations/op1"):
            return httpx.Response(
                200,
                request=request,
                headers={"Location": "https://api.fabric.microsoft.com/v1/workspaces/w1/lakehouses/l1"},
                json={"status": "Succeeded"},
            )
        return httpx.Response(200, request=request, json={"id": "l1", "displayName": "Inventory"})

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    result = client.request("POST", "/workspaces/w1/lakehouses", json_body={"displayName": "Inventory"})

    assert result["id"] == "l1"


def test_fabric_client_follows_operation_location_on_analysis_windows_net() -> None:
    """Long-running Fabric item operations (e.g. creating an Ontology item)
    return a 202 Location on a regional Power BI/Fabric backend cluster host
    such as "wabi-west-us3-a-primary-redirect.analysis.windows.net", not on
    api.fabric.microsoft.com itself. That legitimate operation-tracking host
    must be trusted, not rejected as a cross-origin URL.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ontologies"):
            return httpx.Response(
                202,
                request=request,
                headers={
                    "Location": (
                        "https://wabi-west-us3-a-primary-redirect.analysis.windows.net"
                        "/v1/operations/op1"
                    ),
                    "Retry-After": "0",
                },
            )
        if "/operations/op1" in request.url.path:
            return httpx.Response(
                200,
                request=request,
                headers={"Location": "https://api.fabric.microsoft.com/v1/workspaces/w1/ontologies/o1"},
                json={"status": "Succeeded"},
            )
        return httpx.Response(200, request=request, json={"id": "o1", "displayName": "Ontology"})

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    result = client.request("POST", "/workspaces/w1/ontologies", json_body={"displayName": "Ontology"})

    assert result["id"] == "o1"


def test_fabric_client_reads_blob_backed_operation_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getDefinition"):
            return httpx.Response(
                202,
                request=request,
                headers={
                    "Location": (
                        "https://wabi-west-us3-a-primary-redirect.analysis.windows.net"
                        "/v1/operations/op1"
                    ),
                    "Retry-After": "0",
                },
            )
        if request.url.path.endswith("/operations/op1/result"):
            return httpx.Response(
                200,
                request=request,
                json={"definition": {"parts": [{"path": "data_agent.json"}]}},
            )
        if request.url.path.endswith("/operations/op1"):
            return httpx.Response(
                200,
                request=request,
                json={
                    "status": "Succeeded",
                    "blobInfoId": "blob-1",
                    "resultContentType": "application/json",
                },
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    result = client.request(
        "POST",
        "/workspaces/w/items/a/getDefinition",
        json_body={"format": "Default"},
    )

    assert result["definition"]["parts"][0]["path"] == "data_agent.json"


@pytest.mark.parametrize(
    "url",
    (
        "https://attacker.invalid/steal",
        "http://api.fabric.microsoft.com/v1/workspaces",
        # Must be rejected as a suffix match, not a substring match: hosts
        # like these are not actually subdomains of analysis.windows.net.
        "https://evil-analysis.windows.net.attacker.invalid/steal",
        "https://notanalysis.windows.net/steal",
    ),
)
def test_fabric_client_rejects_untrusted_absolute_request_urls(url: str) -> None:
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, request=request, json={})

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ValueError, match="trusted HTTPS Fabric origin"):
        client.request("GET", url)
    assert sent == []


def test_fabric_client_rejects_cross_origin_continuation_uri() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "value": [],
                "continuationUri": "https://attacker.invalid/next",
            },
        )

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ValueError, match="trusted HTTPS Fabric origin"):
        list(client.iter_items("/workspaces"))
    assert len(requests) == 1


def test_fabric_client_rejects_cross_origin_operation_location() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202,
            request=request,
            headers={"Location": "https://attacker.invalid/operation"},
        )

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    with pytest.raises(ValueError, match="trusted HTTPS Fabric origin"):
        client.request("POST", "/workspaces/w1/lakehouses", json_body={})
    assert len(requests) == 1


def test_fabric_client_retries_transport_error_with_stable_request_id() -> None:
    request_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_ids.append(request.headers["x-ms-client-request-id"])
        if len(request_ids) == 1:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(200, request=request, json={"value": []})

    client = FabricClient(
        FakeCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    assert client.request("GET", "/workspaces") == {"value": []}
    assert len(set(request_ids)) == 1


def test_workspace_manager_resolves_configured_name() -> None:
    client = type("Client", (), {"iter_items": lambda _self, _path: iter([
        {"id": "w1", "displayName": "Operations"},
        {"id": "w2", "displayName": "Other"},
    ])})()

    resolved = WorkspaceManager(client).resolve(workspace_name="Operations")

    assert resolved["id"] == "w1"


def test_lakehouse_manager_creates_missing_lakehouse() -> None:
    class Client:
        def iter_items(self, path):
            assert path == "/workspaces/w1/lakehouses"
            return iter([])

        def request(self, method, path, json_body=None, **_kwargs):
            assert (method, path) == ("POST", "/workspaces/w1/lakehouses")
            assert json_body["displayName"] == "Inventory"
            return {"id": "l1", "displayName": "Inventory"}

    lakehouse = LakehouseManager(Client(), "w1").resolve(
        lakehouse_name="Inventory",
        create_if_missing=True,
    )

    assert lakehouse["id"] == "l1"


def test_lakehouse_manager_waits_for_delta_table_registration() -> None:
    manager = LakehouseManager(type("Client", (), {})(), "w1")
    calls = iter([
        [{"name": "other"}],
        [{"name": "bronze_resources"}, {"name": "other"}],
    ])
    manager.list_tables = lambda _lakehouse_id: next(calls)

    registered = manager.ensure_tables_registered(
        "l1",
        {"bronze_resources"},
        attempts=2,
        sleep=lambda _: None,
    )

    assert registered == {"bronze_resources"}


def test_fabric_runtime_config_resolves_local_paths(tmp_path) -> None:
    path = tmp_path / "fabric.yaml"
    path.write_text(
        """
fabric:
  auth:
    mode: managed_identity
  workspace_name: Operations
  lakehouse_name: Inventory
  capacity:
    subscription_id: sub-fabric
    resource_group: rg-fabric
    capacity_name: cap-aiops
  create_lakehouse_if_missing: true
  source_data_root: ./source
  local_onelake_root: ./mock-lakehouse
  patch_policies:
    - name: Production baseline
      environment: Production
      max_patch_age_days: 30
      minimum_compliance_score: 90
  lifecycle:
    enabled: true
    catalog_path: ./lifecycle-catalog.json
    approaching_months: 24
    near_months: 12
    critical_months: 6
  incident_causality:
    enabled: true
    lookback_hours: 72
    max_incidents: 2000
    max_evidence_rows: 25000
  change_intelligence:
    enabled: true
    max_changes: 30000
    max_output_items: 75
  predictive:
    enabled: true
    max_history_rows: 40000
    max_output_items: 60
  topology_pipeline:
    enabled: true
  ontology_pipeline:
    enabled: false
"""
    )

    config = FabricRuntimeConfig.load(path)

    assert config.source_data_root == (tmp_path / "source").resolve()
    assert config.local_onelake_root == (tmp_path / "mock-lakehouse").resolve()
    assert config.capacity.subscription_id == "sub-fabric"
    assert config.capacity.resource_group == "rg-fabric"
    assert config.capacity.capacity_name == "cap-aiops"
    assert config.create_lakehouse_if_missing
    assert config.patch_policies[0].name == "Production baseline"
    assert config.patch_policies[0].minimum_compliance_score == 90
    assert config.lifecycle.enabled is True
    assert config.lifecycle.catalog_path == (tmp_path / "lifecycle-catalog.json").resolve()
    assert config.lifecycle.approaching_months == 24
    assert config.incident_causality.enabled is True
    assert config.incident_causality.lookback_hours == 72
    assert config.incident_causality.max_incidents == 2000
    assert config.incident_causality.max_evidence_rows == 25000
    assert config.change_intelligence.enabled is True
    assert config.change_intelligence.max_changes == 30000
    assert config.change_intelligence.max_output_items == 75
    assert config.predictive.enabled is True
    assert config.predictive.max_history_rows == 40000
    assert config.predictive.max_output_items == 60
    assert config.topology_pipeline.enabled is True
    assert config.ontology_pipeline.enabled is False


@pytest.mark.parametrize("value", [True, 1.5])
def test_predictive_runtime_bounds_reject_non_integer_values(tmp_path, value) -> None:
    config_path = tmp_path / "fabric.yaml"
    config_path.write_text(
        f"""
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  predictive:
    enabled: true
    max_history_rows: {str(value).lower()}
    max_output_items: 100
"""
    )

    with pytest.raises(TypeError, match="max_history_rows must be an integer"):
        FabricRuntimeConfig.load(config_path)


def test_load_remediation_runtime_configuration(tmp_path) -> None:
    config_path = tmp_path / "fabric.yaml"
    config_path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  remediation:
    enabled: true
    max_resources: 4000
    max_plans: 800
    max_output_items: 50
    max_dependencies: 75
"""
    )

    config = FabricRuntimeConfig.load(config_path)

    assert config.remediation.enabled is True
    assert config.remediation.max_resources == 4000
    assert config.remediation.max_plans == 800
    assert config.remediation.max_output_items == 50
    assert config.remediation.max_dependencies == 75


@pytest.mark.parametrize("value", [True, 1.5, "100"])
def test_remediation_runtime_bounds_fail_closed(tmp_path, value) -> None:
    rendered = f'"{value}"' if isinstance(value, str) else str(value).lower()
    config_path = tmp_path / "fabric.yaml"
    config_path.write_text(
        f"""
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  remediation:
    max_plans: {rendered}
"""
    )

    with pytest.raises(TypeError, match="fabric.remediation.max_plans"):
        FabricRuntimeConfig.load(config_path)


def test_fabric_iq_adapter_stamps_governed_enrichment() -> None:
    adapter = FabricIQToolAdapter(
        query=lambda kind, args, scope: {
            "data": {"subscription": "sub-a", "kind": kind},
            "freshness": "fresh",
            "provenance": "fabric-runtime",
            "authorization": "managed-identity",
        }
    )
    result = adapter.run(
        "relationships",
        {"subject": "network"},
        Scope.from_mapping({"subscription": ["sub-a"]}),
    )
    assert result.status == "ok"
    assert result.data["metadata"]["identity_authority"] is False
    assert result.data["metadata"]["provenance"] == "fabric-runtime"
