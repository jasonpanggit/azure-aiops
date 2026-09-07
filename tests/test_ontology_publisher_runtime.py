from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fabric.auth import FabricAuthConfig
from fabric.config import FabricRuntimeConfig
from onboarding.registry import ConnectionRegistry
from ontology.ontology_validator import OntologyValidator
from ontology.subscription_connection import SubscriptionConnection
from ontology_discovery import publisher_cli
from ontology_discovery.command_intake import (
    CommandIntakeService,
    PublisherCommandConsumer,
    scope_receipt,
)
from ontology_discovery.dispatch_store import PublisherDispatchStore
from ontology_discovery.publisher import OntologyGenerationPublisher
from ontology_discovery.publisher_cli import (
    PublisherRuntimeConfig,
    publisher_fabric_config,
)
from ontology_discovery.publisher_worker import PublisherIntakeAdapter, PublisherWorker
from storage.datasets import DatasetStore
from storage.locking import MonotonicFenceAllocator
from storage.onelake_documents import OneLakeDocumentStore

NOW = datetime(2026, 9, 7, 7, 0, tzinfo=UTC)
CONSUMERS = ("api", "fabric", "agent", "export", "semantic")


def _candidate() -> dict[str, object]:
    return {
        "generation_id": "ontology-generation-17",
        "entities": [
            {
                "tenant_id": "tenant-a",
                "subscription_id": "subscription-a",
                "resource_id": "vm-1",
                "timestamp": "2026-09-07T00:00:00Z",
                "change_version": "v1",
                "ingestion_run_id": "run-17",
                "entity_type": "VirtualMachine",
                "name": "vm-1",
                "resource_type": "test/resource",
                "location": "eastus",
                "payload_json": "{}",
                "lineage_json": "{}",
                "semantic_metadata_json": "{}",
                "lifecycle_status": "active",
                "valid_from": "2026-09-07T00:00:00Z",
                "retired_at": "",
                "ontology_version": "v1",
            },
            {
                "tenant_id": "tenant-a",
                "subscription_id": "subscription-a",
                "resource_id": "app-1",
                "timestamp": "2026-09-07T00:00:00Z",
                "change_version": "v1",
                "ingestion_run_id": "run-17",
                "entity_type": "Application",
                "name": "app-1",
                "resource_type": "test/resource",
                "location": "eastus",
                "payload_json": "{}",
                "lineage_json": "{}",
                "semantic_metadata_json": "{}",
                "lifecycle_status": "active",
                "valid_from": "2026-09-07T00:00:00Z",
                "retired_at": "",
                "ontology_version": "v1",
            },
        ],
        "relationships": [
            {
                "tenant_id": "tenant-a",
                "subscription_id": "subscription-a",
                "resource_id": "relationship://vm-app",
                "timestamp": "2026-09-07T00:00:00Z",
                "change_version": "v1",
                "ingestion_run_id": "run-17",
                "subject_id": "vm-1",
                "subject_type": "VirtualMachine",
                "predicate": "member_of",
                "object_id": "app-1",
                "object_type": "Application",
                "source": "deterministic",
                "scope": "tenant-a/subscription-a",
                "payload_json": "{}",
                "lineage_json": "{}",
                "lifecycle_status": "active",
                "valid_from": "2026-09-07T00:00:00Z",
                "retired_at": "",
                "ontology_version": "v1",
                "confidence": 1.0,
            }
        ],
        "proposal_lineage": ["proposal-shadow-17"],
        "decision_lineage": ["decision-shadow-excluded-17"],
        "policy_version": "ontology-policy/v1",
        "schema_version": "ontology-generation/v1",
    }


def _worker(tmp_path, events: list[str], *, fail_materialization: bool = False):
    dispatch_root = str(tmp_path / "dispatch")
    publication_root = str(tmp_path / "publication")
    dataset = DatasetStore(publication_root)
    storage = dataset.authoritative_publisher(
        publisher_identity="publisher-uai",
        approved_publisher_identity="publisher-uai",
    )
    publisher = OntologyGenerationPublisher(
        storage,
        validator=OntologyValidator(
            allowed_triples={("VirtualMachine", "member_of", "Application")}
        ),
        approved_publisher_identity="publisher-uai",
    )

    def materialize(candidate):
        events.append("fabric")
        if fail_materialization:
            raise RuntimeError("fabric unavailable")
        return {"status": "completed", "generation_id": candidate.generation_id}

    def check(stage: str, generation_id: str):
        events.extend(f"{stage}:{family}" for family in CONSUMERS)
        return {family: True for family in CONSUMERS}

    worker = PublisherWorker(
        dispatches=PublisherDispatchStore(dispatch_root).publisher(),
        publisher=publisher,
        publisher_identity="publisher-uai",
        owner_id="publisher-worker-17",
        fence_allocator=MonotonicFenceAllocator(
            OneLakeDocumentStore(dispatch_root)
        ),
        materialize=materialize,
        consumer_check=check,
        now=lambda: NOW,
    )
    return dispatch_root, storage, worker


def test_worker_consumes_coordinator_dispatch_in_fixed_visibility_order(tmp_path):
    events: list[str] = []
    dispatch_root, storage, worker = _worker(tmp_path, events)
    dispatch, _ = PublisherDispatchStore(dispatch_root).coordinator().create_publish(
        run_id="ODR-17",
        connection_id="connection-a",
        source_generation_id="source-17",
        candidate=_candidate(),
        now=NOW,
    )

    result = worker.run_once(now=NOW, limit=1)

    assert result == {"selected": 1, "succeeded": 1, "failed": 0, "contended": 0}
    durable = PublisherDispatchStore(dispatch_root).publisher().get_publish(
        dispatch["dispatch_id"]
    )
    assert durable["status"] == "succeeded"
    assert [receipt["step"] for receipt in durable["receipts"]] == [
        "immutable_stage",
        "persisted_validation",
        "staged_compatibility",
        "fabric_materialization",
        "final_preconditions",
        "pointer_cas",
        "post_check",
    ]
    assert events == [
        *(f"staged:{family}" for family in CONSUMERS),
        "fabric",
        *(f"post:{family}" for family in CONSUMERS),
    ]
    assert storage.read_pointer().pointer.active_generation == "ontology-generation-17"
    assert all(
        row["source"] != "model"
        for row in storage.read_generation("ontology-generation-17")["relationships"]
    )


def test_fabric_failure_never_exposes_generation_and_restart_uses_same_payload(
    tmp_path,
):
    events: list[str] = []
    dispatch_root, storage, worker = _worker(
        tmp_path, events, fail_materialization=True
    )
    dispatch, _ = PublisherDispatchStore(dispatch_root).coordinator().create_publish(
        run_id="ODR-17",
        connection_id="connection-a",
        source_generation_id="source-17",
        candidate=_candidate(),
        now=NOW,
    )

    assert worker.run_once(now=NOW, limit=1)["failed"] == 1
    assert storage.read_pointer().pointer is None
    failed = PublisherDispatchStore(dispatch_root).publisher().get_publish(
        dispatch["dispatch_id"]
    )
    assert failed["status"] == "retrying"
    assert failed["candidate"] == _candidate()
    assert [row["step"] for row in failed["receipts"]] == [
        "immutable_stage",
        "persisted_validation",
        "staged_compatibility",
    ]

    resumed_events: list[str] = []
    _, _, resumed = _worker(tmp_path, resumed_events)
    assert resumed.run_once(now=NOW, limit=1)["succeeded"] == 1
    assert storage.read_pointer().pointer.active_generation == "ontology-generation-17"


def test_publisher_dispatch_view_cannot_create_or_replace_publish_payload(tmp_path):
    publisher = PublisherDispatchStore(str(tmp_path / "dispatch")).publisher()

    assert not hasattr(publisher, "create_publish")
    assert not hasattr(publisher, "replace_publish")
    with pytest.raises(TypeError):
        PublisherDispatchStore(state_root=str(tmp_path / "state"))  # type: ignore[call-arg]


def test_rollback_intake_reauthorizes_before_authoritative_dispatch(tmp_path):
    connection_root = str(tmp_path / "connections")
    command_root = str(tmp_path / "commands")
    dispatch_root = str(tmp_path / "dispatch")
    registry = ConnectionRegistry(connection_root)
    connection = SubscriptionConnection(
        connection_id="connection-a",
        name="connection-a",
        tenant_id="tenant-a",
        subscription_id="subscription-a",
        metadata={"environment": "production"},
    )
    registry.add(connection)
    _dispatch_root, storage, worker = _worker(tmp_path, [])
    first, _ = PublisherDispatchStore(dispatch_root).coordinator().create_publish(
        run_id="ODR-17",
        connection_id="connection-a",
        source_generation_id="source-17",
        candidate=_candidate(),
        now=NOW,
    )
    assert worker.run_once(now=NOW)["succeeded"] == 1
    pointer = storage.read_pointer()
    command = CommandIntakeService(command_root).enqueue_rollback(
        actor_hash="actor-hash",
        connection_id="connection-a",
        action="ontology.publication.rollback",
        effective_scope_hash=scope_receipt(
            connection, "ontology.publication.rollback"
        ),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        idempotency_key="rollback-17",
        reason="validated recovery",
        target_generation_id="ontology-generation-17",
        observed_active_generation=pointer.pointer.active_generation,
        observed_pointer_etag=pointer.etag,
    )
    intake = PublisherIntakeAdapter(
        registry=ConnectionRegistry(connection_root),
        commands=PublisherCommandConsumer(command_root),
        dispatches=PublisherDispatchStore(dispatch_root).publisher(),
        publication=storage,
        owner_id="publisher-worker-17",
        now=lambda: NOW,
    )

    assert intake.process_one() == {"accepted": 1, "denied": 0, "contended": 0}
    durable = CommandIntakeService(command_root).get(command["command_id"])
    assert durable["status"] == "completed"
    assert durable["authorization_audit"]["outcome"] == "authorized"
    rollback = PublisherDispatchStore(dispatch_root).publisher().list_due_rollback(
        now=NOW
    )
    assert len(rollback) == 1
    assert rollback[0]["target_generation_id"] == "ontology-generation-17"
    assert rollback[0]["source_command_id"] == command["command_id"]
    assert rollback[0]["reason_hash"]
    assert first["candidate"] == _candidate()


def test_stale_rollback_intake_is_denied_without_dispatch(tmp_path):
    connection_root = str(tmp_path / "connections")
    command_root = str(tmp_path / "commands")
    dispatch_root = str(tmp_path / "dispatch")
    registry = ConnectionRegistry(connection_root)
    connection = SubscriptionConnection(
        connection_id="connection-a",
        name="connection-a",
        tenant_id="tenant-a",
        subscription_id="subscription-a",
        metadata={"environment": "production"},
    )
    registry.add(connection)
    _dispatch_root, storage, worker = _worker(tmp_path, [])
    PublisherDispatchStore(dispatch_root).coordinator().create_publish(
        run_id="ODR-17",
        connection_id="connection-a",
        source_generation_id="source-17",
        candidate=_candidate(),
        now=NOW,
    )
    worker.run_once(now=NOW)
    command = CommandIntakeService(command_root).enqueue_rollback(
        actor_hash="actor-hash",
        connection_id="connection-a",
        action="ontology.publication.rollback",
        effective_scope_hash=scope_receipt(
            connection, "ontology.publication.rollback"
        ),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        idempotency_key="rollback-stale",
        reason="stale request",
        target_generation_id="ontology-generation-17",
        observed_active_generation="older-generation",
        observed_pointer_etag='"older-etag"',
    )

    result = PublisherIntakeAdapter(
        registry=ConnectionRegistry(connection_root),
        commands=PublisherCommandConsumer(command_root),
        dispatches=PublisherDispatchStore(dispatch_root).publisher(),
        publication=storage,
        owner_id="publisher-worker-17",
        now=lambda: NOW,
    ).process_one()

    assert result == {"accepted": 0, "denied": 1, "contended": 0}
    assert CommandIntakeService(command_root).get(command["command_id"])[
        "reason_code"
    ] == "stale_pointer_observation"
    assert (
        PublisherDispatchStore(dispatch_root)
        .publisher()
        .list_due_rollback(now=NOW)
        == []
    )


def test_publisher_runtime_rebinds_fabric_managed_identity_and_exact_roots(tmp_path):
    roots = {
        "AIOPS_CONNECTION_HOME": str(tmp_path / "connections"),
        "AIOPS_ONTOLOGY_COMMAND_HOME": str(tmp_path / "commands"),
        "AIOPS_ONTOLOGY_DISPATCH_HOME": str(tmp_path / "dispatch"),
        "AIOPS_ONTOLOGY_PUBLICATION_HOME": str(tmp_path / "publication"),
        "AIOPS_FABRIC_CONFIG": str(tmp_path / "fabric.yaml"),
        "AIOPS_IDENTITY_CLASS": "publisher",
        "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID": "publisher-client-id",
        "AZURE_CLIENT_ID": "publisher-client-id",
        "AIOPS_RUNTIME_MODE": "local",
    }
    config = PublisherRuntimeConfig.from_env(roots)
    assert config.capabilities == {
        "connection": frozenset({"read"}),
        "command": frozenset({"claim_rollback", "status"}),
        "state": frozenset(),
        "dispatch": frozenset(
            {"claim_publish", "claim_rollback", "status", "create_rollback"}
        ),
        "publication": frozenset({"read", "write", "stage", "pointer"}),
    }
    assert set(config.roots) == {
        "connection",
        "command",
        "dispatch",
        "publication",
    }

    loaded = FabricRuntimeConfig(
        auth=FabricAuthConfig(
            mode="managed_identity",
            managed_identity_client_id="api-client-id",
        ),
        source_data_root=tmp_path / "source",
    )
    rebound = publisher_fabric_config(loaded, config.publisher_client_id)
    assert rebound == replace(
        loaded,
        auth=FabricAuthConfig(
            mode="managed_identity",
            managed_identity_client_id="publisher-client-id",
        ),
    )


def test_explicit_rollback_uses_newer_fence_and_restores_retained_generation(
    tmp_path,
):
    events: list[str] = []
    dispatch_root, storage, worker = _worker(tmp_path, events)
    coordinator = PublisherDispatchStore(dispatch_root).coordinator()
    coordinator.create_publish(
        run_id="ODR-17",
        connection_id="connection-a",
        source_generation_id="source-17",
        candidate=_candidate(),
        now=NOW,
    )
    assert worker.run_once(now=NOW)["succeeded"] == 1
    second_candidate = {
        **_candidate(),
        "generation_id": "ontology-generation-18",
    }
    coordinator.create_publish(
        run_id="ODR-18",
        connection_id="connection-a",
        source_generation_id="source-18",
        candidate=second_candidate,
        now=NOW,
    )
    assert worker.run_once(now=NOW)["succeeded"] == 1
    current = storage.read_pointer()
    assert current.pointer.active_generation == "ontology-generation-18"

    connection_root = str(tmp_path / "connections")
    command_root = str(tmp_path / "commands")
    registry = ConnectionRegistry(connection_root)
    connection = SubscriptionConnection(
        connection_id="connection-a",
        name="connection-a",
        tenant_id="tenant-a",
        subscription_id="subscription-a",
        metadata={"environment": "production"},
    )
    registry.add(connection)
    CommandIntakeService(command_root).enqueue_rollback(
        actor_hash="actor-hash",
        connection_id="connection-a",
        action="ontology.publication.rollback",
        effective_scope_hash=scope_receipt(
            connection, "ontology.publication.rollback"
        ),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        idempotency_key="rollback-to-17",
        reason="consumer regression",
        target_generation_id="ontology-generation-17",
        observed_active_generation="ontology-generation-18",
        observed_pointer_etag=current.etag,
    )
    intake = PublisherIntakeAdapter(
        registry=registry,
        commands=PublisherCommandConsumer(command_root),
        dispatches=PublisherDispatchStore(dispatch_root).publisher(),
        publication=storage,
        owner_id="publisher-worker-17",
        now=lambda: NOW,
    )
    assert intake.process_one()["accepted"] == 1

    assert worker.run_once(now=NOW)["succeeded"] == 1
    restored = storage.read_pointer()
    assert restored.pointer.active_generation == "ontology-generation-17"
    assert restored.pointer.prior_generation == "ontology-generation-18"
    assert restored.pointer.fence > current.pointer.fence


def test_runtime_builder_passes_only_publisher_identity_to_fabric(
    tmp_path, monkeypatch
):
    captured: list[FabricRuntimeConfig] = []
    loaded = FabricRuntimeConfig(
        auth=FabricAuthConfig(
            mode="service_principal",
            tenant_id="tenant",
            client_id="api-client-id",
        ),
        source_data_root=tmp_path / "fabric-source",
        local_onelake_root=tmp_path / "lakehouse",
    )
    monkeypatch.setattr(
        publisher_cli.FabricRuntimeConfig,
        "load",
        lambda _path: loaded,
    )

    class Fabric:
        service = object()

    def capture(config):
        captured.append(config)
        return Fabric()

    monkeypatch.setattr(publisher_cli, "build_runtime", capture)
    config = PublisherRuntimeConfig.from_env(
        {
            "AIOPS_CONNECTION_HOME": str(tmp_path / "connections"),
            "AIOPS_ONTOLOGY_COMMAND_HOME": str(tmp_path / "commands"),
            "AIOPS_ONTOLOGY_DISPATCH_HOME": str(tmp_path / "dispatch"),
            "AIOPS_ONTOLOGY_PUBLICATION_HOME": str(tmp_path / "publication"),
            "AIOPS_FABRIC_CONFIG": str(tmp_path / "fabric.yaml"),
            "AIOPS_IDENTITY_CLASS": "publisher",
            "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID": "publisher-client-id",
            "AZURE_CLIENT_ID": "publisher-client-id",
            "AIOPS_RUNTIME_MODE": "local",
        }
    )

    publisher_cli.build_publisher_runtime(config)

    assert len(captured) == 1
    assert captured[0].auth == FabricAuthConfig(
        mode="managed_identity",
        managed_identity_client_id="publisher-client-id",
    )
