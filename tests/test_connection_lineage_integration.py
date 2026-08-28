"""End-to-end proof that a real ingestion run carries connection identity.

These tests close the gap where ``SubscriptionConnection``/``ConnectionHealth``
entities only materialized for hand-constructed rows: they drive the genuine
Normalizer -> dataset mapper -> EntityBuilder -> RelationshipBuilder chain and
assert both the entities and the Business Service / Environment lineage edges.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fabric.dataset_mapper import _entity_row
from onboarding.graph_normalize import Normalizer
from onboarding.metadata import BusinessMetadata
from onboarding.registry import ConnectionRegistry, RegistryConflictError
from onboarding.runtime import connection_context
from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder
from ontology.subscription_connection import (
    ConnectionHealth,
    CredentialReference,
    SubscriptionConnection,
)
from semantic.semantic_engine import SemanticEngine
from semantic.semantic_indexes import SemanticIndexes

TENANT = "tenant-1"
SUBSCRIPTION = "sub-1"
FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"


def make_connection(**metadata_overrides) -> SubscriptionConnection:
    business = {
        "business_service": "Retail Banking",
        "application": "Payments",
        "environment": "production",
        "project_owner": "ops@example.com",
        "support_team": "Platform SRE",
        "criticality": "high",
        **metadata_overrides,
    }
    return SubscriptionConnection(
        connection_id="prod-core",
        name="Production Core",
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        credential=CredentialReference(
            credential_id="prod-core",
            kind="service_principal",
            client_id="client-1",
            tenant_id=TENANT,
            secret_ref="env://SPN_SECRET",
        ),
        metadata={"business": BusinessMetadata.from_mapping(business).to_dict()},
    )


def run_pipeline(connection: SubscriptionConnection | None):
    """Drive the production path: normalize -> map -> ontology entities/edges."""
    payload = json.loads(FIXTURE.read_text())
    context = connection_context(connection) if connection else {}
    graph = Normalizer(context).normalize(payload, datetime(2026, 1, 1, tzinfo=UTC))
    rows = [
        _entity_row(row, entity_type, "run-1")
        for entity_type, entities in graph.entities.items()
        for row in entities
    ]
    entities = EntityBuilder().build(rows, "run-1")
    relationships = RelationshipBuilder().build(entities, "run-1")
    return entities, relationships


def by_type(entities, entity_type):
    return [row for row in entities if row["entity_type"] == entity_type]


def test_real_ingestion_stamps_connection_identity_on_every_entity():
    payload = json.loads(FIXTURE.read_text())
    context = connection_context(make_connection())
    graph = Normalizer(context).normalize(payload, datetime(2026, 1, 1, tzinfo=UTC))

    emitted = [row for rows in graph.entities.values() for row in rows]
    assert emitted, "fixture should produce entities"
    for row in emitted:
        assert row["connection_id"] == "prod-core"
        assert row["connection_name"] == "Production Core"


def test_normalizer_without_connection_context_is_unchanged():
    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 1, 1, tzinfo=UTC))
    for rows in graph.entities.values():
        for row in rows:
            assert "connection_id" not in row


def test_real_ingestion_produces_connection_entities():
    entities, _ = run_pipeline(make_connection())

    connections = by_type(entities, "SubscriptionConnection")
    assert len(connections) == 1
    assert connections[0]["name"] == "Production Core"
    assert connections[0]["subscription_id"] == SUBSCRIPTION


def test_real_ingestion_without_connection_emits_no_connection_entities():
    entities, _ = run_pipeline(None)
    assert by_type(entities, "SubscriptionConnection") == []


def test_real_ingestion_builds_full_business_lineage():
    entities, relationships = run_pipeline(make_connection())
    connection = by_type(entities, "SubscriptionConnection")[0]

    outgoing = {
        row["predicate"]: row["object_type"]
        for row in relationships
        if row["subject_id"] == connection["resource_id"]
    }
    assert outgoing["mapped_to"] == "Environment"
    assert outgoing["supports"] == "BusinessService"

    incoming = {
        row["predicate"]
        for row in relationships
        if row["object_id"] == connection["resource_id"]
    }
    assert {"owns", "contains"} <= incoming


def test_connection_health_entity_materializes_from_ingestion():
    connection = make_connection()
    context = connection_context(connection)
    context["connection_health_status"] = "healthy"

    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer(context).normalize(payload, datetime(2026, 1, 1, tzinfo=UTC))
    rows = [
        _entity_row(row, entity_type, "run-1")
        for entity_type, entities in graph.entities.items()
        for row in entities
    ]
    entities = EntityBuilder().build(rows, "run-1")
    assert by_type(entities, "ConnectionHealth")


def test_connection_context_carries_business_metadata():
    context = connection_context(make_connection())
    assert context["environment_name"] == "production"
    assert context["business_service_name"] == "Retail Banking"
    assert context["application_name"] == "Payments"
    assert "client_secret" not in context
    assert "secret_ref" not in context


def test_registry_rejects_concurrent_clobbering(tmp_path):
    registry = ConnectionRegistry(tmp_path)
    connection = make_connection()
    registry.add(connection)

    stale_revision = registry.revision()
    registry.save(connection.__class__.from_mapping({**connection.to_dict(), "name": "First"}))

    with pytest.raises(RegistryConflictError):
        registry.save(
            connection.__class__.from_mapping({**connection.to_dict(), "name": "Second"}),
            expected_revision=stale_revision,
        )


def test_registry_revision_advances_on_each_write(tmp_path):
    registry = ConnectionRegistry(tmp_path)
    connection = make_connection()
    assert registry.revision() == 0
    registry.add(connection)
    assert registry.revision() == 1
    registry.save(connection)
    assert registry.revision() == 2


def _build_engine(*connections: SubscriptionConnection) -> SemanticEngine:
    """Run the real ingestion pipeline for each connection and wrap the merged
    ontology graph in a SemanticEngine, mirroring how the API layer will read
    the ontology.
    """
    all_entities: list[dict] = []
    all_relationships: list[dict] = []
    for index, connection in enumerate(connections, start=1):
        entities, relationships = run_pipeline(connection)
        all_entities.extend(entities)
        all_relationships.extend(relationships)
    indexes = SemanticIndexes(all_entities, all_relationships)
    return SemanticEngine(
        indexes,
        knowledge_version="v1",
        freshness="2026-01-01T00:00:00Z",
    )


def test_subscription_connection_context_resolves_by_display_name_and_connection_id():
    """Regression test for G1: SemanticEngine.get_subscription_connection_context
    used to raise LookupError for every input because it resolved the bare
    subscription GUID against Subscription entities keyed as
    ``/subscriptions/{id}``, and looked up connections only by display name.
    """
    connection = SubscriptionConnection(
        connection_id="prod-core",
        name="Production Core",
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        credential=CredentialReference(
            credential_id="prod-core",
            kind="service_principal",
            client_id="client-1",
            tenant_id=TENANT,
            secret_ref="env://SPN_SECRET",
        ),
        health=ConnectionHealth(connection_id="prod-core", status="healthy"),
        metadata={
            "business": BusinessMetadata.from_mapping(
                {
                    "business_service": "Retail Banking",
                    "application": "Payments",
                    "environment": "production",
                    "project_owner": "ops@example.com",
                    "support_team": "Platform SRE",
                    "criticality": "high",
                }
            ).to_dict()
        },
    )
    engine = _build_engine(connection)

    by_name = engine.get_subscription_connection_context("Production Core")
    by_id = engine.get_subscription_connection_context("prod-core")

    for context in (by_name, by_id):
        assert context["subject"]["entity_type"] == "SubscriptionConnection"
        assert context["sections"]["subscription"]["name"] == "Contoso Production"
        assert context["sections"]["environment_mappings"][0]["environment"]["name"] == "production"
        assert context["sections"]["business_service_linkages"][0]["business_service"]["name"] == "Retail Banking"


def test_health_for_connection_isolates_overlapping_connection_ids():
    """Regression test for G2: health_for_connection("prod") used to also
    return the health entity for the unrelated connection "prod-core" because
    of a name prefix-match. Health lookups must only ever return the queried
    connection's own health entity.
    """
    prod_core = SubscriptionConnection(
        connection_id="prod-core",
        name="Production Core",
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        credential=CredentialReference(
            credential_id="prod-core",
            kind="service_principal",
            client_id="client-1",
            tenant_id=TENANT,
            secret_ref="env://SPN_SECRET",
        ),
        health=ConnectionHealth(connection_id="prod-core", status="healthy"),
        metadata={
            "business": BusinessMetadata.from_mapping(
                {
                    "business_service": "Retail Banking",
                    "application": "Payments",
                    "environment": "production",
                    "project_owner": "ops@example.com",
                    "support_team": "Platform SRE",
                    "criticality": "high",
                }
            ).to_dict()
        },
    )
    prod = SubscriptionConnection(
        connection_id="prod",
        name="Prod Short",
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        credential=CredentialReference(
            credential_id="prod",
            kind="service_principal",
            client_id="client-2",
            tenant_id=TENANT,
            secret_ref="env://SPN_SECRET2",
        ),
        health=ConnectionHealth(connection_id="prod", status="degraded"),
        metadata={
            "business": BusinessMetadata.from_mapping(
                {
                    "business_service": "Retail Banking",
                    "application": "Payments",
                    "environment": "production",
                    "project_owner": "ops@example.com",
                    "support_team": "Platform SRE",
                    "criticality": "high",
                }
            ).to_dict()
        },
    )

    entities_core, relationships_core = run_pipeline(prod_core)
    entities_prod, relationships_prod = run_pipeline(prod)
    indexes = SemanticIndexes(
        entities_core + entities_prod,
        relationships_core + relationships_prod,
    )

    core_health = indexes.health_for_connection("prod-core")
    short_health = indexes.health_for_connection("prod")

    assert len(core_health) == 1
    assert len(short_health) == 1
    assert core_health != short_health
    assert indexes.entities[core_health[0]]["name"] == "prod-core status healthy"
    assert indexes.entities[short_health[0]]["name"] == "prod status degraded"
