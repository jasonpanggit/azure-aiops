"""Comparison-harness proof that the Fabric-native ontology pipeline
reproduces ``ontology.entity_builder.EntityBuilder`` /
``ontology.relationship_builder.RelationshipBuilder`` /
``onboarding.ontology_metadata.generate_ontology_metadata`` faithfully.

Mirrors ``tests/test_topology_pipeline.py``'s style: rather than asserting
against a separately-hand-written expected output, this test feeds the same
fixture input to both (1) the Fabric pipeline's ``derive_entities``/
``derive_relationships``/``derive_ontology_metadata`` wrapper functions and
(2) ``EntityBuilder``/``RelationshipBuilder``/``generate_ontology_metadata``
directly, then asserts the two outputs are identical -- proving the Fabric
pipeline is a faithful pass-through (not a re-implementation) of the exact
Hermes ontology-construction logic, plus exercises the Delta-write path via
the reused ``DeltaWriter``/``OneLakeWriter`` machinery.
"""

from __future__ import annotations

import json

from deltalake import DeltaTable
from ontology_comparison_scenario import ontology_comparison_scenario

from fabric_pipelines.ontology_pipeline import (
    derive_entities,
    derive_ontology_metadata,
    derive_relationships,
    run,
)
from onboarding.ontology_metadata import generate_ontology_metadata
from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder
from storage.onelake_writer import OneLakeWriter

RUN_ID = "ontology-pipeline-test-run"
TIMESTAMP = "2026-08-27T00:00:00Z"

# The full set of entity types Hermes's ``TAG_ENTITY_TYPES``/
# ``RESOURCE_ENTITY_TYPES`` mapping tables plus structural inventory
# entities (Tenant/Subscription/ResourceGroup) and lineage-derived entities
# (ConnectionHealth) can produce -- asserted against
# ``ontology_comparison_scenario()``'s comprehensive fixture below so the
# pipeline's coverage isn't silently narrowed to a convenient subset.
FULL_ENTITY_TYPE_SET = {
    "Tenant",
    "Subscription",
    "ResourceGroup",
    "ManagementGroup",
    "SubscriptionConnection",
    "ConnectionHealth",
    "Environment",
    "Application",
    "BusinessService",
    "BusinessFunction",
    "Owner",
    "SupportTeam",
    "Service",
    "VirtualMachine",
    "ArcServer",
    "KubernetesCluster",
    "Resource",
    "PatchAssessment",
    "PatchInstallation",
    "AdvisorRecommendation",
    "CostActual",
    "VNet",
    "VNetPeering",
    "Subnet",
    "NetworkSecurityGroup",
    "NetworkSecurityRule",
    "RouteTable",
    "Route",
    "NetworkInterface",
    "AzureFirewall",
    "FirewallPolicy",
    "FirewallRuleCollection",
    "FirewallRule",
    "PrivateEndpoint",
    "PrivateDnsZone",
    "NetworkGateway",
    "LoadBalancer",
}

# The complete relationship-predicate vocabulary
# ``ontology.relationship_builder.RelationshipBuilder.build()`` infers,
# spanning structural containment, tag-derived business context,
# subscription-connection lineage, operational (cost/patch/advisor) edges,
# and the full re-derived network topology.
FULL_PREDICATE_SET = {
    "owns",
    "contains",
    "member_of",
    "hosted_on",
    "belongs_to",
    "supports",
    "implements",
    "depends_on",
    "funded_by",
    "owned_by",
    "provides",
    "has_health",
    "mapped_to",
    "runs",
    "deployed_in",
    "managed_by",
    "affects",
    "incurs_cost",
    "evaluates",
    "records_installation_for",
    "hasPeering",
    "protectedBy",
    "routedBy",
    "egressesVia",
    "peersWith",
    "hasRule",
    "hasRoute",
    "attachedTo",
    "hasNetworkInterface",
    "enforcesPolicy",
    "hasRuleCollection",
    "exposesPrivately",
    "resolvesFor",
    "loadBalances",
    "hosts",
}


def _resource(**overrides):
    row = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
        "timestamp": TIMESTAMP,
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": "VirtualMachine",
        "name": "vm1",
        "resource_type": "microsoft.compute/virtualmachines",
        "location": "eastus",
        "payload_json": json.dumps(
            {
                "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                "name": "vm1",
                "tenantId": "tenant-1",
                "subscriptionId": "sub-1",
                "resourceGroup": "rg",
                "tags": {
                    "AppName": "Payments API",
                    "Environment": "Production",
                    "BusinessUnit": "Retail",
                    "CostCenter": "CC-42",
                    "Owner": "ops@example.com",
                    "SupportGroup": "SRE",
                    "Service": "Checkout",
                },
            }
        ),
    }
    row.update(overrides)
    return row


def _patch_assessment(**overrides):
    row = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": (
            "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/"
            "virtualmachines/vm1/patchassessmentresults/latest"
        ),
        "timestamp": TIMESTAMP,
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": "PatchAssessment",
        "name": "latest",
        "resource_type": "microsoft.compute/virtualmachines/patchassessmentresults",
        "location": "eastus",
        "payload_json": json.dumps(
            {
                "targetResourceId": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                "tenantId": "tenant-1",
                "subscriptionId": "sub-1",
            }
        ),
    }
    row.update(overrides)
    return row


def _advisor_recommendation(**overrides):
    row = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.advisor/recommendations/rec-1",
        "timestamp": TIMESTAMP,
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": "AdvisorRecommendation",
        "name": "rec-1",
        "resource_type": "microsoft.advisor/recommendations",
        "location": "eastus",
        "payload_json": json.dumps(
            {
                "targetResourceId": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                "tenantId": "tenant-1",
                "subscriptionId": "sub-1",
            }
        ),
    }
    row.update(overrides)
    return row


def _source_rows() -> list[dict]:
    """Minimal 3-row fixture retained for the Delta-write proof (fast,
    doesn't need full ontology breadth to prove the write path works)."""
    return [_resource(), _patch_assessment(), _advisor_recommendation()]


def _full_source_rows() -> list[dict]:
    """The comprehensive fixture covering every Hermes entity type and
    relationship predicate -- used by the parity-assertion tests below."""
    return ontology_comparison_scenario()


def test_derive_entities_matches_entity_builder_output_exactly():
    """Proves ``derive_entities`` is a faithful pass-through: same rows,
    byte-for-byte, as calling ``EntityBuilder().build(...)`` directly --
    exercised against the full Hermes entity-type surface, not a subset."""
    rows = _full_source_rows()
    pipeline_entities = derive_entities(rows, run_id=RUN_ID, timestamp=TIMESTAMP)
    reference_entities = EntityBuilder().build(rows, RUN_ID, timestamp=TIMESTAMP)

    assert pipeline_entities == reference_entities
    entity_types = {row["entity_type"] for row in pipeline_entities}
    assert FULL_ENTITY_TYPE_SET <= entity_types


def test_derive_relationships_matches_relationship_builder_output_exactly():
    """Proves ``derive_relationships`` is a faithful pass-through: same rows,
    byte-for-byte, as calling ``RelationshipBuilder().build(...)`` directly --
    exercised against the full Hermes relationship-predicate vocabulary
    (structural, tag-derived, lineage, operational, and network), not just
    belongsTo/assessedBy/impacts analogs."""
    entities = derive_entities(_full_source_rows(), run_id=RUN_ID, timestamp=TIMESTAMP)

    pipeline_relationships = derive_relationships(entities, RUN_ID)
    reference_relationships = RelationshipBuilder().build(entities, RUN_ID)

    assert pipeline_relationships == reference_relationships
    predicates = {row["predicate"] for row in pipeline_relationships}
    assert FULL_PREDICATE_SET <= predicates


def test_derive_ontology_metadata_matches_generate_ontology_metadata_exactly():
    """Proves ``derive_ontology_metadata`` is a faithful pass-through of
    ``onboarding.ontology_metadata.generate_ontology_metadata`` -- including
    its full static ``RELATIONSHIP_TYPES`` vocabulary (belongsTo/assessedBy/
    impacts) and entity-type schema inference across the full fixture."""
    entities = derive_entities(_full_source_rows(), run_id=RUN_ID, timestamp=TIMESTAMP)

    pipeline_metadata = derive_ontology_metadata(entities)

    by_type: dict[str, list[dict]] = {}
    for row in entities:
        by_type.setdefault(row["entity_type"], []).append(row)
    reference_metadata = generate_ontology_metadata(by_type)

    assert pipeline_metadata == reference_metadata
    assert pipeline_metadata["name"] == "HermesAzureOperationalContext"
    assert FULL_ENTITY_TYPE_SET <= set(pipeline_metadata["entityTypes"])
    assert set(pipeline_metadata["relationshipTypes"]) == {"belongsTo", "assessedBy", "impacts"}


def test_run_writes_ontology_entities_and_relationships_to_delta_tables(tmp_path):
    """Proves the tracer's `<done>` criterion, mirroring
    ``test_pipeline_writes_topology_entities_and_edges_to_delta_tables``:
    rows are actually written to a Delta table via the reused writer
    machinery (not a new writer)."""
    lakehouse_root = tmp_path / "lakehouse"
    onelake = OneLakeWriter("workspace", "lakehouse", local_root=lakehouse_root)

    summary = run(_source_rows(), run_id=RUN_ID, onelake=onelake, timestamp=TIMESTAMP)

    assert summary.entity_count > 0
    assert summary.relationship_count > 0
    assert summary.entities_write.result.rows_processed == summary.entity_count
    assert summary.relationships_write.result.rows_processed == summary.relationship_count
    assert summary.ontology_metadata["name"] == "HermesAzureOperationalContext"

    entities_table = DeltaTable(str(lakehouse_root / "Tables" / "ontology_entities"))
    relationships_table = DeltaTable(str(lakehouse_root / "Tables" / "ontology_relationships"))
    assert entities_table.to_pyarrow_table().num_rows == summary.entity_count
    assert relationships_table.to_pyarrow_table().num_rows == summary.relationship_count
