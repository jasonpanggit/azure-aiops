# ruff: noqa: F811
"""Native navigation does not confer unattended authoring or execute providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontology_discovery.native_agent import native_agent_capabilities
from tests.test_api_ontology_discovery import (  # noqa: F401
    _headers,
    _scope,
    api_fixture,
)

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
ITEM = "bb479201-8ab1-4fde-ab6c-9f9a16477115"
TARGET = {
    "AIOPS_ONTOLOGY_NATIVE_WORKSPACE_ID": WORKSPACE,
    "AIOPS_ONTOLOGY_NATIVE_ITEM_ID": ITEM,
}


def test_native_is_primary_but_configuration_is_not_a_live_receipt():
    result = native_agent_capabilities(TARGET)
    native = result["native_interactive"]
    assert result["primary_mode"] == "native_interactive"
    assert native["status"] == "configured_unverified"
    assert native["portal_url"] == (
        f"https://app.fabric.microsoft.com/groups/{WORKSPACE}/ontologies/{ITEM}"
    )
    assert native["default_mode"] == "plan"
    assert native["execution_verified"] is False
    assert native["unattended_authoring"] == "unavailable"
    assert native["apply_requires_review"] is True
    assert result["foundry_fallback"] == {"selection_required": True, "selected": False}


def test_legacy_publisher_target_is_never_substituted_for_native():
    result = native_agent_capabilities({
        "FABRIC_WORKSPACE_ID": WORKSPACE, "FABRIC_ONTOLOGY_ID": ITEM,
        "FOUNDRY_PROJECT_ENDPOINT": "https://unused.invalid",
    })
    assert result["native_interactive"]["status"] == "not_configured"
    assert result["native_interactive"]["portal_url"] is None


@pytest.mark.parametrize("target", [
    {"AIOPS_ONTOLOGY_NATIVE_WORKSPACE_ID": WORKSPACE},
    {"AIOPS_ONTOLOGY_NATIVE_ITEM_ID": ITEM},
    {**TARGET, "AIOPS_ONTOLOGY_NATIVE_WORKSPACE_ID": "../foreign"},
    {**TARGET, "AIOPS_ONTOLOGY_NATIVE_ITEM_ID": f"{ITEM}?redirect=https://foreign.invalid"},
])
def test_invalid_or_partial_target_has_no_link_or_automatic_fallback(target):
    result = native_agent_capabilities(target)
    assert result["native_interactive"]["status"] == "invalid_configuration"
    assert result["native_interactive"]["portal_url"] is None
    assert result["foundry_fallback"]["selected"] is False


def test_scoped_endpoint_works_without_reading_run_or_publication_state(
    api_fixture, monkeypatch,
):
    for key, value in TARGET.items():
        monkeypatch.setenv(key, value)
    provider = api_fixture["provider"]
    monkeypatch.setattr(provider.run_store, "list_runs", lambda **_: pytest.fail("run read"))
    monkeypatch.setattr(provider, "generation", lambda _: pytest.fail("generation read"))
    response = api_fixture["client"].get(
        "/api/v1/ontology-discovery/agent-capabilities",
        params=_scope(), headers=_headers("reader"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["native_interactive"]["status"] == "configured_unverified"
    assert response.json()["scope"] == {"subscription": [_scope()["subscription"]]}
    assert response.json()["evidence"][0]["source_table"] == "server_configuration"


def test_native_target_is_not_disclosed_for_unauthorized_connection(api_fixture, monkeypatch):
    for key, value in TARGET.items():
        monkeypatch.setenv(key, value)
    response = api_fixture["client"].get(
        "/api/v1/ontology-discovery/agent-capabilities",
        params=_scope(connection_id="conn-b"), headers=_headers("reader"),
    )
    assert response.status_code == 404
    assert WORKSPACE not in response.text and ITEM not in response.text


def test_native_capabilities_require_application_authentication(api_fixture):
    response = api_fixture["client"].get(
        "/api/v1/ontology-discovery/agent-capabilities", params=_scope(),
    )
    assert response.status_code == 401


def test_native_terraform_target_is_api_only_opt_in_and_independent():
    root = Path(__file__).resolve().parents[1] / "infra" / "terraform"
    variables = (root / "variables.tf").read_text()
    target = variables.split('variable "fabric_native_ontology_target" {', 1)[1]
    target = target.split('\nvariable "', 1)[0]
    assert "default = null" in target
    assert "validation {" in target
    assert "workspace_id = string" in target and "item_id      = string" in target
    apps = (root / "container_apps.tf").read_text()
    api = apps.split('resource "azurerm_container_app" "api" {', 1)[1]
    api = api.split('\nresource "', 1)[0]
    assert "var.fabric_native_ontology_target == null ? {}" in api
    assert "AIOPS_ONTOLOGY_NATIVE_WORKSPACE_ID = var.fabric_native_ontology_target.workspace_id" in api
    assert "AIOPS_ONTOLOGY_NATIVE_ITEM_ID      = var.fabric_native_ontology_target.item_id" in api
    consumers = [
        path.name for path in root.glob("*.tf")
        if "var.fabric_native_ontology_target" in path.read_text()
    ]
    assert sorted(consumers) == ["container_apps.tf", "variables.tf"]
    dev = (root / "environments" / "dev.native-ontology.tfvars").read_text()
    assert WORKSPACE in dev and ITEM in dev
    assert "191c9b47" not in dev and "FABRIC_ONTOLOGY_ID" not in dev
