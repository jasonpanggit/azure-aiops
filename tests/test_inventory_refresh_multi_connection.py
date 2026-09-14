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

from onboarding.credentials import CredentialResolver, EnvironmentSecretProvider
from onboarding.registry import ConnectionRegistry
from onboarding.service import SubscriptionOnboardingService
from onboarding.sync import ConnectionSyncCoordinator

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
    ) -> None:
        from storage.datasets import DatasetStore

        self.store = DatasetStore(root)
        self._rows = rows
        self._fail = fail
        self._resource_rows = resource_rows or []

    def refresh(self):
        if self._fail:
            raise RuntimeError("acquisition boom")
        from dataclasses import dataclass

        manifest = self.store.publish(
            {
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


def test_refresh_all_connections_merges_successful_connections_and_isolates_failure(
    tmp_path: Path, monkeypatch
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
        str(config_path), registry_root=str(tmp_path)
    )

    assert result["status"] == "partial"
    assert result["connections"]["conn-a"]["status"] == "completed"
    assert result["connections"]["conn-b"]["status"] == "failed"
    assert "acquisition boom" in result["connections"]["conn-b"]["error"]

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

    def fake_combine(connection_output_dirs, _target_root, *, connection_ids=None):
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


class FakeDiscoveryIngestion:
    """Writes a minimal ``entities/*.jsonl`` discovery generation.

    Mirrors the real per-connection discovery ingestion
    (``build_connection_ingestion``) closely enough for
    ``onboarding.activation.publish_combined_snapshot`` to find a valid
    generation to merge, without any real ARG/network dependency.
    """

    def __init__(self, root: Path, resource_id: str, connection_id: str) -> None:
        from storage.datasets import DatasetStore

        self.store = DatasetStore(root)
        self._resource_id = resource_id
        self._connection_id = connection_id

    def run(self):
        return self.store.publish(
            {
                "entities/Resource": [
                    {
                        "id": self._resource_id,
                        "resourceId": self._resource_id,
                        "connection_id": self._connection_id,
                    }
                ],
                "entities/Subscription": [],
                "entities/ResourceGroup": [],
                "entities/VirtualMachine": [],
                "entities/ArcServer": [],
                "entities/ManagementGroup": [],
                "entities/PatchAssessment": [],
                "entities/PatchAssessmentDetail": [],
                "entities/PatchInstallation": [],
                "entities/AdvisorRecommendation": [],
                "entities/CostActual": [],
                "entities/RoleAssignment": [],
                "entities/RoleDefinition": [],
                "entities/ManagedIdentity": [],
                "entities/DefenderAssessment": [],
                "relationships/relationships": [],
                "changes/resource_changes": [],
            },
            {},
            {
                "runId": f"discovery-{self._connection_id}",
                "status": "completed",
                "startedAt": "2026-01-01T00:00:00Z",
            },
            ontology={},
        )


def test_refresh_all_connections_publishes_fabric_from_resolved_generation(
    tmp_path: Path, monkeypatch
) -> None:
    from api.inventory_orchestration import (
        run_inventory_refresh_all_connections,
    )
    from onboarding.config import ConnectorConfig
    from storage.datasets import DatasetStore

    _build_registry(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"storage:\n  output_dir: {tmp_path / 'compat'}\n", encoding="utf-8"
    )
    pipelines: dict[str, FakePipeline] = {
        "conn-a": FakePipeline(
            tmp_path / "connections" / "conn-a",
            [{"resource_id": "/subscriptions/aaa/vm1", "connection_id": "conn-a"}],
        ),
        "conn-b": FakePipeline(
            tmp_path / "connections" / "conn-b",
            [{"resource_id": "/subscriptions/bbb/vm2", "connection_id": "conn-b"}],
        ),
    }
    ingestions: dict[str, FakeDiscoveryIngestion] = {
        "conn-a": FakeDiscoveryIngestion(
            tmp_path / "compat" / "connections" / "conn-a",
            "/subscriptions/aaa/vm1",
            "conn-a",
        ),
        "conn-b": FakeDiscoveryIngestion(
            tmp_path / "compat" / "connections" / "conn-b",
            "/subscriptions/bbb/vm2",
            "conn-b",
        ),
    }
    calls: list[Path | str] = []
    replay_calls: list[str] = []
    scope_calls: list[dict[str, list[str]] | None] = []
    pointer_store_calls: list[Any] = []

    def fake_build(config: ConnectorConfig, connection, resolver=None):
        return pipelines[connection.connection_id]

    def fake_build_ingestion(config: ConnectorConfig, connection, resolver=None):
        return ingestions[connection.connection_id]

    class FakeRuntime:
        def __init__(self, source_root: Path) -> None:
            self.source_root = source_root
            self.service = self

        def sync(
            self,
            *,
            replay_source_run_id="",
            requested_scope=None,
            exposure_pointer_store=None,
        ):
            calls.append(self.source_root)
            replay_calls.append(replay_source_run_id)
            scope_calls.append(requested_scope)
            pointer_store_calls.append(exposure_pointer_store)
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

    monkeypatch.setattr(
        "onboarding.runtime.build_connection_inventory_pipeline", fake_build
    )
    monkeypatch.setattr(
        "onboarding.runtime.build_connection_ingestion", fake_build_ingestion
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
        lambda config: FakeRuntime(config.source_data_root),
    )

    result = run_inventory_refresh_all_connections(
        str(config_path),
        fabric_config_path="fabric.yaml",
        registry_root=str(tmp_path),
    )

    assert result["fabric_publication"]["fabricTables"] == ["metadata_source_status"]
    assert calls == [tmp_path / "compat"]
    assert replay_calls == [result["entities_manifest"]["runId"]]
    assert scope_calls == [{"subscription": [SUB_A, SUB_B]}]
    assert len(pointer_store_calls) == 1
    assert pointer_store_calls[0] is not None
    assert str(pointer_store_calls[0].root) == str(tmp_path)
    store = DatasetStore(tmp_path / "compat")
    expected_generation = Path(
        store.generation_path(str(result["entities_manifest"]["runId"])) or ""
    )
    assert (expected_generation / "manifest.json").is_file()
