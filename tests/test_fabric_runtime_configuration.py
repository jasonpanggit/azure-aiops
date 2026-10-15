"""Deployment configuration must follow provisioned resources, not baked IDs."""

import json
from pathlib import Path

import pytest

from fabric.config import FabricRuntimeConfig
from onboarding.config import ConnectorConfig


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
