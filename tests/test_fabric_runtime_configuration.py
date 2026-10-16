"""Deployment configuration must follow provisioned resources, not baked IDs."""

import json
from pathlib import Path

import pytest

from fabric.config import FabricRuntimeConfig
from onboarding.config import ConnectorConfig


def test_api_staging_pins_traffic_without_changing_default():
    root = Path(__file__).resolve().parents[1] / "infra" / "terraform"
    variables = (root / "variables.tf").read_text()
    apps = (root / "container_apps.tf").read_text()
    variable = variables.split('variable "api_traffic_revision" {', 1)[1].split(
        'variable "copilot_default_base_image_digest"', 1
    )[0]
    api = apps.split('resource "azurerm_container_app" "api" {', 1)[1].split(
        'resource "azurerm_container_app" "web"', 1
    )[0]
    assert 'default     = ""' in variable
    assert 'latest_revision = var.api_traffic_revision == ""' in api
    assert (
        'revision_suffix = var.api_traffic_revision == "" ? null : '
        'trimprefix(var.api_traffic_revision, "${local.base}-api--")'
    ) in api
    assert 'percentage      = 100' in api
    assert 'startswith(var.api_traffic_revision, "${local.base}-api--")' in api


def test_imported_cursor_key_metadata_does_not_trigger_rotation():
    root = Path(__file__).resolve().parents[1] / "infra" / "terraform"
    resource = (root / "main.tf").read_text().split(
        'resource "random_password" "exposure_cursor" {', 1
    )[1].split('data "azurerm_client_config"', 1)[0]
    assert "ignore_changes = [length, special]" in resource
    assert "length   = 64" in resource
    assert "special  = false" in resource


def test_terraform_config_replaces_baked_resource_ids(tmp_path, monkeypatch):
    path = tmp_path / "fabric.yaml"
    path.write_text("fabric:\n  workspace_id: deleted-workspace\n")
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG_JSON", json.dumps({
        "fabric": {
            "workspace_id": "new-workspace",
            "lakehouse_id": "new-lakehouse",
            "source_data_root": "abfss://new-workspace@onelake.dfs.fabric.microsoft.com/new-lakehouse/Files/source",
            "auth": {"mode": "managed_identity", "managed_identity_client_id": "new-identity"},
        }
    }))
    config = FabricRuntimeConfig.load(path)
    assert config.workspace_id == "new-workspace"
    assert config.lakehouse_id == "new-lakehouse"
    assert config.auth.managed_identity_client_id == "new-identity"
    assert str(config.source_data_root).startswith("abfss://new-workspace@")


@pytest.mark.parametrize("payload", ["{", "[]", '{"fabric": []}', "{}"])
def test_invalid_terraform_config_does_not_fall_back(tmp_path, monkeypatch, payload):
    path = tmp_path / "fabric.yaml"
    path.write_text("fabric:\n  workspace_id: deleted-workspace\n")
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG_JSON", payload)
    with pytest.raises(ValueError):
        FabricRuntimeConfig.load(path)


def test_file_configuration_remains_supported(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOPS_FABRIC_CONFIG_JSON", raising=False)
    path = tmp_path / "fabric.yaml"
    path.write_text("fabric:\n  workspace_id: file-workspace\n  lakehouse_id: file-lakehouse\n")
    assert FabricRuntimeConfig.load(path).workspace_id == "file-workspace"


def test_connector_output_override_keeps_onelake_uri(tmp_path, monkeypatch):
    path = tmp_path / "connector.yaml"
    path.write_text("storage:\n  output_dir: /tmp/aiops\n")
    root = "abfss://workspace@onelake.dfs.fabric.microsoft.com/lakehouse/Files/aiops"
    monkeypatch.setenv("AIOPS_CONNECTOR_OUTPUT_DIR", root)
    assert ConnectorConfig.load(path).output_dir == root


def test_connector_file_output_remains_supported(tmp_path, monkeypatch):
    monkeypatch.delenv("AIOPS_CONNECTOR_OUTPUT_DIR", raising=False)
    path = tmp_path / "connector.yaml"
    path.write_text("storage:\n  output_dir: /tmp/aiops\n")
    assert ConnectorConfig.load(path).output_dir == Path("/tmp/aiops").resolve()
