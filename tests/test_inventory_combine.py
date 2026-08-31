"""Regression tests for the inventory connection-merge step.

Covers the identity-collision guard and the observed_at freshness tiebreak
that protects a combined snapshot from being silently overwritten by a
stale/partial refresh landing after a fresher one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from intelligence.inventory.combine import publish_combined_inventory_snapshot
from storage.datasets import DatasetStore


def _publish_connection_rows(
    root: Path,
    rows: list[dict],
    *,
    observed_at: str = "2026-08-31T10:00:00Z",
) -> None:
    store = DatasetStore(root)
    store.publish(
        {
            "inventory/os_observations": rows,
            "inventory/source_status": [],
            "inventory/software_observations": [],
            "inventory/software_source_status": [],
            "inventory/resource_observations": [],
        },
        {},
        {"runId": f"run-{observed_at}", "status": "completed", "startedAt": observed_at},
        ontology={},
    )


def _os_row(
    *,
    resource_id: str,
    machine_name: str,
    observed_at: str,
    connection_id: str = "conn-a",
) -> dict:
    return {
        "resource_id": resource_id,
        "machine_name": machine_name,
        "subscription_id": "sub-1",
        "resource_group": "rg-1",
        "os_name": "Ubuntu",
        "os_version": "22.04",
        "observed_at": observed_at,
        "connection_id": connection_id,
        "source_type": "azure_vm",
        "source_engine": "arg",
        "source_table": "Resources",
        "source_id": resource_id,
        "query_version": "inventory-os-v1",
    }


def test_merge_keeps_freshest_observed_at_for_same_identity(tmp_path: Path) -> None:
    """Two rows for the same identity from the same connection's dataset
    (e.g. a duplicate/stale row alongside a fresher one within one generation)
    must resolve to the freshest observed_at, not whichever happened to be
    read/merged last."""
    conn_root = tmp_path / "conn-a"
    resource_id = "/subscriptions/sub-1/resourcegroups/rg-1/vm-1"
    _publish_connection_rows(
        conn_root,
        [
            _os_row(
                resource_id=resource_id,
                machine_name="vm-1-stale",
                observed_at="2026-08-31T09:00:00Z",
            ),
            _os_row(
                resource_id=resource_id,
                machine_name="vm-1-fresh",
                observed_at="2026-08-31T10:00:00Z",
            ),
        ],
    )

    result = publish_combined_inventory_snapshot(
        {"conn-a": conn_root}, tmp_path / "combined"
    )

    combined_store = DatasetStore(tmp_path / "combined")
    rows = combined_store.read_dataset("inventory/os_observations")
    assert len(rows) == 1
    assert rows[0]["machine_name"] == "vm-1-fresh"
    assert result["runId"].startswith("inventory-activation-")


def test_merge_rejects_cross_connection_identity_collision(tmp_path: Path) -> None:
    conn_a = tmp_path / "conn-a"
    conn_b = tmp_path / "conn-b"
    shared_resource_id = "/subscriptions/sub-1/resourcegroups/rg-1/vm-shared"
    _publish_connection_rows(
        conn_a,
        [
            _os_row(
                resource_id=shared_resource_id,
                machine_name="vm-a",
                observed_at="2026-08-31T10:00:00Z",
                connection_id="conn-a",
            )
        ],
    )
    _publish_connection_rows(
        conn_b,
        [
            _os_row(
                resource_id=shared_resource_id,
                machine_name="vm-b",
                observed_at="2026-08-31T11:00:00Z",
                connection_id="conn-b",
            )
        ],
    )

    with pytest.raises(ValueError, match="identity collision"):
        publish_combined_inventory_snapshot(
            {"conn-a": conn_a, "conn-b": conn_b}, tmp_path / "combined"
        )
