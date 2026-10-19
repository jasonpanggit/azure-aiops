"""Regression tests for the inventory connection-merge step.

Covers the identity-collision guard and the observed_at freshness tiebreak
that protects a combined snapshot from being silently overwritten by a
stale/partial refresh landing after a fresher one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from intelligence.inventory.combine import publish_combined_inventory_snapshot
from storage.datasets import DatasetStore
from storage.locking import LeaseLostError


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
        {
            "runId": f"run-{observed_at}",
            "status": "completed",
            "startedAt": observed_at,
        },
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


@pytest.mark.parametrize("publisher", ["inventory", "entities"])
def test_combined_publishers_forward_loss_guard_to_actual_promotion(tmp_path, monkeypatch, publisher):
    from onboarding.activation import publish_combined_snapshot

    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    _publish_connection_rows(source_root, [{"resource_id": "resource", "connection_id": "conn-a"}])
    target = DatasetStore(target_root)
    target.publish({"inventory/os_observations": [{"resource_id": "last-good"}]}, {}, {"runId": "old"})
    generation = target.current_generation()
    hashes = target.hash_path.read_bytes()
    original = DatasetStore._write_generation
    lost = False

    def stage_then_lose(store, *args, **kwargs):
        nonlocal lost
        result = original(store, *args, **kwargs)
        if store.root == target_root:
            lost = True
        return result

    def assert_held():
        if lost:
            raise LeaseLostError("combined_lease_lost")

    monkeypatch.setattr(DatasetStore, "_write_generation", stage_then_lose)
    with pytest.raises(LeaseLostError, match="combined_lease_lost"):
        if publisher == "inventory":
            publish_combined_inventory_snapshot(
                {"conn-a": source_root}, target_root, assert_lock_held=assert_held,
            )
        else:
            publish_combined_snapshot(
                SimpleNamespace(
                    registry=SimpleNamespace(get=lambda connection_id: connection_id),
                    sync_coordinator=SimpleNamespace(connection_output_dir=lambda connection: source_root),
                ),
                ["conn-a"], target_root, assert_lock_held=assert_held,
            )
    assert target.current_generation() == generation
    assert target.hash_path.read_bytes() == hashes


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


def test_merge_rejects_missing_active_connection_generation(tmp_path: Path) -> None:
    combined_root = tmp_path / "combined"

    with pytest.raises(RuntimeError, match="generation unavailable.*conn-a"):
        publish_combined_inventory_snapshot(
            {"conn-a": tmp_path / "missing-conn-a"},
            combined_root,
        )

    assert DatasetStore(combined_root).current_generation() is None


def test_merge_rejects_all_empty_inventory_without_explicit_authorization(
    tmp_path: Path,
) -> None:
    conn_root = tmp_path / "conn-a"
    _publish_connection_rows(conn_root, [])
    combined_root = tmp_path / "combined"

    with pytest.raises(RuntimeError, match="all-empty combined inventory"):
        publish_combined_inventory_snapshot(
            {"conn-a": conn_root},
            combined_root,
        )

    assert DatasetStore(combined_root).current_generation() is None

    manifest = publish_combined_inventory_snapshot(
        {"conn-a": conn_root},
        combined_root,
        allow_empty=True,
    )
    assert manifest["sourceRunIds"] == ["run-2026-08-31T10:00:00Z"]


def test_republish_loads_exact_combined_generation_after_pointer_moves(
    tmp_path: Path,
) -> None:
    from intelligence.inventory.combine import _load_combined_inventory_generation

    conn_root = tmp_path / "conn-a"
    resource_id = "/subscriptions/sub-1/resourcegroups/rg-1/vm-1"
    _publish_connection_rows(
        conn_root,
        [
            _os_row(
                resource_id=resource_id,
                machine_name="vm-1",
                observed_at="2026-08-31T10:00:00Z",
            )
        ],
    )
    combined_root = tmp_path / "combined"
    combined_manifest = publish_combined_inventory_snapshot(
        {"conn-a": conn_root},
        combined_root,
    )

    store = DatasetStore(combined_root)
    store.publish(
        {
            "inventory/os_observations": [],
            "inventory/source_status": [],
            "inventory/software_observations": [],
            "inventory/software_source_status": [],
            "inventory/resource_observations": [],
        },
        {},
        {
            "runId": "unrelated-empty-publication",
            "status": "completed",
            "startedAt": "2026-08-31T11:00:00Z",
        },
        ontology={},
    )

    assert store.read_dataset("inventory/os_observations") == []
    datasets, manifest = _load_combined_inventory_generation(
        store,
        source_run_id=str(combined_manifest["runId"]),
    )

    assert manifest["runId"] == combined_manifest["runId"]
    assert [row["resource_id"] for row in datasets["inventory/os_observations"]] == [
        resource_id
    ]


def test_republish_rejects_generation_that_does_not_match_manifest(
    tmp_path: Path,
) -> None:
    from intelligence.inventory.combine import _load_combined_inventory_generation

    conn_root = tmp_path / "conn-a"
    _publish_connection_rows(
        conn_root,
        [
            _os_row(
                resource_id="/subscriptions/sub-1/resourcegroups/rg-1/vm-1",
                machine_name="vm-1",
                observed_at="2026-08-31T10:00:00Z",
            )
        ],
    )
    combined_root = tmp_path / "combined"
    manifest = publish_combined_inventory_snapshot(
        {"conn-a": conn_root},
        combined_root,
    )
    store = DatasetStore(combined_root)
    generation = Path(store.generation_path(str(manifest["runId"])) or "")
    (generation / "inventory" / "os_observations.jsonl").unlink()

    with pytest.raises(RuntimeError, match="does not match its manifest"):
        _load_combined_inventory_generation(
            store,
            source_run_id=str(manifest["runId"]),
        )


def test_combine_pins_each_connection_generation_when_pointer_moves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import intelligence.inventory.combine as combine_module

    conn_root = tmp_path / "conn-a"
    resource_id = "/subscriptions/sub-1/resourcegroups/rg-1/vm-1"
    _publish_connection_rows(
        conn_root,
        [
            _os_row(
                resource_id=resource_id,
                machine_name="vm-1",
                observed_at="2026-08-31T10:00:00Z",
            )
        ],
    )
    original_read_manifest = combine_module._read_manifest
    pointer_moved = False

    def read_manifest_then_move_pointer(store, *, generation=None):
        nonlocal pointer_moved
        manifest = original_read_manifest(store, generation=generation)
        if not pointer_moved:
            pointer_moved = True
            store.publish(
                {
                    "inventory/os_observations": [],
                    "inventory/source_status": [],
                    "inventory/software_observations": [],
                    "inventory/software_source_status": [],
                    "inventory/resource_observations": [],
                },
                {},
                {
                    "runId": "newer-empty-connection-run",
                    "status": "completed",
                    "startedAt": "2026-08-31T11:00:00Z",
                },
                ontology={},
            )
        return manifest

    monkeypatch.setattr(
        combine_module, "_read_manifest", read_manifest_then_move_pointer
    )

    publish_combined_inventory_snapshot(
        {"conn-a": conn_root},
        tmp_path / "combined",
    )

    rows = DatasetStore(tmp_path / "combined").read_dataset("inventory/os_observations")
    assert [row["resource_id"] for row in rows] == [resource_id]
