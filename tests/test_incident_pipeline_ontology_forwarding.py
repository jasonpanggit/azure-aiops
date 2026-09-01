"""Regression tests for MED-04 Task 4: the Incident-domain ontology
forwarding fix.

``IncidentEngine.knowledge_projection()`` already builds a bounded
``CausalityGraph`` of ``Incident``/``OperationalFinding``/``BlastRadius``/
``DependencyChain``/``OperationalEvent``/``RootCause`` rows shaped for
ontology publication, but ``IncidentEngine`` was only ever instantiated in
``src/semantic/live_operations.py``'s on-demand query path — never in
``sync_service.py``'s batch dataset-assembly flow — so the graph never
reached ontology publication either. This mirrors
``test_change_pipeline_ontology_forwarding.py``'s pattern exactly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from deltalake import DeltaTable

from fabric.data_quality import DataQualityValidator
from fabric.sync_service import FabricSyncService
from fabric_pipelines import incident_pipeline
from intelligence.incidents.incident_engine import IncidentEngine
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_writer import OneLakeWriter

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"
INCIDENT_FIXTURE = Path(__file__).parent / "fixtures" / "sample_incident_causality.json"
RESOURCE_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute"
    "/virtualmachines/vm-prod-01"
)


def test_incident_pipeline_forwards_knowledge_projection_entities() -> None:
    scenario = json.loads(INCIDENT_FIXTURE.read_text())
    result = incident_pipeline.run(**scenario)
    engine = IncidentEngine.from_snapshot(**scenario)
    engine.analyze()
    aiops = engine.knowledge_projection()

    assert result.entities == aiops["entities"]
    assert result.entities != []
    entity_types = {row["entity_type"] for row in result.entities}
    assert entity_types & {
        "Incident",
        "OperationalFinding",
        "BlastRadius",
        "DependencyChain",
        "OperationalEvent",
        "RootCause",
    }


def test_incident_pipeline_forwards_knowledge_projection_relationships() -> None:
    scenario = json.loads(INCIDENT_FIXTURE.read_text())
    result = incident_pipeline.run(**scenario)
    engine = IncidentEngine.from_snapshot(**scenario)
    engine.analyze()
    aiops = engine.knowledge_projection()

    assert result.relationships == aiops["relationships"]
    assert result.relationships != []


def test_incident_pipeline_empty_snapshot_yields_empty_entities_and_relationships() -> None:
    result = incident_pipeline.run(
        resources=[],
        incidents=[],
        alerts=[],
        resource_changes=[],
        patch_findings=[],
        lifecycle_findings=[],
        history=[],
        freshness="2026-08-18T13:00:00Z",
    )

    assert result.entities == []
    assert result.relationships == []


def _source_snapshot(root: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    DatasetStore(root).publish(
        graph,
        payload,
        {"runId": "source-run-1", "startedAt": "2026-08-17T00:00:00Z", "status": "completed"},
    )


def _delta_rows(path: Path) -> list[dict]:
    return DeltaTable(str(path)).to_pyarrow_table().to_pylist()


def _build_service(tmp_path) -> FabricSyncService:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    onelake = OneLakeWriter("workspace", "lakehouse", local_root=lakehouse)
    return FabricSyncService(
        source_root=source,
        onelake=onelake,
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )


def _seed_governed_incident_tables(service: FabricSyncService) -> None:
    """Seed the governed silver tables ``incident_intelligence_snapshot()``
    reads, simulating data already committed by other connectors/processes
    before this sync run."""
    now = "2026-08-17T00:00:00Z"
    common = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "timestamp": now,
        "ingestion_run_id": "seed-run",
    }
    incident_row = {
        **common,
        "resource_id": "INC-100",
        "change_version": "seed-incident-1",
        "incident_id": "INC-100",
        "title": "Payments checkout degraded",
        "status": "Active",
        "severity": "High",
        "started_at": now,
        "target_resource_id": RESOURCE_ID,
    }
    alert_row = {
        **common,
        "resource_id": "ALERT-100",
        "change_version": "seed-alert-1",
        "alert_id": "ALERT-100",
        "title": "High CPU utilization",
        "severity": "High",
        "fired_at": now,
        "target_resource_id": RESOURCE_ID,
        "signal": "CPU",
    }
    service.delta.write(
        service.onelake.table_uri("silver", "incidents"),
        [incident_row],
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=("resource_id",),
    )
    service.delta.write(
        service.onelake.table_uri("silver", "alerts"),
        [alert_row],
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=("resource_id",),
    )


def test_incident_pipeline_ontology_rows_reach_ontology_entities(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    service.sync()
    _seed_governed_incident_tables(service)

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    entities = _delta_rows(lakehouse / "Tables/ontology_entities")
    entity_types = {row["entity_type"] for row in entities}
    assert entity_types & {
        "Incident",
        "OperationalFinding",
        "BlastRadius",
        "DependencyChain",
        "OperationalEvent",
        "RootCause",
    }
    assert "Incident" in entity_types


def test_incident_pipeline_relationships_survive_ontology_synchronization(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    service.sync()
    _seed_governed_incident_tables(service)

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    relationships = _delta_rows(lakehouse / "Tables/ontology_relationships")
    entities = _delta_rows(lakehouse / "Tables/ontology_entities")
    known_ids = {row["resource_id"] for row in entities}
    incident_relationships = [
        row for row in relationships if row["source"] == "Incident Causality"
    ]
    assert incident_relationships
    assert all(row["subject_id"] in known_ids for row in incident_relationships)
    assert all(row["object_id"] in known_ids for row in incident_relationships)


def test_incident_pipeline_forwarding_is_empty_when_no_governed_incident_data(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    entities = _delta_rows(lakehouse / "Tables/ontology_entities")
    incident_entities = [
        row
        for row in entities
        if row["entity_type"]
        in {
            "Incident",
            "OperationalFinding",
            "BlastRadius",
            "DependencyChain",
            "OperationalEvent",
            "RootCause",
        }
    ]
    assert incident_entities == []


def test_incident_engine_reachable_from_sync_service_batch_flow() -> None:
    """Acceptance criteria intent: IncidentEngine now reaches the batch sync
    flow, not just the live on-demand query path in live_operations.py.

    The plan's literal `grep -rln "IncidentEngine(" src/` check is a false
    friend here -- it matches live_operations.py only because
    `LiveIncidentEngine(` contains "IncidentEngine(" as a substring (verified
    this session), a coincidence unrelated to this incident_engine module.
    This asserts the actual reachability claim instead: incident_pipeline.py
    (which does use IncidentEngine) exists alongside live_operations.py, and
    sync_service.py's batch sync flow calls incident_pipeline.run().
    """
    import subprocess

    result = subprocess.run(
        ["grep", "-rln", "IncidentEngine", "src/"],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    files = set(result.stdout.strip().splitlines())
    assert "src/semantic/live_operations.py" in files
    assert "src/fabric_pipelines/incident_pipeline.py" in files

    sync_service_source = (Path(__file__).parent.parent / "src/fabric/sync_service.py").read_text()
    assert "incident_pipeline.run(" in sync_service_source
