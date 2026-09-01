from __future__ import annotations

import json

import pytest

from fabric import lineage


def test_entity_lineage_summary_returns_sources_for_known_entity() -> None:
    entities = {
        "entity-1": {
            "resource_id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            "tenant_id": "tenant-1",
            "subscription_id": "sub-1",
            "lineage_json": json.dumps({"source_resource_ids": ["src-a", "src-b"]}),
        }
    }

    result = lineage.entity_lineage_summary("ENTITY-1", entities)

    assert result == {"status": "found", "source_resource_ids": ["src-a", "src-b"]}


def test_entity_lineage_summary_returns_not_found_without_key_error() -> None:
    result = lineage.entity_lineage_summary("missing", {})

    assert result == {"status": "not_found", "source_resource_ids": []}


def test_entity_lineage_summary_does_not_leak_topology_fields() -> None:
    entities = {
        "entity-1": {
            "resource_id": "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
            "tenant_id": "tenant-1",
            "subscription_id": "sub-1",
            "lineage_json": json.dumps({"source_resource_ids": ["src-a"]}),
        }
    }

    result = lineage.entity_lineage_summary("entity-1", entities)

    assert set(result.keys()) == {"status", "source_resource_ids"}


def test_native_lineage_url_contains_workspace_id_and_validates_empty() -> None:
    url = lineage.native_lineage_url("workspace-123")
    assert "workspace-123" in url
    assert url.startswith("https://app.fabric.microsoft.com/groups/")
    assert url.endswith("/lineage")

    with pytest.raises(ValueError, match="workspace_id"):
        lineage.native_lineage_url("")


def test_lineage_functions_are_pure_without_network_calls(monkeypatch) -> None:
    def _forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("network should not be called")

    monkeypatch.setattr("httpx.request", _forbidden)

    entities = {"entity-1": {"lineage_json": json.dumps({"source_resource_ids": ["src-a"]})}}
    assert lineage.entity_lineage_summary("entity-1", entities)["status"] == "found"
    assert lineage.native_lineage_url("workspace-123").endswith("/lineage")
