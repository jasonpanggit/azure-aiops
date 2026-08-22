from __future__ import annotations

from dataclasses import dataclass

import pytest

from hermes_arg_connector.normalize import ENTITY_TYPES, NormalizedGraph
from hermes_arg_connector.storage import DatasetStore
from onboarding.activation import publish_combined_snapshot


@dataclass(frozen=True)
class _Connection:
    connection_id: str


class _Registry:
    def get(self, connection_id: str) -> _Connection:
        return _Connection(connection_id)


class _Coordinator:
    def __init__(self, roots):
        self.roots = roots

    def connection_output_dir(self, connection: _Connection):
        return self.roots[connection.connection_id]


class _Service:
    def __init__(self, roots):
        self.registry = _Registry()
        self.sync_coordinator = _Coordinator(roots)


def _publish(root, connection_id: str, resource_id: str) -> None:
    entities = {name: [] for name in ENTITY_TYPES}
    entities["Resource"] = [
        {
            "id": resource_id,
            "name": resource_id,
            "entityType": "Resource",
            "connection_id": connection_id,
        }
    ]
    DatasetStore(root).publish(
        NormalizedGraph(entities=entities),
        {},
        {
            "runId": f"run-{connection_id}",
            "status": "completed",
            "startedAt": "2026-01-01T00:00:00Z",
            "completedAt": "2026-01-01T00:01:00Z",
        },
    )


def test_combined_snapshot_preserves_distinct_connection_entities(tmp_path):
    roots = {"hub": tmp_path / "hub", "spoke": tmp_path / "spoke"}
    _publish(roots["hub"], "hub", "/subscriptions/hub/resourceGroups/rg/providers/x/a")
    _publish(
        roots["spoke"],
        "spoke",
        "/subscriptions/spoke/resourceGroups/rg/providers/x/b",
    )

    publish_combined_snapshot(_Service(roots), ["hub", "spoke"], tmp_path / "combined")

    rows = DatasetStore(tmp_path / "combined").read_dataset("entities/Resource")
    assert {(row["id"], row["connection_id"]) for row in rows} == {
        ("/subscriptions/hub/resourceGroups/rg/providers/x/a", "hub"),
        ("/subscriptions/spoke/resourceGroups/rg/providers/x/b", "spoke"),
    }


def test_combined_snapshot_rejects_cross_connection_identity_collision(tmp_path):
    roots = {"hub": tmp_path / "hub", "spoke": tmp_path / "spoke"}
    shared_id = "/subscriptions/shared/resourceGroups/rg/providers/x/a"
    _publish(roots["hub"], "hub", shared_id)
    _publish(roots["spoke"], "spoke", shared_id)

    with pytest.raises(ValueError, match="identity collision across connections"):
        publish_combined_snapshot(
            _Service(roots), ["hub", "spoke"], tmp_path / "combined"
        )
