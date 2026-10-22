from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from test_container_image_exposure import REGISTRY, _granular_image_row

from fabric.data_quality import DataQualityValidator
from fabric.sync_service import FabricSyncService
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter


def test_registry_mapping_sync_persists_and_retires_source_edges(tmp_path: Path):
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    payload = {
        "resources": [{
            "id": REGISTRY,
            "name": "acr1",
            "type": "Microsoft.ContainerRegistry/registries",
            "subscriptionId": "sub1",
            "resourceGroup": "rg1",
            "tenantId": "tenant1",
        }],
        "defender_assessments": [
            {
                **_granular_image_row("openssl", ["Critical"], ["CVE-2026-1001"]),
                "tenantId": "tenant1",
            },
        ],
    }

    def publish(day: int) -> None:
        observed = datetime(2026, 9, day, tzinfo=UTC)
        run_id = f"registry-source-{day}"
        graph = Normalizer({"connection_id": "connection-1"}).normalize(
            payload, observed, run_id=run_id,
        )
        DatasetStore(source).publish(
            graph, payload,
            {"runId": run_id, "startedAt": observed.isoformat(), "status": "completed"},
        )

    publish(2)
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    table = lakehouse / (
        "Tables/ontology_rel_exposes_container_image_exposure_container_registry"
    )

    assert service.sync().status == "completed"
    rows = service.delta.read(table)
    assert len(rows) == 1
    assert rows[0]["object_id"] == REGISTRY.casefold()
    assert rows[0]["subject_type"] == "ContainerImageExposure"
    assert rows[0]["object_type"] == "ContainerRegistry"
    assert rows[0]["lifecycle_status"] == "active"
    relationship_id = rows[0]["resource_id"]
    semantic_version = rows[0]["change_version"]

    assert service.sync().status == "completed"
    replay = service.delta.read(table)
    assert len(replay) == 1
    assert replay[0]["resource_id"] == relationship_id
    assert replay[0]["change_version"] == semantic_version

    payload["defender_assessments"] = []
    payload["resources"].append({
        **payload["resources"][0],
        "id": f"{REGISTRY}-new",
        "name": "acr1-new",
    })
    publish(3)
    assert service.sync().status == "completed"
    assert service.delta.read(table) == []
    retired = [
        row for row in service.delta.read(lakehouse / "Tables/ontology_relationships")
        if row["resource_id"] == relationship_id
    ]
    assert len(retired) == 1
    assert retired[0]["lifecycle_status"] == "retired"
