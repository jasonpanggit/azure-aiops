"""Tests for multi-connection inventory refresh orchestration.

Confirms that ``run_inventory_refresh_all_connections`` fans out over every
active ``SubscriptionConnection`` in the onboarding registry (rather than a
single static config), isolates one connection's acquisition failure from the
others, and merges all successful connections' inventory datasets into one
combined snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from onboarding.credentials import CredentialResolver, EnvironmentSecretProvider
from onboarding.registry import ConnectionRegistry
from onboarding.service import SubscriptionOnboardingService
from onboarding.sync import ConnectionSyncCoordinator
from storage.locking import LeaseLostError

TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT = "33333333-3333-3333-3333-333333333333"
SUB_A = "aaaaaaaa-1111-1111-1111-111111111111"
SUB_B = "bbbbbbbb-2222-2222-2222-222222222222"


class FakeIngestion:
    def run(self):  # pragma: no cover - not exercised, sync_coordinator required
        return {}


def _build_registry(tmp_path: Path) -> None:
    resolver = CredentialResolver(
        provider=EnvironmentSecretProvider(env={"SPN_SECRET": "s3cret"}),
        credential_factory=lambda **kwargs: object(),
    )
    coordinator = ConnectionSyncCoordinator(
        tmp_path,
        ingestion_factory=lambda connection: FakeIngestion(),
    )
    service = SubscriptionOnboardingService(
        tmp_path,
        registry=ConnectionRegistry(tmp_path),
        resolver=resolver,
        sync_coordinator=coordinator,
    )
    service.add(
        connection_id="conn-a",
        tenant_id=TENANT,
        subscription_id=SUB_A,
        client_id=CLIENT,
        secret_ref="env://SPN_SECRET",
    )
    service.add(
        connection_id="conn-b",
        tenant_id=TENANT,
        subscription_id=SUB_B,
        client_id=CLIENT,
        secret_ref="env://SPN_SECRET",
    )


class FakePipeline:
    def __init__(
        self,
        root: Path,
        rows: list[dict[str, Any]],
        *,
        fail: bool = False,
        resource_rows: list[dict[str, Any]] | None = None,
        entity_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        from storage.datasets import DatasetStore

        self.store = DatasetStore(root)
        self._rows = rows
        self._fail = fail
        self._resource_rows = resource_rows or []
        self._entity_rows = entity_rows

    def refresh(self):
        if self._fail:
            raise RuntimeError("acquisition boom")
        from dataclasses import dataclass

        entities = (
            {"entities/Resource": self._entity_rows}
            if self._entity_rows is not None
            else {}
        )
        manifest = self.store.publish(
            {
                **entities,
                "inventory/os_observations": self._rows,
                "inventory/source_status": [
                    {"source_type": "azure_vm", "state": "ready"}
                ],
                "inventory/software_observations": [],
                "inventory/software_source_status": [{"state": "ready"}],
                "inventory/resource_observations": self._resource_rows,
            },
            {},
            {
                "runId": "run-1",
                "status": "completed",
                "startedAt": "2026-01-01T00:00:00Z",
            },
            ontology={},
        )

        @dataclass
        class Result:
            manifest: dict[str, Any]

        return Result(manifest=manifest)


def test_refresh_stops_before_combined_promotion_when_outer_lease_is_lost(tmp_path, monkeypatch):
    from api.inventory_orchestration import run_inventory_refresh_all_connections
    from storage.datasets import DatasetStore

    _build_registry(tmp_path)
    combined_root = tmp_path / "compat"
    store = DatasetStore(combined_root)
    store.publish({"inventory/os_observations": [{"resource_id": "last-good"}]}, {}, {"runId": "old"})
    generation = store.current_generation()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"storage:\n  output_dir: {combined_root}\n")
    lost = False

    class LosingPipeline(FakePipeline):
        def refresh(self):
            nonlocal lost
            result = super().refresh()
            lost = True
            return result

    def build(config, connection, resolver=None):
        return LosingPipeline(
            tmp_path / "connections" / connection.connection_id,
            [{"resource_id": connection.connection_id}],
        )

    def assert_held():
        if lost:
            raise LeaseLostError("outer_lease_lost")

    monkeypatch.setattr("onboarding.runtime.build_connection_inventory_pipeline", build)
    with pytest.raises(LeaseLostError, match="outer_lease_lost"):
        run_inventory_refresh_all_connections(
            str(config_path), registry_root=str(tmp_path), assert_lock_held=assert_held,
        )
    assert store.current_generation() == generation
    assert store.read_dataset("inventory/os_observations") == [{"resource_id": "last-good"}]


@pytest.mark.parametrize("require_all_connections", [False, True])
def test_refresh_all_connections_merges_successful_connections_and_isolates_failure(
    tmp_path: Path, monkeypatch, require_all_connections: bool
) -> None:
    from api.inventory_orchestration import (
        run_inventory_refresh_all_connections,
    )
    from onboarding.config import ConnectorConfig

    _build_registry(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"storage:\n  output_dir: {tmp_path / 'compat'}\n", encoding="utf-8"
    )
    pipelines: dict[str, FakePipeline] = {
        "conn-a": FakePipeline(
            tmp_path / "connections" / "conn-a",
            [{"resource_id": "/subscriptions/aaa/vm1", "connection_id": "conn-a"}],
            resource_rows=[
                {
                    "resource_id": "/subscriptions/aaa/sites/app1",
                    "connection_id": "conn-a",
                    "family": "paas",
                    "resource_type": "microsoft.web/sites",
                }
            ],
        ),
        "conn-b": FakePipeline(
            tmp_path / "connections" / "conn-b",
            [],
            fail=True,
        ),
    }

    def fake_build(config: ConnectorConfig, connection, resolver=None):
        return pipelines[connection.connection_id]

    monkeypatch.setattr(
        "onboarding.runtime.build_connection_inventory_pipeline", fake_build
    )

    result = run_inventory_refresh_all_connections(
        str(config_path), registry_root=str(tmp_path),
        require_all_connections=require_all_connections,
    )

    assert result["status"] == "partial"
    assert result["connections"]["conn-a"]["status"] == "completed"
    assert result["connections"]["conn-b"]["status"] == "failed"
    assert "acquisition boom" in result["connections"]["conn-b"]["error"]
    if require_all_connections:
        assert not (tmp_path / "compat" / "current").exists()
        assert "combined_manifest" not in result
        assert "fabric_publication" not in result
        return

    from storage.datasets import DatasetStore

    combined_store = DatasetStore(tmp_path / "compat")
    combined_os = combined_store.read_dataset("inventory/os_observations")
    assert [row["resource_id"] for row in combined_os] == ["/subscriptions/aaa/vm1"]
    combined_resources = combined_store.read_dataset("inventory/resource_observations")
    assert [row["resource_id"] for row in combined_resources] == [
        "/subscriptions/aaa/sites/app1"
    ]
    assert result["combined_manifest"]["sourceConnectionIds"] == ["conn-a"]


def test_refresh_all_connections_preserves_remote_store_uri(
    tmp_path: Path, monkeypatch
) -> None:
    from api.inventory_orchestration import run_inventory_refresh_all_connections
    from onboarding.config import ConnectorConfig

    _build_registry(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"storage:\n  output_dir: {tmp_path / 'compat'}\n",
        encoding="utf-8",
    )
    pipelines = {
        connection_id: FakePipeline(
            tmp_path / "connections" / connection_id,
            [{"resource_id": f"/subscriptions/{connection_id}/vm1"}],
        )
        for connection_id in ("conn-a", "conn-b")
    }
    expected_roots = {
        connection_id: f"abfss://workspace@onelake.dfs.fabric.microsoft.com/lakehouse/Files/aiops/connections/{connection_id}"
        for connection_id in pipelines
    }
    for connection_id, pipeline in pipelines.items():
        pipeline.store.uri_root = expected_roots[connection_id]
    captured_roots: dict[str, str | Path] = {}

    def fake_build(config: ConnectorConfig, connection, resolver=None):
        return pipelines[connection.connection_id]

    def fake_combine(connection_output_dirs, _target_root, *, connection_ids=None, assert_lock_held=None):
        assert_lock_held()
        captured_roots.update(connection_output_dirs)
        return {
            "runId": "combined-run",
            "sourceConnectionIds": sorted(connection_ids or []),
        }

    monkeypatch.setattr(
        "onboarding.runtime.build_connection_inventory_pipeline",
        fake_build,
    )
    monkeypatch.setattr(
        "intelligence.inventory.combine.publish_combined_inventory_snapshot",
        fake_combine,
    )

    result = run_inventory_refresh_all_connections(
        str(config_path),
        registry_root=str(tmp_path),
    )

    assert result["status"] == "completed"
    assert captured_roots == expected_roots


def test_refresh_rejects_registry_changes_after_discovery(tmp_path: Path) -> None:
    from api.inventory_orchestration import run_inventory_refresh_all_connections

    _build_registry(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"storage:\n  output_dir: {tmp_path / 'compat'}\n")
    with pytest.raises(RuntimeError, match="Registered connections changed"):
        run_inventory_refresh_all_connections(
            str(config_path),
            registry_root=str(tmp_path),
            discovery_output_dirs={"conn-a": str(tmp_path / "discovery")},
        )
    assert not (tmp_path / "compat" / "current").exists()


@pytest.mark.parametrize("separate_discovery", [False, True])
@pytest.mark.parametrize("exposure_enabled", [False, True])
def test_refresh_all_connections_publishes_fabric_from_resolved_generation(
    tmp_path: Path, monkeypatch, separate_discovery: bool, exposure_enabled: bool
) -> None:
    from api.inventory_orchestration import (
        run_inventory_refresh_all_connections,
    )
    from onboarding.config import ConnectorConfig
    from storage.datasets import DatasetStore

    _build_registry(tmp_path)
    DatasetStore(tmp_path / "compat").publish(
        {
            "exposure/workload_source_checkpoints": [
                {
                    "checkpoint_key": f"old-system-{index}",
                    "tenant_id": "system",
                    "connection_id": "conn-a",
                    "effective_generation": "historical",
                }
                for index in range(9)
            ],
        },
        {},
        {"runId": "historical", "status": "completed"},
        ontology={},
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"storage:\n  output_dir: {tmp_path / 'compat'}\n", encoding="utf-8"
    )
    pipelines: dict[str, FakePipeline] = {
        "conn-a": FakePipeline(
            tmp_path / "connections" / "conn-a",
            [{"resource_id": "/subscriptions/aaa/vm1", "connection_id": "conn-a"}],
            entity_rows=[{"id": "/subscriptions/aaa/vm1", "connection_id": "conn-a"}],
        ),
        "conn-b": FakePipeline(
            tmp_path / "connections" / "conn-b",
            [{"resource_id": "/subscriptions/bbb/vm2", "connection_id": "conn-b"}],
            entity_rows=[{"id": "/subscriptions/bbb/vm2", "connection_id": "conn-b"}],
        ),
    }
    discovery_roots = {}
    if separate_discovery:
        for connection_id, pipeline in pipelines.items():
            discovery_root = tmp_path / "full-discovery" / connection_id
            DatasetStore(discovery_root).publish(
                {
                    "entities/Resource": pipeline._entity_rows,
                    "exposure/workload_source_checkpoints": [
                        {
                            "checkpoint_key": f"fresh-{connection_id}-{index}",
                            "tenant_id": TENANT,
                            "connection_id": connection_id,
                            "effective_generation": "discovery",
                            "status": "healthy-empty",
                            "row_count": 0,
                            "carried_forward": False,
                        }
                        for index in range(6)
                    ],
                },
                {},
                {"runId": "discovery", "status": "completed"},
                ontology={},
            )
            pipeline._entity_rows = None
            discovery_roots[connection_id] = str(discovery_root)
    calls: list[Path | str] = []
    replay_calls: list[str] = []
    scope_calls: list[dict[str, list[str]] | None] = []
    pointer_stores: list[Any] = []

    def fake_build(config: ConnectorConfig, connection, resolver=None):
        return pipelines[connection.connection_id]

    class FakeRuntime:
        def __init__(self, source_root: Path) -> None:
            self.source_root = source_root
            self.service = self

        def sync(
            self, *, replay_source_run_id="", requested_scope=None,
            exposure_pointer_store=None,
        ):
            calls.append(self.source_root)
            replay_calls.append(replay_source_run_id)
            scope_calls.append(requested_scope)
            pointer_stores.append(exposure_pointer_store)
            return type(
                "Publication",
                (),
                {
                    "run_id": "fabric-run",
                    "source_run_id": "combined-run",
                    "status": "completed",
                    "tables": ("metadata_source_status",),
                },
            )()

    @dataclass(frozen=True)
    class FabricConfig:
        source_data_root: Path

        @property
        def exposure(self):
            from fabric.config import ExposureRuntimeConfig

            return ExposureRuntimeConfig(enabled=exposure_enabled)

    monkeypatch.setattr(
        "onboarding.runtime.build_connection_inventory_pipeline", fake_build
    )

    def fake_republish(root, *_args, **_kwargs):
        DatasetStore(root).publish(
            {
                "inventory/os_observations": [],
                "inventory/source_status": [],
                "inventory/software_observations": [],
                "inventory/software_source_status": [],
                "inventory/resource_observations": [],
            },
            {},
            {
                "runId": "concurrent-empty-publication",
                "status": "completed",
                "startedAt": "2026-01-01T00:00:01Z",
            },
            ontology={},
        )
        return {"status": "published"}

    monkeypatch.setattr(
        "intelligence.inventory.combine.republish_combined_snapshot_to_fabric",
        fake_republish,
    )
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        lambda _path: FabricConfig(source_data_root=tmp_path / "stale-current-alias"),
    )
    monkeypatch.setattr(
        "fabric.runtime.build_runtime",
        lambda config, *, mode: FakeRuntime(config.source_data_root),
    )

    result = run_inventory_refresh_all_connections(
        str(config_path),
        fabric_config_path="fabric.yaml",
        registry_root=str(tmp_path),
        discovery_output_dirs=discovery_roots or None,
    )

    assert result["fabric_publication"]["fabricTables"] == ["metadata_source_status"]
    assert calls == [tmp_path / "compat"]
    # The full sync must replay the entities-aware generation, never the
    # inventory-only combined manifest: its empty `entities/*` projection
    # would overwrite every bronze/silver/ontology table with zero rows.
    entities_run_id = str(result["entities_manifest"]["runId"])
    assert entities_run_id != result["combined_manifest"]["runId"]
    assert replay_calls == [entities_run_id]
    assert scope_calls == [{"subscription": [SUB_A, SUB_B]}]
    assert len(pointer_stores) == 1
    if exposure_enabled:
        from storage.onelake_documents import OneLakeDocumentStore

        assert isinstance(pointer_stores[0], OneLakeDocumentStore)
        pointer_stores[0].write(
            "publication-probe.json", {"status": "verified"}, expected_revision=0,
        )
        assert (tmp_path / "compat" / "publication-probe.json").is_file()
    else:
        assert pointer_stores == [None]
    store = DatasetStore(tmp_path / "compat")
    expected_generation = Path(store.generation_path(entities_run_id) or "")
    assert (expected_generation / "manifest.json").is_file()
    replayed = store.read_datasets(
        ["entities/Resource", "inventory/os_observations"],
        generation=expected_generation,
    )
    assert sorted(row["id"] for row in replayed["entities/Resource"]) == [
        "/subscriptions/aaa/vm1",
        "/subscriptions/bbb/vm2",
    ]
    assert sorted(
        row["resource_id"] for row in replayed["inventory/os_observations"]
    ) == ["/subscriptions/aaa/vm1", "/subscriptions/bbb/vm2"]
    if separate_discovery:
        checkpoints = store.read_dataset("exposure/workload_source_checkpoints")
        assert len(checkpoints) == 12
        assert {row["tenant_id"] for row in checkpoints} == {TENANT}
        assert {row["effective_generation"] for row in checkpoints} == {"discovery"}
        assert all(
            row["status"] == "healthy-empty"
            and row["row_count"] == 0
            and row["carried_forward"] is False
            for row in checkpoints
        )
