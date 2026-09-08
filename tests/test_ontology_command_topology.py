from __future__ import annotations

import json
from datetime import UTC, datetime

from api.app import create_app
from api.routers.ontology_discovery import OntologyDiscoveryApi
from onboarding.registry import ConnectionRegistry
from onboarding.service import SubscriptionOnboardingService
from ontology.ontology_validator import OntologyValidator
from ontology.subscription_connection import SubscriptionConnection
from ontology_discovery.command_intake import (
    CommandIntakeService,
    CoordinatorCommandConsumer,
    PublisherCommandConsumer,
)
from ontology_discovery.dispatch_store import PublisherDispatchStore
from ontology_discovery.generation_resolver import GenerationResolver
from ontology_discovery.publisher import OntologyGenerationPublisher
from ontology_discovery.publisher_worker import PublisherIntakeAdapter, PublisherWorker
from ontology_discovery.runtime import CoordinatorIntakeAdapter
from ontology_discovery.store import OntologyRunStore
from storage.datasets import DatasetStore
from storage.locking import MonotonicFenceAllocator
from storage.onelake_documents import OneLakeDocumentStore

NOW = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
CONSUMERS = ("api", "fabric", "agent", "export", "semantic")


def _candidate(generation_id: str, source_generation: str) -> dict[str, object]:
    entity = {
        "tenant_id": "tenant-a",
        "subscription_id": "subscription-a",
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": "run-18",
        "resource_type": "test/resource",
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": NOW.isoformat(),
        "retired_at": "",
        "ontology_version": "v1",
    }
    entities = [
        {**entity, "resource_id": "vm-1", "entity_type": "VirtualMachine", "name": "vm-1"},
        {**entity, "resource_id": "app-1", "entity_type": "Application", "name": "app-1"},
    ]
    relationships = [
        {
            "tenant_id": "tenant-a",
            "subscription_id": "subscription-a",
            "resource_id": "relationship://vm-app",
            "timestamp": NOW.isoformat(),
            "change_version": "v1",
            "ingestion_run_id": "run-18",
            "subject_id": "vm-1",
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_id": "app-1",
            "object_type": "Application",
            "source": "deterministic",
            "payload_json": "{}",
            "lineage_json": "{}",
            "lifecycle_status": "active",
            "valid_from": NOW.isoformat(),
            "retired_at": "",
            "ontology_version": "v1",
            "confidence": 1.0,
        }
    ]
    return {
        "generation_id": generation_id,
        "source_generation": source_generation,
        "entities": entities,
        "relationships": relationships,
        "proposal_lineage": [],
        "decision_lineage": ["hard-shadow"],
        "policy_version": "ontology-policy/v1",
        "schema_version": "ontology-generation/v1",
    }


def _publisher(dispatch_root: str, publication_root: str) -> PublisherWorker:
    dataset = DatasetStore(publication_root)
    storage = dataset.authoritative_publisher(
        publisher_identity="publisher-uai",
        approved_publisher_identity="publisher-uai",
    )
    return PublisherWorker(
        dispatches=PublisherDispatchStore(dispatch_root).publisher(),
        publisher=OntologyGenerationPublisher(
            storage,
            validator=OntologyValidator(
                allowed_triples={
                    ("VirtualMachine", "member_of", "Application")
                }
            ),
            approved_publisher_identity="publisher-uai",
        ),
        publisher_identity="publisher-uai",
        owner_id="publisher-worker-18",
        fence_allocator=MonotonicFenceAllocator(
            OneLakeDocumentStore(dispatch_root)
        ),
        materialize=lambda candidate: {
            "status": "completed",
            "generation_id": candidate.generation_id,
        },
        consumer_check=lambda _stage, _generation: {
            family: True for family in CONSUMERS
        },
        now=lambda: NOW,
    )


def _api(
    *,
    connection_root: str,
    command_root: str,
    state_root: str,
    publication_root: str,
) -> OntologyDiscoveryApi:
    onboarding = SubscriptionOnboardingService(connection_root, clock=lambda: NOW)
    return OntologyDiscoveryApi(
        onboarding=onboarding,
        run_store=OntologyRunStore(
            state_root,
            document_store=OneLakeDocumentStore(state_root),
        ),
        command_intake=CommandIntakeService(command_root),
        connection_reader=ConnectionRegistry(connection_root).get,
        generation_resolver_factory=lambda _connection_id: GenerationResolver(
            DatasetStore(publication_root)
        ),
        clock=lambda: NOW,
    )


def test_manual_publish_and_rollback_survive_every_process_reconstruction(
    tmp_path,
) -> None:
    connection_root = str(tmp_path / "connections")
    command_root = str(tmp_path / "commands")
    state_root = str(tmp_path / "state")
    dispatch_root = str(tmp_path / "dispatch")
    publication_root = str(tmp_path / "publication")
    registry = ConnectionRegistry(connection_root)
    connection = SubscriptionConnection(
        connection_id="connection-a",
        name="connection-a",
        tenant_id="tenant-a",
        subscription_id="subscription-a",
        metadata={"environment": "validation"},
    )
    registry.add(connection)
    service = SubscriptionOnboardingService(
        connection_root,
        ontology_command_intake=CommandIntakeService(command_root),
        clock=lambda: NOW,
    )

    command = service.enqueue_ontology_refresh(
        "connection-a",
        requested_by="operator-a",
        idempotency_key="manual-18",
    )
    assert command["durable_command"]["status"] == "pending"
    state = OntologyRunStore(
        state_root,
        document_store=OneLakeDocumentStore(state_root),
    )
    assert state.list_runs() == []

    assert CoordinatorIntakeAdapter(
        registry=ConnectionRegistry(connection_root),
        commands=CoordinatorCommandConsumer(command_root),
        run_store=state,
        source_generation=lambda _connection: "source-1",
        environment="validation",
        now=lambda: NOW,
    ).process_one()["accepted"] == 1
    run = OntologyRunStore(
        state_root,
        document_store=OneLakeDocumentStore(state_root),
    ).list_runs()[0]
    dispatches = PublisherDispatchStore(dispatch_root)
    dispatches.coordinator().create_publish(
        run_id=run["run_id"],
        connection_id="connection-a",
        source_generation_id="source-1",
        candidate=_candidate("generation-1", "source-1"),
        now=NOW,
    )
    assert _publisher(dispatch_root, publication_root).run_once()["succeeded"] == 1

    dispatches.coordinator().create_publish(
        run_id="run-generation-2",
        connection_id="connection-a",
        source_generation_id="source-2",
        candidate=_candidate("generation-2", "source-2"),
        now=NOW,
    )
    assert _publisher(dispatch_root, publication_root).run_once()["succeeded"] == 1
    reloaded = _api(
        connection_root=connection_root,
        command_root=command_root,
        state_root=state_root,
        publication_root=publication_root,
    )
    generation = reloaded.generation("connection-a")
    assert generation["active_generation"] == "generation-2"
    assert generation["prior_generation"] == "generation-1"
    rollback = reloaded.rollback(
        "connection-a",
        "generation-1",
        expected_etag=generation["pointer_etag"],
        actor="operator-a",
        reason="restore predecessor",
        idempotency_key="rollback-18",
    )
    assert rollback["status"] == "pending"
    intake_result = PublisherIntakeAdapter(
        registry=ConnectionRegistry(connection_root),
        commands=PublisherCommandConsumer(command_root),
        dispatches=PublisherDispatchStore(dispatch_root).publisher(),
        publication=DatasetStore(publication_root).authoritative_publisher(
            publisher_identity="publisher-uai",
            approved_publisher_identity="publisher-uai",
        ),
        owner_id="publisher-worker-18",
        now=lambda: NOW,
    ).process_one()
    rollback_command = CommandIntakeService(command_root).get(
        rollback["command_id"]
    )
    assert intake_result["accepted"] == 1, rollback_command["reason_code"]
    assert _publisher(dispatch_root, publication_root).run_once()["succeeded"] == 1

    final = _api(
        connection_root=connection_root,
        command_root=command_root,
        state_root=state_root,
        publication_root=publication_root,
    )
    assert final.generation("connection-a")["active_generation"] == "generation-1"
    assert final.command(rollback["command_id"])["status"] == "completed"


def test_default_openapi_exposes_complete_ontology_command_surface(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "api"))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv(
        "AIOPS_API_TOKENS",
        json.dumps(
            {
                "ontology-admin-token": {
                    "subject": "admin@example.com",
                    "grants": [{"role": "admin", "scope": {}}],
                }
            }
        ),
    )
    paths = create_app().openapi()["paths"]

    assert "/api/v1/ontology-discovery/runs" in paths
    assert "/api/v1/ontology-discovery/generations/{generation_id}/rollback" in paths
    assert (
        "/api/v1/ontology-discovery/connections/{connection_id}/"
        "maintenance/full-reconciliation-due"
    ) in paths
