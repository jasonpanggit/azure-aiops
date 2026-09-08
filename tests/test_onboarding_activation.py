from __future__ import annotations

from dataclasses import dataclass

import pytest

from onboarding.activation import publish_combined_snapshot
from onboarding.graph_normalize import ENTITY_TYPES, NormalizedGraph
from storage.datasets import DatasetStore


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
    graph = NormalizedGraph(entities=entities)
    DatasetStore(root).publish(
        {
            **{
                f"entities/{entity_type}": rows
                for entity_type, rows in graph.entities.items()
            },
            "relationships/relationships": [],
            "changes/resource_changes": [],
            "exposure/workload_observations": [
                {
                    "observation_id": f"observation-{connection_id}",
                    "connection_id": connection_id,
                }
            ],
            "exposure/workload_deployments": [
                {
                    "deployment_id": f"deployment-{connection_id}",
                    "connection_id": connection_id,
                    "workspace_id": f"workspace-{connection_id}",
                }
            ],
            "exposure/workload_source_checkpoints": [
                {
                    "checkpoint_key": f"checkpoint-{connection_id}",
                    "connection_id": connection_id,
                    "workspace_id": f"workspace-{connection_id}",
                }
            ],
            "situations/source_status": [
                {
                    "partition_key": f"partition-{connection_id}",
                    "connection_id": connection_id,
                    "source_family": "defender_image",
                    "attempted_generation": f"attempt-{connection_id}",
                    "effective_generation": f"effective-{connection_id}",
                    "attempted_at": "2026-01-01T00:00:00Z",
                    "last_success_at": "2026-01-01T00:00:00Z",
                    "row_count": 0,
                    "represented_count": 1,
                    "expected_count": 1,
                    "completeness": "complete",
                    "safe_error_code": "",
                    "safe_error_summary": "",
                }
            ],
        },
        {},
        {
            "runId": f"run-{connection_id}",
            "status": "completed",
            "startedAt": "2026-01-01T00:00:00Z",
            "completedAt": "2026-01-01T00:01:00Z",
        },
        ontology={},
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
    combined = DatasetStore(tmp_path / "combined")
    assert {
        row["deployment_id"]
        for row in combined.read_dataset("exposure/workload_deployments")
    } == {"deployment-hub", "deployment-spoke"}
    assert {
        row["checkpoint_key"]
        for row in combined.read_dataset(
            "exposure/workload_source_checkpoints"
        )
    } == {"checkpoint-hub", "checkpoint-spoke"}
    assert {
        row["partition_key"]
        for row in combined.read_dataset("situations/source_status")
    } == {"partition-hub", "partition-spoke"}


def test_combined_snapshot_rejects_cross_connection_identity_collision(tmp_path):
    roots = {"hub": tmp_path / "hub", "spoke": tmp_path / "spoke"}
    shared_id = "/subscriptions/shared/resourceGroups/rg/providers/x/a"
    _publish(roots["hub"], "hub", shared_id)
    _publish(roots["spoke"], "spoke", shared_id)

    with pytest.raises(ValueError, match="identity collision across connections"):
        publish_combined_snapshot(
            _Service(roots), ["hub", "spoke"], tmp_path / "combined"
        )
