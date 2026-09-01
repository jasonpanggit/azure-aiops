from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onboarding.sync import ConnectionSyncCoordinator, SyncResult
from ontology.subscription_connection import SubscriptionConnection


def _connection() -> SubscriptionConnection:
    return SubscriptionConnection(
        connection_id="conn-1",
        name="Connection One",
        tenant_id="tenant-1",
        subscription_id="sub-1",
    )


class _FakeIngestion:
    def __init__(self, manifest: dict) -> None:
        self.manifest = manifest

    def run(self):
        return self.manifest


def _coordinator(tmp_path: Path, manifest: dict) -> ConnectionSyncCoordinator:
    return ConnectionSyncCoordinator(
        str(tmp_path),
        ingestion_factory=lambda _connection: _FakeIngestion(manifest),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_discovery_metrics_is_none_by_default(tmp_path: Path) -> None:
    manifest = {"queryVersion": "1.0.0", "datasets": {"entities/resource": {"rowCount": 3}}}
    coordinator = _coordinator(tmp_path, manifest)

    result, _state = coordinator.run(_connection(), mode="initial")

    assert isinstance(result, SyncResult)
    assert result.discovery_metrics is None
    assert result.to_dict()["discovery_metrics"] is None


def test_discovery_metrics_is_populated_from_manifest_sub_dict(tmp_path: Path) -> None:
    metrics = {
        "entities_added": 5,
        "relationships_added": 3,
        "dangling_relationships": 1,
        "confidence_distribution": {"0.9-1.0": 3},
    }
    manifest = {
        "queryVersion": "1.0.0",
        "datasets": {"entities/resource": {"rowCount": 3}},
        "discovery_metrics": metrics,
    }
    coordinator = _coordinator(tmp_path, manifest)

    result, _state = coordinator.run(_connection(), mode="initial")

    assert result.discovery_metrics == metrics
    assert result.to_dict()["discovery_metrics"] == metrics


def test_discovery_metrics_is_populated_from_ontology_report_key(tmp_path: Path) -> None:
    metrics = {"entities_added": 1, "relationships_added": 0, "dangling_relationships": 0}
    manifest = {
        "queryVersion": "1.0.0",
        "datasets": {"entities/resource": {"rowCount": 1}},
        "ontology_report": metrics,
    }
    coordinator = _coordinator(tmp_path, manifest)

    result, _state = coordinator.run(_connection(), mode="initial")

    assert result.discovery_metrics == metrics


def test_discovery_metrics_ignores_non_dict_or_empty_sub_dict(tmp_path: Path) -> None:
    manifest = {
        "queryVersion": "1.0.0",
        "datasets": {"entities/resource": {"rowCount": 1}},
        "discovery_metrics": {},
    }
    coordinator = _coordinator(tmp_path, manifest)

    result, _state = coordinator.run(_connection(), mode="initial")

    assert result.discovery_metrics is None
