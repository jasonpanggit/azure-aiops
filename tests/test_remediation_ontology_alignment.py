import copy
import json
from pathlib import Path

from remediation_scenario import remediation_planner

from fabric.config import FabricAuthConfig, FabricRuntimeConfig
from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import (
    ONTOLOGY_RELATIONSHIP_TYPES,
    InventoryDatasetMapper,
    remediation_decision_ontology_rows,
    remediation_plan_ontology_rows,
)
from fabric.runtime import build_runtime
from fabric.sync_service import FabricSyncService
from intelligence.remediation.plan_repository import PlanRepository
from ontology.ontology_validator import OntologyValidator
from storage.delta_writer import DeltaWriter
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter
from tests.defender_correlation_scenario import defender_correlator
from tests.test_incremental_sync import _delta_rows, _source_snapshot

_DEFENDER_PREDICATES = {
    "addressesFinding",
    "addressesAlert",
    "breaksAttackPath",
    "improvesControl",
}


def _plan_and_defender_entities():
    planner = remediation_planner(defender_correlator=defender_correlator())
    planner.generate_plans()
    plans = planner.repository.list()
    plan = next(
        item
        for item in plans
        if {
            citation["source_type"]
            for citation in item["evidence_citations"]
        }
        == {"assessment", "alert", "attack_path", "secure_score_control"}
    )
    resource_id = plan["resource"].get("id") or plan["resource_key"]
    entities = [
        _ontology_entity(
            "assess-001",
            "DefenderAssessment",
            {"targetResourceId": resource_id},
        ),
        _ontology_entity(
            "alert-001",
            "SecurityAlert",
            {"resourceIds": [resource_id]},
        ),
        _ontology_entity(
            "path-001",
            "AttackPath",
            {"resourceIds": [resource_id]},
        ),
        _ontology_entity(
            "control-001",
            "SecureScoreControl",
            {"assessmentDefinitions": ["assess-001"]},
        ),
    ]
    return planner, plan, entities


def _ontology_entity(
    resource_id: str,
    entity_type: str,
    payload: dict,
    *,
    ingestion_run_id: str = "run-1",
    timestamp: str = "2026-08-31T00:00:00Z",
) -> dict:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id,
        "timestamp": timestamp,
        "change_version": f"version-{resource_id}",
        "ingestion_run_id": ingestion_run_id,
        "entity_type": entity_type,
        "name": resource_id,
        "resource_type": f"microsoft.security/{entity_type.casefold()}",
        "location": "",
        "payload_json": json.dumps(payload, sort_keys=True),
        "lineage_json": json.dumps({"source_resource_ids": [resource_id]}),
        "semantic_metadata_json": json.dumps({"source": "defender"}),
        "lifecycle_status": "active",
        "valid_from": timestamp,
        "retired_at": "",
        "ontology_version": "1",
    }


def test_approval_decisions_are_projected_into_remediation_ontology():
    planner = remediation_planner()
    plan = next(
        item for item in planner.generate_plans()["plans"] if item["evidence_citations"]
    )

    decision = planner.repository.decisions.append(
        plan=plan,
        decision="rejected",
        approver="operator@example.com",
        reason="Evidence needs owner clarification",
        scope={"subscription": ["sub-1"]},
        action_version=plan["action_version"],
    )
    projection = planner.repository.ontology_projection()

    assert any(
        row["entity_id"] == decision["decision_id"]
        and row["entity_type"] == "ApprovalDecision"
        and row["lifecycle_status"] == "rejected"
        for row in projection["entities"]
    )
    assert any(
        row["subject_id"] == plan["plan_id"]
        and row["relationship_type"] == "hasApprovalDecision"
        and row["object_id"] == decision["decision_id"]
        for row in projection["relationships"]
    )
    assert projection["read_only"] is True


def test_durable_approval_decisions_publish_to_ontology_rows():
    planner = remediation_planner()
    plan = planner.generate_plans()["plans"][0]
    decision = planner.repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="operator@example.com",
        reason="Approved for planning handoff",
        scope={"subscription": ["sub-1"]},
        action_version=plan["action_version"],
        expires_at="2026-09-01T00:00:00Z",
    )

    entities, relationships = remediation_decision_ontology_rows(
        [decision],
        "run-1",
        "2026-08-31T00:00:00Z",
    )

    assert any(
        row["resource_id"] == decision["decision_id"]
        and row["entity_type"] == "ApprovalDecision"
        for row in entities
    )
    assert any(
        row["subject_id"] == plan["plan_id"]
        and row["predicate"] == "hasApprovalDecision"
        and row["object_id"] == decision["decision_id"]
        for row in relationships
    )


def test_plan_defender_evidence_relationships_are_registered_and_projected():
    planner, _plan, defender_entities = _plan_and_defender_entities()

    projection = planner.repository.ontology_projection(
        defender_entities=defender_entities
    )
    relationship_types = {row["relationship_type"] for row in projection["relationships"]}

    assert {
        ("RemediationPlan", "addressesFinding", "DefenderAssessment"),
        ("RemediationPlan", "addressesAlert", "SecurityAlert"),
        ("RemediationPlan", "breaksAttackPath", "AttackPath"),
        ("RemediationPlan", "improvesControl", "SecureScoreControl"),
    } <= set(ONTOLOGY_RELATIONSHIP_TYPES)
    assert {
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    } <= relationship_types
    assert any(
        row["relationship_type"] == "addressesFinding"
        and row["object_id"] == "assess-001"
        for row in projection["relationships"]
    )
    distinct = {
        row["relationship_type"]
        for row in projection["relationships"]
        if row["relationship_type"]
        in {"addressesFinding", "addressesAlert", "breaksAttackPath", "improvesControl"}
    }
    assert distinct == {
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    }
    forbidden = ("resolve", "fix", "remediate", "close", "clear")
    assert all(
        all(term not in row["relationship_type"].casefold() for term in forbidden)
        for row in projection["relationships"]
    )
    rel = next(
        row for row in projection["relationships"] if row["relationship_type"] == "addressesFinding"
    )
    assert rel["confidence"] == 1.0
    assert rel["source"] == "remediation-plan-citation"


def test_production_correlator_assignment_reaches_plan_generator():
    planner = remediation_planner()
    planner.generator.defender_correlator = None

    planner.defender_correlator = defender_correlator()
    planner.generate_plans()

    assert any(
        plan["evidence_citations"]
        for plan in planner.repository.list()
    )


def test_plan_projection_records_unresolved_citations_without_synthesized_ids():
    planner, plan, defender_entities = _plan_and_defender_entities()
    broken = copy.deepcopy(plan)
    broken["evidence_citations"][0]["source_id"] = "stale-assessment"
    planner.repository.replace_generation([broken])

    projection = planner.repository.ontology_projection(
        defender_entities=defender_entities
    )

    assert not any(
        row["object_id"] == "stale-assessment"
        for row in projection["relationships"]
    )
    assert not any(
        row["entity_id"] == "stale-assessment"
        for row in projection["entities"]
    )
    assert any(
        row["citation"]["source_id"] == "stale-assessment"
        and row["reason"] == "Defender entity not found"
        for row in projection["pending_relationships"]
    )


def test_plan_projection_rejects_mistyped_and_cross_resource_citations():
    planner, plan, defender_entities = _plan_and_defender_entities()
    broken = copy.deepcopy(plan)
    broken["evidence_citations"] = [
        {
            **broken["evidence_citations"][0],
            "source_type": "alert",
            "source_id": "assess-001",
        },
        {
            **broken["evidence_citations"][0],
            "source_type": "assessment",
            "source_id": "assess-other-resource",
        },
    ]
    defender_entities.append(
        _ontology_entity(
            "assess-other-resource",
            "DefenderAssessment",
            {"targetResourceId": "/subscriptions/sub-1/resourceGroups/other"},
        )
    )
    planner.repository.replace_generation([broken])

    projection = planner.repository.ontology_projection(
        defender_entities=defender_entities
    )

    assert not (_DEFENDER_PREDICATES & {
        row["relationship_type"] for row in projection["relationships"]
    })
    reasons = {row["reason"] for row in projection["pending_relationships"]}
    assert reasons == {
        "Defender entity type does not match citation source type",
        "Defender entity is not associated with plan resource",
    }


def test_plan_projection_still_keeps_existing_plan_relationships():
    planner, plan, defender_entities = _plan_and_defender_entities()
    planner.repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="operator@example.com",
        reason="Approved for planning handoff",
        scope={"subscription": ["sub-1"]},
        action_version=plan["action_version"],
    )
    projection = planner.repository.ontology_projection(
        defender_entities=defender_entities
    )
    rels = {row["relationship_type"] for row in projection["relationships"]}
    assert {
        "requiresApproval",
        "hasStep",
        "hasRollbackPlan",
        "hasSimulation",
        "mitigatesRisk",
        "protectsService",
        "requiresPlan",
        "hasApprovalDecision",
    } <= rels


def test_plan_relationship_rows_publish_through_sync_path():
    planner, _plan, defender_entities = _plan_and_defender_entities()
    projection = planner.repository.ontology_projection(
        defender_entities=defender_entities
    )
    entities, relationships = remediation_plan_ontology_rows(
        projection,
        "run-1",
        "2026-08-31T00:00:00Z",
    )
    published = {row["predicate"] for row in relationships}
    assert {
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    } <= published
    assert any(
        row["predicate"] == "requiresPlan"
        and row["subject_type"] == "Application"
        and row["object_type"] == "RemediationPlan"
        for row in relationships
    )
    assert OntologyValidator().validate(
        [*entities, *defender_entities],
        relationships,
    ).passed


def test_sync_writes_all_plan_defender_relationships_to_published_dataset(
    tmp_path: Path,
):
    planner, plan, defender_entities = _plan_and_defender_entities()
    planner.repository.replace_generation([plan])
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)

    class MapperWithDefenderEntities(InventoryDatasetMapper):
        def load(self, *args, **kwargs):
            datasets = super().load(*args, **kwargs)
            run_id = args[1]
            datasets["ontology_entities"].extend(
                [
                    {
                        **row,
                        "ingestion_run_id": run_id,
                    }
                    for row in defender_entities
                ]
            )
            return datasets

    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace",
            "lakehouse",
            local_root=lakehouse,
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
        mapper=MapperWithDefenderEntities(),
        remediation_plan_reader=planner.repository.ontology_projection,
    )

    service.sync(requested_scope={"subscription": ["sub-1"]})

    rows = _delta_rows(lakehouse / "Tables/ontology_relationships")
    assert _DEFENDER_PREDICATES <= {
        row["predicate"]
        for row in rows
        if row["subject_id"] == plan["plan_id"].casefold()
    }


def test_production_runtime_shares_and_durably_reloads_plan_projection(
    tmp_path: Path,
):
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)
    config = FabricRuntimeConfig(
        auth=FabricAuthConfig(mode="managed_identity"),
        source_data_root=source,
        workspace_id="workspace",
        lakehouse_id="lakehouse",
        local_onelake_root=lakehouse,
    )
    _planner, plan, _defender_entities = _plan_and_defender_entities()

    first = build_runtime(config)
    assert first.service.remediation_plan_reader is not None
    first.remediation_repository.replace_generation([plan])

    second = build_runtime(config)
    assert second.service.remediation_plan_reader is not None
    assert plan["plan_id"] in {
        row["entity_id"]
        for row in second.service.remediation_plan_reader([])["entities"]
    }


def test_plan_repository_persists_plans_through_shared_document_store(
    tmp_path: Path,
):
    _planner, plan, _defender_entities = _plan_and_defender_entities()
    store = OneLakeDocumentStore(tmp_path)
    writer = PlanRepository(plan_document_store=store)
    writer.replace_generation([plan])

    reader = PlanRepository(plan_document_store=store)

    assert reader.get(plan["plan_id"]) == plan


def test_docs_and_schema_remain_aligned_with_registry_predicates():
    docs = Path("docs/ontology-model.md").read_text()
    schema = Path("ontology-schema.md").read_text()
    for predicate in (
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    ):
        assert predicate in docs
        assert predicate in schema
    for phrase in (
        "record intent to address",
        "not resolved until post-change evidence confirms it",
        "canonical resource ID",
        "separate meanings",
    ):
        assert phrase in docs
        assert phrase in schema
