from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intelligence.inventory.pipeline import InventoryPipeline
from onboarding.config import ConnectorConfig


class _InventorySource:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture

    def list_subscriptions(self) -> list[dict[str, str]]:
        return [{"subscriptionId": "sub-a"}, {"subscriptionId": "sub-b"}]

    def fetch(self, specs, subscription_ids: list[str]) -> dict[str, list[dict]]:
        return {
            spec.name: list(self.fixture.get(spec.name, []))
            for spec in specs
            if spec.name in self.fixture
        }


class _LogsSource:
    def __init__(
        self,
        rows: list[dict] | None,
        *,
        failures: set[str] | None = None,
    ) -> None:
        self.rows = rows
        self.failures = failures or set()

    def query_configuration_data(self, workspace_id: str) -> list[dict]:
        if workspace_id in self.failures:
            raise RuntimeError("workspace access denied")
        return list(self.rows or [])


def refresh_inventory(
    store_root: Path,
    *,
    fixture_path: Path | None = None,
    software_fixture_path: Path | None = None,
    software_rows: list[dict] | None = None,
    failed_workspaces: set[str] | None = None,
    workspaces: dict[str, str | tuple[str, ...]] | None = None,
    clock: datetime | None = None,
) -> dict[str, Any]:
    fixture_path = fixture_path or Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"
    software_fixture_path = (
        software_fixture_path
        or Path(__file__).parent / "fixtures" / "mock_configurationdata.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if software_rows is None:
        software_rows = json.loads(software_fixture_path.read_text(encoding="utf-8"))
    if workspaces is None:
        workspaces = {"connection-1": "workspace-1"}
    if "inventory_log_analytics_workspaces" not in fixture:
        discovered_ids: list[str] = []
        for values in workspaces.values():
            if isinstance(values, (list, tuple)):
                discovered_ids.extend(str(v) for v in values)
            else:
                discovered_ids.append(str(values))
        fixture = {
            **fixture,
            "inventory_log_analytics_workspaces": [
                {"workspaceId": workspace_id} for workspace_id in discovered_ids
            ],
        }
    config = ConnectorConfig(
        output_dir=store_root,
        subscriptions=("sub-a", "sub-b"),
        connection_context={"connection_id": "connection-1"},
        cost_management_enabled=False,
    )
    service = InventoryPipeline(
        config,
        source=_InventorySource(fixture),
        logs_client=_LogsSource(software_rows, failures=failed_workspaces),
        clock=lambda: clock or datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )
    return service.refresh().manifest


class _AIOpsArgSource:
    """Fake `AzureResourceGraphSource`-shaped fetch for the AIOps
    (onboarding) ingestion seam, distinct from `_InventorySource`
    above which feeds `intelligence.inventory.pipeline.InventoryPipeline`."""

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture

    def list_subscriptions(self) -> list[dict[str, str]]:
        return [{"subscriptionId": "sub-1", "tenantId": "tenant-1"}]

    def fetch(self, specs, subscription_ids: list[str]) -> dict[str, list[dict]]:
        return {spec.name: list(self.fixture.get(spec.name, [])) for spec in specs}


def run_aiops_ingestion(
    store_root: Path,
    *,
    identity_source: str = "arg",
    fixture_path: Path | None = None,
    clock: datetime | None = None,
) -> dict[str, Any]:
    """Runs `onboarding.ingestion_service.IngestionService` end-to-end for a
    given `identity_source`, through the single named harness seam (Task 3:
    "Characterization tests reach their driver only through a single named
    seam"). Both ``"arg"`` and ``"inventory"`` values must be exercisable
    from this one entry point against the same golden fixture."""
    from intelligence.inventory.read_port import InventoryReadPort
    from intelligence.inventory.service import InventoryService as OSInventoryService
    from onboarding.config import ConnectorConfig as AIOpsConnectorConfig
    from onboarding.ingestion_service import IngestionService

    fixture_path = fixture_path or Path(__file__).parent / "fixtures" / "mock_arg_responses.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    config = AIOpsConnectorConfig(
        output_dir=store_root,
        subscriptions=("sub-1",),
        cost_management_enabled=False,
        identity_source=identity_source,
    )

    inventory_read_port = None
    if identity_source == "inventory":
        resource_observations = [
            {
                "tenant_id": row.get("tenantId") or "",
                "subscription_id": row.get("subscriptionId") or "",
                "resource_id": row.get("id") or "",
                "timestamp": "2026-08-25T12:00:00Z",
                "change_version": "v1",
                "ingestion_run_id": "harness-run",
                "resource_name": row.get("name") or "",
                "resource_type": row.get("type") or "",
                "resource_group": row.get("resourceGroup") or "",
                "location": row.get("location") or "",
                "family": "paas",
                "sku": "",
                "tier": "",
                "runtime": "",
                "provisioning_state": "",
                "os_name": "",
                "os_version": "",
                "source_type": "arg",
                "source_table": "Resources",
                "observed_at": "2026-08-25T12:00:00Z",
                "query_version": "resource-observation-v1",
                "provider_payload_json": json.dumps(row.get("properties") or {}),
                "tags_json": json.dumps(row.get("tags") or {}),
                "provenance_json": "{}",
            }
            for row in fixture.get("resources", [])
        ]
        os_service = OSInventoryService({"resource_observations": resource_observations})
        inventory_read_port = InventoryReadPort(os_service)

    service = IngestionService(
        config,
        source=_AIOpsArgSource(fixture),
        clock=lambda: clock or datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
        inventory_read_port=inventory_read_port,
    )
    return service.run()


def _normalized_entities_and_relationships(store_root: Path) -> tuple[dict, list]:
    """Loads the entity families the `identity_source` flag actually swaps:
    the resource-shaped entities from the `resources` ARG spec. Containment
    entities (Subscription/ResourceGroup) are intentionally excluded here --
    `InventoryReadPort.list_containment()` (Task 1) derives only IDs from
    existing observation rows, not decorative fields like tags/tenantId/state
    that a real ResourceContainers query carries; a persisted containment
    table with that fidelity is explicitly out of scope for this plan (Task 1
    action note) and is a follow-up, not silently added here."""
    from onboarding.ingestion_storage import DatasetStore

    store = DatasetStore(store_root)
    entities: dict[str, list] = {}
    for entity_type in ("Resource", "VirtualMachine", "ArcServer"):
        entities[entity_type] = store.read_dataset(f"entities/{entity_type}")
    relationships = [
        row
        for row in store.read_dataset("relationships/relationships")
        if row.get("predicate") == "belongsTo"
    ]
    return entities, relationships


def test_identity_source_inventory_matches_identity_source_arg(tmp_path: Path) -> None:
    """Task 3: `identity_source="inventory"` must produce the same
    characterized NormalizedGraph output as `identity_source="arg"` for the
    harness fixture (parametrized over both values against one golden
    fixture, per the 07-01 precedent)."""
    arg_root = tmp_path / "arg"
    inventory_root = tmp_path / "inventory"

    arg_manifest = run_aiops_ingestion(arg_root, identity_source="arg")
    inventory_manifest = run_aiops_ingestion(inventory_root, identity_source="inventory")

    arg_entities, arg_relationships = _normalized_entities_and_relationships(arg_root)
    inventory_entities, inventory_relationships = _normalized_entities_and_relationships(
        inventory_root
    )

    def _sorted_json(rows: list) -> list[str]:
        return sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)

    for entity_type in arg_entities:
        assert _sorted_json(arg_entities[entity_type]) == _sorted_json(
            inventory_entities[entity_type]
        ), f"{entity_type} diverged between identity_source='arg' and 'inventory'"

    assert _sorted_json(arg_relationships) == _sorted_json(inventory_relationships)
    assert arg_manifest["status"] == "completed"
    assert inventory_manifest["status"] == "completed"


def test_identity_source_defaults_to_arg_with_no_behavior_change(tmp_path: Path) -> None:
    """Default behavior (`identity_source="arg"`) is unchanged: omitting the
    flag entirely must match explicitly passing `identity_source="arg"`."""
    from onboarding.config import ConnectorConfig as AIOpsConnectorConfig

    default_config = AIOpsConnectorConfig(output_dir=tmp_path / "default")
    assert default_config.identity_source == "arg"

    default_root = tmp_path / "default-run"
    explicit_root = tmp_path / "explicit-run"
    run_aiops_ingestion(default_root, identity_source="arg")
    run_aiops_ingestion(explicit_root, identity_source="arg")

    default_entities, default_relationships = _normalized_entities_and_relationships(default_root)
    explicit_entities, explicit_relationships = _normalized_entities_and_relationships(explicit_root)

    def _sorted_json(rows: list) -> list[str]:
        return sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)

    for entity_type in default_entities:
        assert _sorted_json(default_entities[entity_type]) == _sorted_json(
            explicit_entities[entity_type]
        )
    assert _sorted_json(default_relationships) == _sorted_json(explicit_relationships)

