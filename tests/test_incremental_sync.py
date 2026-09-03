from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from deltalake import DeltaTable
from topology_comparison_scenario import topology_comparison_scenario

from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import InventoryDatasetMapper
from fabric.sync_service import FabricSyncService, _table_source_status_rows
from intelligence.inventory.pipeline import InventoryPipeline
from onboarding.config import ConnectorConfig
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from semantic.semantic_engine import SemanticEngine
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_writer import OneLakeWriter

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"


def _source_snapshot(root: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["cost_actuals"] = [
        {
            "subscriptionId": "sub-1",
            "usageDate": "2026-08-17",
            "cost": 42.5,
            "currency": "AUD",
            "resourceId": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod",
            "resourceGroup": "rg-prod",
            "serviceName": "Virtual Machines",
        }
    ]
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    DatasetStore(root).publish(
        graph,
        payload,
        {"runId": "source-run-1", "startedAt": "2026-08-17T00:00:00Z", "status": "completed"},
    )


def _source_snapshot_with_topology(root: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    payload.update(topology_comparison_scenario())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    DatasetStore(root).publish(
        graph,
        payload,
        {"runId": "source-run-topology", "startedAt": "2026-08-17T00:00:00Z", "status": "completed"},
    )


def _delta_rows(path: Path) -> list[dict]:
    return DeltaTable(str(path)).to_pyarrow_table().to_pylist()


def test_incremental_sync_writes_bronze_silver_ontology_and_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    onelake = OneLakeWriter("workspace", "lakehouse", local_root=lakehouse)
    service = FabricSyncService(
        source_root=source,
        onelake=onelake,
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )

    first = service.sync(requested_scope={"subscription": ["sub-1"]})
    second = service.sync(requested_scope={"subscription": ["sub-1"]})

    resources = _delta_rows(lakehouse / "Tables/bronze_resources")
    costs = _delta_rows(lakehouse / "Tables/silver_cost_actuals")
    states = _delta_rows(lakehouse / "Tables/metadata_ingestion_state")
    source_status = _delta_rows(lakehouse / "Tables/metadata_source_status")
    assert first.status == "completed"
    assert second.status == "completed"
    assert len(resources) == 3
    assert all({
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
    } <= set(row) for row in resources)
    assert {row["status"] for row in states} == {"completed"}
    assert all(row["watermark"] == "2026-08-17T00:30:00Z" for row in states)
    assert (lakehouse / "Tables/silver_vm_inventory/_delta_log").is_dir()
    assert costs[0]["cost"] == 42.5
    assert costs[0]["currency"] == "AUD"
    assert costs[0]["usage_date"] == "2026-08-17"
    source_status_by_family = {row["source_family"]: row for row in source_status}
    assert source_status_by_family["bronze_resources"]["row_count"] == 3
    assert source_status_by_family["silver_vm_inventory"]["availability"] == "available"
    assert source_status_by_family["ontology_entities"]["status"] == "succeeded"
    assert source_status_by_family["bronze_resources"]["subscription_id"] == "sub-1"
    assert json.loads(source_status_by_family["bronze_resources"]["requested_scope_json"]) == {
        "subscription": ["sub-1"]
    }
    assert source_status_by_family["bronze_container_image_exposure"]["row_count"] == 0
    assert (
        source_status_by_family["bronze_container_image_exposure"]["subscription_id"]
        == "sub-1"
    )
    assert (lakehouse / "Tables/ontology_entities/_delta_log").is_dir()
    assert (lakehouse / "Files/ontology/metadata/catalog.json").is_file()


def test_source_status_rows_preserve_each_subscription_for_empty_tables() -> None:
    rows = _table_source_status_rows(
        {
            "bronze_resources": [
                {"subscription_id": "sub-a"},
                {"subscription_id": "sub-b"},
            ],
            "silver_empty": [],
        },
        "run-1",
        "2026-08-17T00:00:00Z",
        requested_scope={"subscription": ["sub-a", "sub-b"]},
    )

    by_key = {(row["source_family"], row["subscription_id"]): row for row in rows}
    assert by_key["bronze_resources", "sub-a"]["row_count"] == 1
    assert by_key["bronze_resources", "sub-b"]["row_count"] == 1
    assert by_key["silver_empty", "sub-a"]["row_count"] == 0
    assert by_key["silver_empty", "sub-b"]["row_count"] == 0
    assert all(
        json.loads(row["requested_scope_json"]) == {"subscription": [subscription_id]}
        for (_, subscription_id), row in by_key.items()
    )


def test_sync_with_topology_flag_publishes_topology_tables(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot_with_topology(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        topology_enabled=True,
    )

    service.sync()

    topology_entities_path = lakehouse / "Tables/topology_entities"
    topology_edges_path = lakehouse / "Tables/topology_edges"
    manifest_path = lakehouse / "Tables/metadata_publication_manifest"
    assert topology_entities_path.is_dir()
    assert topology_edges_path.is_dir()
    assert DeltaTable(str(topology_entities_path)).to_pyarrow_table().num_rows > 0
    assert DeltaTable(str(topology_edges_path)).to_pyarrow_table().num_rows > 0
    manifest_rows = DeltaTable(str(manifest_path)).to_pyarrow_table().to_pylist()
    manifest_by_name = {row["projection_name"]: row["disposition"] for row in manifest_rows}
    assert manifest_by_name["topology_entities"] == "active"
    assert manifest_by_name["topology_edges"] == "active"


def test_secure_score_snapshots_remain_queryable_across_syncs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    store = DatasetStore(source)
    score_id = (
        "/subscriptions/sub-1/providers/Microsoft.Security/"
        "secureScores/ascScore"
    )

    def publish_score(run_id: str, observed_at: datetime, current: int) -> None:
        payload = json.loads(FIXTURE.read_text())
        payload["defender_secure_scores"] = [
            {
                "id": score_id,
                "name": "ascScore",
                "type": "microsoft.security/securescores",
                "tenantId": "tenant-1",
                "subscriptionId": "sub-1",
                "properties": {
                    "score": {
                        "current": current,
                        "max": 100,
                        "percentage": current / 100,
                    }
                },
            }
        ]
        graph = Normalizer().normalize(payload, observed_at)
        # Audit-event identity is intentionally immutable and tested elsewhere;
        # this regression isolates secure-score history across source runs.
        graph.audit_events = []
        store.publish(
            graph,
            payload,
            {
                "runId": run_id,
                "startedAt": observed_at.isoformat(),
                "status": "completed",
            },
        )

    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace",
            "lakehouse",
            local_root=lakehouse,
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )

    publish_score(
        "source-score-1",
        datetime(2026, 8, 17, tzinfo=UTC),
        40,
    )
    service.sync()
    publish_score(
        "source-score-2",
        datetime(2026, 8, 18, tzinfo=UTC),
        50,
    )
    service.sync()

    scores = service.defender_intelligence_snapshot()["secure_scores"]
    assert len(scores) == 2
    assert {
        json.loads(row["payload_json"])["currentScore"] for row in scores
    } == {40.0, 50.0}
    assert len({row["resource_id"] for row in scores}) == 2


def test_sync_persists_governed_patch_policies_for_runtime_intelligence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        patch_policies=(
            SimpleNamespace(
                name="Production baseline",
                environment="Production",
                max_patch_age_days=30,
                minimum_compliance_score=90,
            ),
        ),
    )

    service.sync()

    assert service.patch_intelligence_snapshot()["policies"] == [
        {
            "name": "Production baseline",
            "environment": "Production",
            "max_patch_age_days": 30,
            "minimum_compliance_score": 90,
        }
    ]


def test_sync_persists_lifecycle_catalog_as_metadata_and_ontology_entity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    entry = {
        "product": "Windows Server",
        "version": "2012 R2",
        "release_date": "2013-11-25",
        "mainstream_support_end": "2018-10-09",
        "extended_support_end": "2023-10-10",
        "last_update_date": "2026-08-18",
        "recommended_upgrade_path": "Windows Server 2025",
        "source_url": "https://learn.microsoft.com/lifecycle/products/windows-server-2012-r2",
        "notes": "",
        "default_support_channel": "mainstream",
    }
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        lifecycle_catalog=(entry,),
    )

    service.sync()

    assert service.lifecycle_intelligence_snapshot()["catalog"] == [entry]
    lifecycle_entities = [
        row
        for row in _delta_rows(lakehouse / "Tables/ontology_entities")
        if row["entity_type"] == "LifecycleProduct"
    ]
    assert lifecycle_entities[0]["name"] == "Windows Server 2012 R2"
    assert _delta_rows(lakehouse / "Tables/ontology_lifecycle_product_entities")
    history = _delta_rows(lakehouse / "Tables/silver_lifecycle_history")
    assert history
    assert {row["lifecycle_status"] for row in history} <= {
        "Supported",
        "Approaching EOL",
        "Near EOL",
        "Critical",
        "EOL",
        "Unknown",
    }


def test_same_second_syncs_preserve_one_lifecycle_observation_per_resource(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    monkeypatch.setattr(
        "fabric.sync_service._utc_now", lambda: "2026-08-18T00:00:00Z"
    )
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        lifecycle_catalog=(
            {
                "product": "Windows Server",
                "version": "2012 R2",
                "release_date": "2013-11-25",
                "mainstream_support_end": "2018-10-09",
                "extended_support_end": "2023-10-10",
                "last_update_date": "2026-08-18",
                "recommended_upgrade_path": "Windows Server 2025",
                "source_url": "https://learn.microsoft.com/lifecycle/products/windows-server-2012-r2",
            },
        ),
    )

    service.sync()
    service.sync()

    history = _delta_rows(lakehouse / "Tables/silver_lifecycle_history")
    # The fixture has 3 resources, but only the VM and the Arc server carry an OS
    # lifecycle. The storage account has no OS and is correctly excluded, so each
    # sync contributes 2 observations, not 3.
    assert len(history) == 4
    assert len({row["resource_id"] for row in history}) == 4


def test_uuid_subscription_resources_receive_lifecycle_history(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    subscription_id = "5ef7423a-80d9-4c44-ae0f-058600202e4a"
    payload = json.loads(FIXTURE.read_text().replace("sub-1", subscription_id))
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    DatasetStore(source).publish(
        graph,
        payload,
        {
            "runId": "source-run-uuid",
            "startedAt": "2026-08-17T00:00:00Z",
            "status": "completed",
        },
    )
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        lifecycle_catalog=(
            {
                "product": "Ubuntu",
                "version": "20.04 LTS",
                "release_date": "2020-04-23",
                "mainstream_support_end": "2025-05-31",
                "extended_support_end": "2030-05-31",
                "last_update_date": "2026-08-18",
                "recommended_upgrade_path": "Ubuntu 22.04 LTS",
                "source_url": "https://ubuntu.com/about/release-cycle",
            },
        ),
    )

    result = service.sync()
    history = _delta_rows(lakehouse / "Tables/silver_lifecycle_history")

    assert result.status == "completed"
    # Only the VM and Arc server have an OS lifecycle; the storage account does not.
    assert len(history) == 2
    assert all(row["subscription_id"] == subscription_id for row in history)


def test_duplicate_display_names_correlate_history_by_canonical_resource_id(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    payload = json.loads(FIXTURE.read_text())
    duplicate = dict(payload["resources"][0])
    duplicate["id"] = duplicate["id"].replace("rg-prod", "rg-secondary")
    payload["resources"].append(duplicate)
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    DatasetStore(source).publish(
        graph,
        payload,
        {
            "runId": "source-run-duplicate-name",
            "startedAt": "2026-08-17T00:00:00Z",
            "status": "completed",
        },
    )
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        lifecycle_catalog=(
            {
                "product": "Ubuntu",
                "version": "20.04 LTS",
                "release_date": "2020-04-23",
                "mainstream_support_end": "2025-05-31",
                "extended_support_end": "2030-05-31",
                "last_update_date": "2026-08-18",
                "recommended_upgrade_path": "Ubuntu 22.04 LTS",
                "source_url": "https://ubuntu.com/about/release-cycle",
            },
        ),
    )

    result = service.sync(raise_on_quality_failure=False)
    history = _delta_rows(lakehouse / "Tables/silver_lifecycle_history")

    assert result.status == "completed"
    # Base fixture yields 2 lifecycle-bearing resources (VM + Arc server; the
    # storage account has no OS), plus the duplicated VM under rg-secondary.
    # Distinct resource_keys prove correlation is by canonical id, not name.
    assert len(history) == 3
    assert len({row["resource_key"] for row in history}) == 3


def test_semantic_layer_builds_only_from_governed_fabric_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    service.sync()

    semantic = SemanticEngine.from_rows(**service.semantic_snapshot())
    result = semantic.query("Find ownership gaps")

    assert result["knowledge_version"].startswith("semantic-")
    assert all("payload_json" not in row for row in result["items"])


def test_incident_snapshot_exposes_governed_resource_changes_without_azure_calls(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    service.sync()

    snapshot = service.incident_intelligence_snapshot()

    assert snapshot["inventory"]
    assert snapshot["resource_changes"]
    assert snapshot["resource_changes"][0]["resource_key"].startswith(
        "/subscriptions/"
    )
    assert snapshot["incidents"] == []
    assert snapshot["alerts"] == []


def test_change_snapshot_exposes_governed_changes_and_optional_deviations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    service.sync()

    snapshot = service.change_intelligence_snapshot()

    assert snapshot["inventory"]
    assert snapshot["resource_changes"]
    assert snapshot["resource_changes"][0]["resource_key"].startswith(
        "/subscriptions/"
    )
    assert snapshot["policy_deviations"] == []
    assert snapshot["security_deviations"] == []


def test_predictive_snapshot_uses_governed_inventory_and_history(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    service.sync()

    snapshot = service.predictive_intelligence_snapshot()

    assert snapshot["inventory"]
    assert snapshot["history"] == []


def test_remediation_snapshot_uses_governed_inventory_and_catalogs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    service.sync()

    snapshot = service.remediation_planning_snapshot()

    assert snapshot["inventory"]
    assert snapshot["action_catalog"] == []
    assert snapshot["approval_policies"] == []


def test_failed_quality_run_is_recoverable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    vm_file = source / "current/entities/VirtualMachine.jsonl"
    row = json.loads(vm_file.read_text())
    row["subscriptionId"] = "wrong-subscription"
    vm_file.resolve().write_text(json.dumps(row) + "\n")
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )

    result = service.sync(raise_on_quality_failure=False)

    states = _delta_rows(lakehouse / "Tables/metadata_ingestion_state")
    assert result.status == "failed"
    assert states[-1]["status"] == "failed"
    assert states[-1]["failed_records"] > 0

    row["subscriptionId"] = "sub-1"
    vm_file.resolve().write_text(json.dumps(row) + "\n")
    recovered = service.sync()
    states = _delta_rows(lakehouse / "Tables/metadata_ingestion_state")
    assert recovered.status == "completed"
    assert {state["status"] for state in states} == {"failed", "completed"}


def test_replay_selects_named_source_generation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )

    result = service.sync(replay_source_run_id="source-run-1")

    assert result.source_run_id == "source-run-1"
    assert result.replay


def test_change_feed_uses_subscription_tenant_when_target_was_deleted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)
    snapshot = (source / "current").resolve()
    change_file = snapshot / "changes/resource_changes.jsonl"
    change = json.loads(change_file.read_text())
    change["targetResourceId"] = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/X/deleted"
    change_file.write_text(json.dumps(change) + "\n")

    rows = InventoryDatasetMapper().load(snapshot, "run-1")["bronze_resource_changes"]

    assert rows[0]["tenant_id"] == "tenant-1"


def test_sync_registers_tables_and_configured_shortcuts(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)

    class Registrar:
        def __init__(self):
            self.expected = set()
            self.shortcuts = []

        def create_shortcut(self, lakehouse_id, **kwargs):
            self.shortcuts.append((lakehouse_id, kwargs))

        def ensure_tables_registered(self, lakehouse_id, expected, attempts):
            self.expected = expected
            return expected

    registrar = Registrar()
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lakehouse"),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        lakehouse_manager=registrar,
        lakehouse_id="lakehouse",
        shortcuts=(
            SimpleNamespace(
                path="Files/bronze",
                name="shared",
                target={"oneLake": {"workspaceId": "w2", "itemId": "l2", "path": "Tables/x"}},
                conflict_policy="CreateOrOverwrite",
            ),
        ),
        registration_attempts=1,
    )

    service.sync()

    assert "bronze_resources" in registrar.expected
    assert "metadata_ingestion_state" in registrar.expected
    assert registrar.shortcuts[0][1]["name"] == "shared"


def test_sync_publishes_typed_fabric_ontology_bindings(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_snapshot(source)

    class Publisher:
        def __init__(self):
            self.call = None

        def publish(self, **kwargs):
            self.call = kwargs
            return {"id": "ontology-1", "action": "created"}

    publisher = Publisher()
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        ontology_publisher=publisher,
        ontology_name="Operational_Context_Graph",
    )

    service.sync()

    assert publisher.call["ontology_name"] == "Operational_Context_Graph"
    assert publisher.call["entity_types"]["VirtualMachine"] == (
        "ontology_virtual_machine_entities"
    )
    assert (
        "VirtualMachine",
        "member_of",
        "Application",
    ) in publisher.call["relationships"]


def test_snapshot_sync_removes_resources_missing_from_new_generation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    service.sync()

    snapshot = (source / "current").resolve()
    vm_id = json.loads((snapshot / "entities/VirtualMachine.jsonl").read_text())["id"]
    (snapshot / "entities/VirtualMachine.jsonl").write_text("")
    relationships = [
        json.loads(line)
        for line in (snapshot / "relationships/relationships.jsonl").read_text().splitlines()
        if line
    ]
    relationships = [
        row
        for row in relationships
        if row["subjectId"] != vm_id and row["objectId"] != vm_id
    ]
    (snapshot / "relationships/relationships.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in relationships)
    )

    service.sync()

    assert _delta_rows(lakehouse / "Tables/silver_vm_inventory") == []
    assert len(_delta_rows(lakehouse / "Tables/bronze_resources")) == 2
    assert _delta_rows(lakehouse / "Tables/ontology_virtual_machine_entities") == []
    assert any(
        row["entity_type"] == "VirtualMachine" and row["lifecycle_status"] == "retired"
        for row in _delta_rows(lakehouse / "Tables/ontology_entities")
    )
    assert any(
        row["lifecycle_status"] == "retired"
        for row in _delta_rows(lakehouse / "Tables/ontology_relationships")
        if row["subject_type"] == "VirtualMachine" or row["object_type"] == "VirtualMachine"
    )


def test_inventory_generation_publishes_successful_family_when_arc_fails(
    tmp_path: Path,
) -> None:
    class FamilyFailureSource:
        def list_subscriptions(self) -> list[dict]:
            return [{"subscriptionId": "sub-a"}]

        def fetch(self, specs, subscription_ids):
            return {
                spec.name: (
                    [
                        {
                            "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                            "name": "vm-1",
                            "type": "microsoft.compute/virtualmachines",
                            "subscriptionId": "sub-a",
                            "resourceGroup": "rg",
                            "tags": {"Environment": "prod"},
                            "osType": "Windows",
                        }
                    ]
                    if spec.name == "inventory_native_vm_os"
                    else (
                        [{"status": "failed", "provider_status": "failed", "error": "Arc timeout"}]
                        if spec.name == "inventory_arc_os"
                        else []
                    )
                )
                for spec in specs
            }

    service = InventoryPipeline(
        ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-a",)),
        source=FamilyFailureSource(),
        clock=lambda: datetime(2026, 8, 25, 10, tzinfo=UTC),
    )
    service.refresh()

    generation = (tmp_path / "current").resolve()
    observations = [
        json.loads(line)
        for line in (generation / "inventory/os_observations.jsonl").read_text().splitlines()
    ]
    statuses = {
        json.loads(line)["source_type"]: json.loads(line)
        for line in (generation / "inventory/source_status.jsonl").read_text().splitlines()
    }
    assert len(observations) == 1
    assert observations[0]["environment"] == "prod"
    assert observations[0]["os_version"] == "Unknown"
    assert statuses["azure_vm"]["state"] == "ready"
    assert statuses["arc"]["state"] == "degraded"
    assert statuses["arc"]["error"] == "Arc timeout"
    assert statuses["arc"]["requested_scope"] == {"subscription": ["sub-a"]}


def test_inventory_source_status_and_rows_have_family_query_versions(tmp_path: Path) -> None:
    fixture = json.loads((Path(__file__).parent / "fixtures" / "mock_inventory_arg.json").read_text())
    from intelligence.inventory.normalization import normalize_os_inventory

    observations, statuses = normalize_os_inventory(
        {
            "inventory_native_vm_os": fixture["inventory_native_vm_os"],
            "inventory_arc_os": fixture["inventory_arc_os"],
        },
        "2026-08-25T10:00:00+00:00",
        run_id="inventory-query-version-run",
        requested_scope={"subscription": ["sub-a", "sub-b"]},
    )
    from storage.datasets import DatasetStore as NeutralDatasetStore

    store = NeutralDatasetStore(tmp_path)
    store.publish(
        {
            "inventory/os_observations": observations,
            "inventory/source_status": statuses,
        },
        {},
        {"runId": "inventory-query-version-run", "status": "completed"},
    )

    statuses = store.read_dataset("inventory/source_status")
    observations = store.read_dataset("inventory/os_observations")
    assert {row["query_version"] for row in statuses} == {
        "inventory-native-vm-os-v1",
        "inventory-arc-os-v1",
    }
    assert {row["query_version"] for row in observations} == {
        "inventory-native-vm-os-v1",
        "inventory-arc-os-v1",
    }


def test_registration_failure_rolls_back_business_tables(tmp_path: Path) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    onelake = OneLakeWriter("workspace", "lakehouse", local_root=lakehouse)
    baseline = FabricSyncService(
        source_root=source,
        onelake=onelake,
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    baseline.sync()
    before = _delta_rows(lakehouse / "Tables/bronze_resources")

    snapshot = (source / "current").resolve()
    resource_file = snapshot / "entities/Resource.jsonl"
    resource = json.loads(resource_file.read_text())
    resource["name"] = "changed-before-registration-failure"
    resource_file.write_text(json.dumps(resource) + "\n")

    class FailingRegistrar:
        def ensure_tables_registered(self, *_args, **_kwargs):
            raise RuntimeError("registration unavailable")

    failing = FabricSyncService(
        source_root=source,
        onelake=onelake,
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        lakehouse_manager=FailingRegistrar(),
        lakehouse_id="lakehouse",
        registration_attempts=1,
    )

    try:
        failing.sync()
    except RuntimeError as exc:
        assert "registration unavailable" in str(exc)
    else:
        raise AssertionError("expected registration failure")

    assert _delta_rows(lakehouse / "Tables/bronze_resources") == before


def test_mapper_reads_remote_snapshot_via_provided_filesystem(tmp_path: Path) -> None:
    """Regression test: `InventoryDatasetMapper.load()` must use the caller's
    `fs` for remote (OneLake) snapshots instead of re-resolving the already
    fsspec-resolved path as a local filesystem. Previously this silently
    returned an empty snapshot (no error) because a bare `container/path`
    string with no `abfss://` scheme resolves to the *local* filesystem,
    where that path doesn't exist.
    """
    import fsspec

    remote_root = f"abfss://ws-aiops@onelake.dfs.fabric.microsoft.com/lakehouse/Files/aiops/connections/demo-{uuid4().hex}"
    store = DatasetStore(remote_root)
    memory_fs = fsspec.filesystem("memory")
    store.fs = memory_fs  # swap the real ADLS backend for an in-memory one

    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    store.publish(graph, payload, {"runId": "remote-run-1", "startedAt": "2026-08-17T00:00:00Z"})

    snapshot_dir = store.current_generation()
    snapshot_uri = store.current_generation_uri()
    assert snapshot_dir is not None
    assert snapshot_uri is not None
    assert snapshot_uri.startswith(remote_root)
    assert snapshot_uri.endswith(snapshot_dir.rsplit("/", 1)[-1])

    # Without passing `fs`, the mapper falls back to resolving the path
    # itself, which treats the bare `container/path` string as local and
    # finds nothing.
    empty = InventoryDatasetMapper().load(snapshot_dir, "remote-run-1")
    assert empty["bronze_resources"] == []

    # Passing the store's own filesystem must load the real data.
    tables = InventoryDatasetMapper().load(snapshot_dir, "remote-run-1", fs=memory_fs)
    assert tables["bronze_resources"] != [] or tables["bronze_virtual_machines"] != []

    direct = FabricSyncService(
        source_root=snapshot_uri,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "direct-lakehouse"),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    direct._source_fs = memory_fs
    assert direct._resolve_snapshot("") == snapshot_dir

    class Delta:
        def __init__(self):
            self.attempts = []

        def restore(self, uri, version):
            self.attempts.append(uri)
            if uri == "table-2":
                raise OSError("temporary restore failure")

    delta = Delta()
    service = FabricSyncService(
        source_root=tmp_path,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lakehouse"),
        delta_writer=delta,
        validator=DataQualityValidator(),
        rollback_sleep=lambda _delay: None,
    )

    errors = service._rollback(
        {
            "bronze_one": ("table-1", 0),
            "bronze_two": ("table-2", 0),
            "bronze_three": ("table-3", 0),
        }
    )

    assert delta.attempts.count("table-2") == 3
    assert "table-1" in delta.attempts
    assert "table-3" in delta.attempts
    assert len(errors) == 1


def test_sync_service_history_tables_use_merge_write_mode_contract(tmp_path: Path) -> None:
    service = FabricSyncService(
        source_root=tmp_path / "source",
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lakehouse"),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )

    expected_history_tables = {
        "bronze_resource_changes",
        "silver_patch_history",
        "silver_lifecycle_history",
        "silver_defender_secure_scores",
        "silver_change_history",
        "silver_incident_history",
        "silver_predictive_history",
        "silver_cost_actuals",
    }
    assert service._MERGE_WRITE_TABLES == expected_history_tables
    for table_name in expected_history_tables:
        assert service._write_mode_for_table(table_name) is DeltaWriteMode.MERGE
    assert service._write_mode_for_table("metadata_audit_events") is DeltaWriteMode.APPEND
    assert service._write_mode_for_table("silver_compliance") is DeltaWriteMode.OVERWRITE
