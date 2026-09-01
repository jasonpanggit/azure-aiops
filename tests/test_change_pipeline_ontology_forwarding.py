"""Regression tests for MED-04: the change-domain ontology forwarding fix,
the predictive-domain identical fix, and the remediation-domain evidence-
backed disposition (Task 3's Assumptions Log A4 investigation).

``ChangeIntelligence.knowledge_projection()`` already computes
``ConfigurationDrift``/``PolicyDeviation``/``SecurityDeviation``/
``AuthorizedChange``/``UnapprovedChange`` rows shaped for ontology
publication. Before this fix, ``change_pipeline.run()`` never called
``knowledge_projection()`` and ``sync_service.py`` never forwarded its
output into ``datasets["ontology_entities"]``/``["ontology_relationships"]``
- the computed graph was silently discarded. These tests assert the rows
now reach the same fail-closed ``OntologyGraphSynchronizer`` gate every
other ontology source passes through, with no bypass.

Task 3 additionally investigated whether the predictive/remediation
ontology domain shares this bug. Evidence found:

- ``PredictiveEngine.knowledge_projection()`` shares the *identical*
  "computed but discarded" shape as the Change domain — a pure
  ``from_snapshot()``-driven projection with no external state dependency
  — but had no ``fabric_pipelines`` module at all (not even a discarding
  one) and was never instantiated outside its own tests
  (``grep -rln "PredictiveEngine(" src/`` returns nothing before this fix).
  Fixed identically to the Change domain (new ``predictive_pipeline.py``,
  wired into ``sync_service.py``).
- ``PlanRepository.ontology_projection()`` is genuinely different: it
  requires ``replace_generation()`` to have already populated
  ``self._plans`` with LLM/planner-generated draft remediation plans — a
  stateful prerequisite process that only runs in the live-query paths
  (``live_operations.py``, ``api/runtime.py``), never in the batch sync
  flow. Wiring this into ``sync_service.py`` would mean *running the
  remediation planner as a new sync-time side effect* — an architectural
  change out of this plan's wiring-fix scope, not a simple forwarding fix.
  Dispositioned ``dormant`` via ``PublicationManifestStore`` — physically
  present, intentionally inactive, not silently assumed fine.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from deltalake import DeltaTable

from fabric.data_quality import DataQualityValidator
from fabric.sync_service import FabricSyncService
from fabric_pipelines import predictive_pipeline
from intelligence.remediation.plan_repository import PlanRepository
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from ontology.publication_manifest import PublicationManifestStore
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_writer import OneLakeWriter

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"
PREDICTIVE_FIXTURE = Path(__file__).parent / "fixtures" / "sample_predictive_operations.json"
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


# ---------------------------------------------------------------------------
# Task 3: predictive domain — identical "computed but discarded" bug, fixed
# identically to the Change domain (new predictive_pipeline.py, wired into
# sync_service.py).
# ---------------------------------------------------------------------------


def test_predictive_pipeline_forwards_knowledge_projection_entities() -> None:
    from intelligence.predictive.predictive_engine import PredictiveEngine

    scenario = json.loads(PREDICTIVE_FIXTURE.read_text())
    result = predictive_pipeline.run(**scenario)
    aiops = PredictiveEngine.from_snapshot(**scenario).knowledge_projection()

    assert result.entities == aiops["entities"]
    assert result.entities != []
    entity_types = {row["entity_type"] for row in result.entities}
    assert entity_types & {"Prediction", "Forecast", "OperationalDebt", "RiskDriver"}


def test_predictive_pipeline_forwards_knowledge_projection_relationships() -> None:
    from intelligence.predictive.predictive_engine import PredictiveEngine

    scenario = json.loads(PREDICTIVE_FIXTURE.read_text())
    result = predictive_pipeline.run(**scenario)
    aiops = PredictiveEngine.from_snapshot(**scenario).knowledge_projection()

    assert result.relationships == aiops["relationships"]


def test_predictive_pipeline_empty_snapshot_yields_empty_entities_and_relationships() -> None:
    result = predictive_pipeline.run(
        resources=[], history=[], freshness="2026-08-18T13:00:00Z"
    )

    assert result.entities == []
    assert result.relationships == []


def test_predictive_pipeline_ontology_rows_reach_ontology_entities(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    now = "2026-08-17T00:00:00Z"
    predictive_history_row = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "timestamp": now,
        "ingestion_run_id": "seed-run",
        "resource_id": "predictive-history-1",
        "change_version": "seed-predictive-1",
        "target_resource_id": RESOURCE_ID,
        "observed_at": now,
        "patch_debt": 5,
        "lifecycle_risk_score": 40,
        "incident_count_30d": 2,
        "configuration_drift_count": 1,
        "risk_score": 60,
    }

    service.sync()
    service.delta.write(
        service.onelake.table_uri("silver", "predictive_history"),
        [predictive_history_row],
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=("resource_id",),
    )

    service.sync()

    lakehouse = tmp_path / "lakehouse"
    entities = _delta_rows(lakehouse / "Tables/ontology_entities")
    entity_types = {row["entity_type"] for row in entities}
    assert entity_types & {"Prediction", "Forecast", "OperationalDebt", "RiskDriver", "Trend"}


# ---------------------------------------------------------------------------
# Task 3: remediation domain — evidence-backed "dormant" disposition, not a
# guessed/invented producer. PlanRepository.ontology_projection() exists and
# is structurally identical to the other domains' knowledge_projection()
# methods, but it requires replace_generation() to have already populated
# self._plans with planner-generated draft plans — a prerequisite process
# that only runs in the live-query paths (live_operations.py, api/
# runtime.py), never in FabricSyncService's batch sync flow. Wiring this in
# would mean running the remediation planner as a new sync-time side
# effect, which is an architectural change out of this plan's scope.
# ---------------------------------------------------------------------------


def test_remediation_plan_ontology_projection_is_empty_without_generated_plans() -> None:
    """Verifies the actual, current state: no batch-flow caller ever
    populates PlanRepository's plans, so its ontology projection is
    genuinely empty in the sync path — not merely untested."""
    repository = PlanRepository()

    projection = repository.ontology_projection()

    assert projection["entities"] == []
    assert projection["relationships"] == []


def test_remediation_plan_domain_is_registered_dormant_pending_plan_generation() -> None:
    """Records the disposition explicitly instead of leaving MED-04's A4
    assumption as an unverified guess for a later phase to rediscover."""
    store = PublicationManifestStore()

    entry = store.register("remediation_plan_projection", disposition="dormant")

    assert entry.disposition == "dormant"
    assert store.get("remediation_plan_projection").disposition == "dormant"

