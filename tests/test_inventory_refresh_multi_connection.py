"""Tests for multi-connection inventory refresh orchestration.

Confirms that ``run_inventory_refresh_all_connections`` fans out over every
active ``SubscriptionConnection`` in the onboarding registry (rather than a
single static config), isolates one connection's acquisition failure from the
others, and merges all successful connections' inventory datasets into one
combined snapshot.
"""

from __future__ import annotations

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
    def __init__(self, root: Path, rows: list[dict[str, Any]], *, fail: bool = False) -> None:
        from storage.datasets import DatasetStore

        self.store = DatasetStore(root)
        self._rows = rows
        self._fail = fail

    def refresh(self):
        if self._fail:
            raise RuntimeError("acquisition boom")
        from dataclasses import dataclass

        manifest = self.store.publish(
            {
                "inventory/os_observations": self._rows,
                "inventory/source_status": [{"source_type": "azure_vm", "state": "ready"}],
                "inventory/software_observations": [],
                "inventory/software_source_status": [{"state": "ready"}],
                "inventory/resource_observations": [],
            },
            {},
            {"runId": "run-1", "status": "completed", "startedAt": "2026-01-01T00:00:00Z"},
            ontology={},
        )

        @dataclass
        class Result:
            manifest: dict[str, Any]

        return Result(manifest=manifest)


def test_refresh_all_connections_merges_successful_connections_and_isolates_failure(
    tmp_path: Path, monkeypatch
) -> None:
    from hermes_arg_connector.config import ConnectorConfig
    from hermes_arg_connector.inventory_refresh import (
        run_inventory_refresh_all_connections,
    )

    _build_registry(tmp_path)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"storage:\n  output_dir: {tmp_path / 'compat'}\n", encoding="utf-8")

    pipelines: dict[str, FakePipeline] = {
        "conn-a": FakePipeline(
            tmp_path / "connections" / "conn-a",
            [{"resource_id": "/subscriptions/aaa/vm1", "connection_id": "conn-a"}],
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

    result = run_inventory_refresh_all_connections(str(config_path), registry_root=str(tmp_path))

    assert result["status"] == "partial"
    assert result["connections"]["conn-a"]["status"] == "completed"
    assert result["connections"]["conn-b"]["status"] == "failed"
    assert "acquisition boom" in result["connections"]["conn-b"]["error"]

    from storage.datasets import DatasetStore

    combined_store = DatasetStore(tmp_path / "compat")
    combined_os = combined_store.read_dataset("inventory/os_observations")
    assert [row["resource_id"] for row in combined_os] == ["/subscriptions/aaa/vm1"]
    assert result["combined_manifest"]["sourceConnectionIds"] == ["conn-a"]
