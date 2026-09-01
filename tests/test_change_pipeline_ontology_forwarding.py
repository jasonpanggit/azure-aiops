"""Regression tests for MED-04: the change-domain ontology forwarding fix.

``ChangeIntelligence.knowledge_projection()`` already computes
``ConfigurationDrift``/``PolicyDeviation``/``SecurityDeviation``/
``AuthorizedChange``/``UnapprovedChange`` rows shaped for ontology
publication. Before this fix, ``change_pipeline.run()`` never called
``knowledge_projection()`` and ``sync_service.py`` never forwarded its
output into ``datasets["ontology_entities"]``/``["ontology_relationships"]``
- the computed graph was silently discarded. These tests assert the rows
now reach the same fail-closed ``OntologyGraphSynchronizer`` gate every
other ontology source passes through, with no bypass.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from deltalake import DeltaTable

from fabric.data_quality import DataQualityValidator
from fabric.sync_service import FabricSyncService
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_writer import OneLakeWriter

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"
RESOURCE_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute"
    "/virtualmachines/vm-prod-01"
)


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


def _seed_governed_change_tables(service: FabricSyncService) -> None:
    """Seed the governed silver tables ``change_intelligence_snapshot()``
    reads, simulating data already committed by other connectors/processes
    before this sync run (the same pattern ``change_intelligence_snapshot()``
    is already designed to read for the live-query path)."""
    now = "2026-08-17T00:00:00Z"
    common = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "timestamp": now,
        "ingestion_run_id": "seed-run",
    }
    policy_row = {
        **common,
        "resource_id": "policy-dev-1",
        "change_version": "seed-policy-1",
        "deviation_id": "POL-100",
        "target_resource_id": RESOURCE_ID,
        "observed_at": now,
        "severity": "High",
        "control": "Public network access must be disabled",
        "status": "NonCompliant",
    }
    security_row = {
        **common,
        "resource_id": "sec-dev-1",
        "change_version": "seed-security-1",
        "deviation_id": "SEC-100",
        "target_resource_id": RESOURCE_ID,
        "observed_at": now,
        "severity": "Critical",
        "control": "Internet exposure baseline",
        "status": "Deviated",
    }
    expected_row = {
        **common,
        "resource_id": RESOURCE_ID,
        "change_version": "seed-expected-1",
        "target_resource_id": RESOURCE_ID,
        "configuration_json": json.dumps({"publicNetworkAccess": "Disabled"}),
    }
    observed_row = {
        **common,
        "resource_id": RESOURCE_ID,
        "change_version": "seed-observed-1",
        "target_resource_id": RESOURCE_ID,
        "configuration_json": json.dumps({"publicNetworkAccess": "Enabled"}),
    }
    for layer, name, rows in (
        ("silver", "policy_deviations", [policy_row]),
        ("silver", "security_deviations", [security_row]),
        ("silver", "expected_configurations", [expected_row]),
        ("silver", "observed_configurations", [observed_row]),
    ):
        service.delta.write(
            service.onelake.table_uri(layer, name),
            rows,
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=("resource_id",),
        )


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


def test_change_pipeline_ontology_rows_reach_ontology_entities(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    # First sync commits bronze_resources so `change_intelligence_snapshot()`
    # (read inside the second sync) has a governed inventory to join against.
    service.sync()
    _seed_governed_change_tables(service)

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    entities = _delta_rows(lakehouse / "Tables/ontology_entities")
    entity_types = {row["entity_type"] for row in entities}
    assert entity_types & {
        "ConfigurationDrift",
        "PolicyDeviation",
        "SecurityDeviation",
        "AuthorizedChange",
        "UnapprovedChange",
        "ChangeEvent",
        "ConfigurationBaseline",
    }
    assert "ConfigurationDrift" in entity_types
    assert "PolicyDeviation" in entity_types
    assert "SecurityDeviation" in entity_types


def test_change_pipeline_relationships_survive_ontology_synchronization(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    service.sync()
    _seed_governed_change_tables(service)

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    relationships = _delta_rows(lakehouse / "Tables/ontology_relationships")
    # Rows pass through the same OntologyGraphSynchronizer gate as every
    # other source - every relationship's subject/object resolve to a known
    # entity id (no dangling edges survive synchronize()).
    entities = _delta_rows(lakehouse / "Tables/ontology_entities")
    known_ids = {row["resource_id"] for row in entities}
    change_relationships = [
        row for row in relationships if row["source"] == "Change Intelligence"
    ]
    assert change_relationships
    assert all(row["subject_id"] in known_ids for row in change_relationships)
    assert all(row["object_id"] in known_ids for row in change_relationships)


def test_assessment_change_findings_populated_exactly_once(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    service.sync()
    _seed_governed_change_tables(service)

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    findings = _delta_rows(lakehouse / "Tables/assessment_change_findings")
    assert findings
    change_ids = [row["change_id"] for row in findings]
    assert len(change_ids) == len(set(change_ids))


def test_change_pipeline_forwarding_is_empty_when_no_governed_change_data(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    entities = _delta_rows(lakehouse / "Tables/ontology_entities")
    change_entities = [
        row
        for row in entities
        if row["entity_type"]
        in {
            "ConfigurationDrift",
            "PolicyDeviation",
            "SecurityDeviation",
            "AuthorizedChange",
            "UnapprovedChange",
        }
    ]
    assert change_entities == []
