from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from onboarding.registry import ConnectionRegistry
from ontology.subscription_connection import CredentialReference, SubscriptionConnection
from ontology_discovery import cli
from ontology_discovery.command_intake import (
    CommandIntakeService,
    CoordinatorCommandConsumer,
    scope_receipt,
)
from ontology_discovery.dispatch_store import PublisherDispatchStore
from ontology_discovery.runtime import (
    CoordinatorIntakeAdapter,
    EligibleConnectionScheduler,
    ProductionRuntimeConfig,
    validate_capability_roots,
)
from ontology_discovery.store import OntologyRunStore
from storage.onelake_documents import OneLakeDocumentStore

NOW = datetime(2026, 9, 7, 6, 30, tzinfo=UTC)


EXPECTED_CAPABILITY_MATRIX = {
    "api": {
        "connection": {"read"},
        "command": {"create", "read", "status"},
        "state": {"read"},
        "dispatch": set(),
        "publication": {"read"},
    },
    "coordinator": {
        "connection": {"read"},
        "command": {"claim_manual", "claim_maintenance", "status"},
        "state": {"read", "write"},
        "dispatch": {"create_publish", "read_publish"},
        "publication": set(),
    },
    "publisher": {
        "connection": {"read"},
        "command": {"claim_rollback", "status"},
        "state": set(),
        "dispatch": {
            "claim_publish",
            "claim_rollback",
            "status",
            "create_rollback",
        },
        "publication": {"read", "write", "stage", "pointer"},
    },
}


def _connection(connection_id: str, *, active: bool = True) -> SubscriptionConnection:
    return SubscriptionConnection(
        connection_id=connection_id,
        name=connection_id,
        tenant_id="tenant-a",
        subscription_id=f"subscription-{connection_id}",
        is_active=active,
        metadata={"environment": "production"},
    )


def _registry(root, *connection_ids: str) -> ConnectionRegistry:
    registry = ConnectionRegistry(str(root))
    for connection_id in connection_ids:
        registry.add(_connection(connection_id))
    return registry


def test_capability_roots_are_explicit_distinct_and_dispatch_only(tmp_path):
    roots = {
        "connection_home": str(tmp_path / "connections"),
        "command_home": str(tmp_path / "commands"),
        "state_home": str(tmp_path / "state"),
        "dispatch_home": str(tmp_path / "dispatch"),
    }

    assert validate_capability_roots(**roots) == roots
    with pytest.raises(ValueError, match="distinct"):
        validate_capability_roots(**{**roots, "dispatch_home": roots["state_home"]})

    signature = inspect.signature(PublisherDispatchStore)
    assert set(signature.parameters) == {"dispatch_root"}
    with pytest.raises(TypeError):
        PublisherDispatchStore(state_root=roots["state_home"])  # type: ignore[call-arg]


def test_manual_intake_reauthorizes_current_scope_before_creating_run(tmp_path):
    registry = _registry(tmp_path / "connections", "connection-a")
    commands = CommandIntakeService(str(tmp_path / "commands"))
    command = commands.enqueue_manual_run(
        actor_hash="actor-hash",
        connection_id="connection-a",
        action="ontology.discovery.run",
        effective_scope_hash=scope_receipt(
            registry.get("connection-a"), "ontology.discovery.run"
        ),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        idempotency_key="manual-1",
        reason="operator requested refresh",
    )

    run_store = OntologyRunStore(tmp_path / "state" / "runs.json")
    adapter = CoordinatorIntakeAdapter(
        registry=registry,
        commands=CoordinatorCommandConsumer(str(tmp_path / "commands")),
        run_store=run_store,
        source_generation=lambda connection: f"source-{connection.connection_id}",
        now=lambda: NOW,
    )

    result = adapter.process_one()

    assert result == {"accepted": 1, "denied": 0, "contended": 0}
    durable = CommandIntakeService(str(tmp_path / "commands")).get(command["command_id"])
    assert durable["status"] == "completed"
    assert durable["authorization_audit"]["outcome"] == "authorized"
    runs = OntologyRunStore(tmp_path / "state" / "runs.json").list_runs()
    assert len(runs) == 1
    assert runs[0]["connection_id"] == "connection-a"
    assert runs[0]["trigger"] == "manual"


def test_stale_scope_receipt_fails_closed_without_authoritative_state(tmp_path):
    registry = _registry(tmp_path / "connections", "connection-a")
    commands = CommandIntakeService(str(tmp_path / "commands"))
    command = commands.enqueue_manual_run(
        actor_hash="actor-hash",
        connection_id="connection-a",
        action="ontology.discovery.run",
        effective_scope_hash="stale-scope",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        idempotency_key="manual-denied",
        reason="stale request",
    )
    run_store = OntologyRunStore(tmp_path / "state" / "runs.json")
    dispatches = PublisherDispatchStore(str(tmp_path / "dispatch"))
    adapter = CoordinatorIntakeAdapter(
        registry=registry,
        commands=CoordinatorCommandConsumer(str(tmp_path / "commands")),
        run_store=run_store,
        source_generation=lambda connection: f"source-{connection.connection_id}",
        now=lambda: NOW,
    )

    result = adapter.process_one()

    assert result == {"accepted": 0, "denied": 1, "contended": 0}
    durable = commands.get(command["command_id"])
    assert durable["status"] == "denied"
    assert durable["reason_code"] == "scope_receipt_mismatch"
    assert run_store.list_runs() == []
    assert dispatches.coordinator().list_publish() == []


def test_publish_dispatch_is_content_addressed_and_restart_durable(tmp_path):
    dispatch_root = str(tmp_path / "dispatch")
    coordinator = PublisherDispatchStore(dispatch_root).coordinator()
    first, created = coordinator.create_publish(
        run_id="ODR-1",
        connection_id="connection-a",
        source_generation_id="source-a",
        candidate={
            "generation_id": "ontology-a",
            "entities": [],
            "relationships": [],
            "proposal_lineage": [],
            "decision_lineage": [],
            "policy_version": "policy-v1",
            "schema_version": "schema-v1",
        },
        now=NOW,
    )
    duplicate, duplicate_created = PublisherDispatchStore(
        dispatch_root
    ).coordinator().create_publish(
        run_id="ODR-1",
        connection_id="connection-a",
        source_generation_id="source-a",
        candidate=first["candidate"],
        now=NOW,
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate["dispatch_id"] == first["dispatch_id"]
    assert PublisherDispatchStore(dispatch_root).coordinator().list_publish() == [
        first
    ]


def test_eligible_epoch_rotates_retrying_head_and_survives_every_restart(tmp_path):
    _registry(
        tmp_path / "connections",
        "connection-a",
        "connection-b",
        "connection-c",
        "connection-d",
    )
    state_path = tmp_path / "state" / "runs.json"
    attempts: dict[str, int] = {}
    selected: list[str] = []

    async def process(connection, _run):
        selected.append(connection.connection_id)
        attempts[connection.connection_id] = attempts.get(connection.connection_id, 0) + 1
        if connection.connection_id == "connection-a":
            raise RuntimeError("retryable")
        return {"status": "succeeded", "dispatch_id": f"dispatch-{connection.connection_id}"}

    for pass_index in range(8):
        scheduler = EligibleConnectionScheduler(
            registry=ConnectionRegistry(str(tmp_path / "connections")),
            run_store=OntologyRunStore(
                state_path,
                max_attempts=2,
                retry_base_seconds=1,
            ),
            processor=process,
            source_generation=lambda connection: f"source-{connection.connection_id}",
            owner=f"worker-{pass_index}",
            now=lambda index=pass_index: NOW + timedelta(seconds=index * 2),
        )
        result = asyncio.run(scheduler.run_once(limit=1))
        assert result["processed"] <= 1
        if result["epoch_drained"]:
            break

    epoch = OntologyRunStore(state_path).active_or_latest_epoch()
    assert selected[:4] == [
        "connection-a",
        "connection-b",
        "connection-c",
        "connection-d",
    ]
    assert epoch["status"] == "drained"
    assert epoch["members"]["connection-a"]["outcome"] == "exhausted_failure"
    assert {
        epoch["members"][connection_id]["outcome"]
        for connection_id in ("connection-b", "connection-c", "connection-d")
    } == {"succeeded"}
    assert len(epoch["member_order"]) == len(set(epoch["member_order"])) == 4


def test_production_config_requires_all_roots_and_agent_version(monkeypatch):
    environment = {
        "AIOPS_RUNTIME_MODE": "production",
        "AIOPS_CONNECTION_HOME": "abfss://state@onelake.dfs.fabric.microsoft.com/lh/Files/connections",
        "AIOPS_ONTOLOGY_COMMAND_HOME": "abfss://state@onelake.dfs.fabric.microsoft.com/lh/Files/commands",
        "AIOPS_ONTOLOGY_STATE_HOME": "abfss://state@onelake.dfs.fabric.microsoft.com/lh/Files/state",
        "AIOPS_ONTOLOGY_DISPATCH_HOME": "abfss://state@onelake.dfs.fabric.microsoft.com/lh/Files/dispatch",
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/p",
        "FOUNDRY_ONTOLOGY_AGENT_NAME": "ontology-curator",
        "FOUNDRY_ONTOLOGY_AGENT_VERSION": "7",
        "AIOPS_CONFIG_PATH": "config.yaml",
    }
    config = ProductionRuntimeConfig.from_environ(environment)
    assert config.agent_version == "7"
    assert isinstance(config.connection_home, str)

    for required in (
        "AIOPS_CONNECTION_HOME",
        "AIOPS_ONTOLOGY_COMMAND_HOME",
        "AIOPS_ONTOLOGY_STATE_HOME",
        "AIOPS_ONTOLOGY_DISPATCH_HOME",
        "FOUNDRY_ONTOLOGY_AGENT_VERSION",
    ):
        invalid = dict(environment)
        invalid[required] = ""
        with pytest.raises(ValueError, match=required):
            ProductionRuntimeConfig.from_environ(invalid)

    invalid = dict(environment)
    invalid["AIOPS_ONTOLOGY_PUBLICATION_HOME"] = "abfss://forbidden"
    with pytest.raises(ValueError, match="publication"):
        ProductionRuntimeConfig.from_environ(invalid)

    invalid = dict(environment)
    invalid["FOUNDRY_PROJECT_ENDPOINT"] = "http://insecure.example.test/project"
    with pytest.raises(ValueError, match="FOUNDRY_PROJECT_ENDPOINT"):
        ProductionRuntimeConfig.from_environ(invalid)


def test_cli_main_uses_production_runtime_and_closes_it(monkeypatch, capsys):
    events: list[str] = []

    class Runtime:
        async def run_once(self, *, limit):
            events.append(f"run:{limit}")
            return {"selected": 1, "processed": 1}

        async def aclose(self):
            events.append("closed")

    monkeypatch.setattr(
        cli,
        "build_production_runtime",
        lambda *, owner: Runtime(),
    )

    assert cli.main(["run-once", "--limit", "1", "--owner", "test-worker"]) == 0
    assert events == ["run:1", "closed"]
    assert capsys.readouterr().out == '{"processed": 1, "selected": 1}\n'


def test_cli_main_real_composition_persists_evidence_proposal_and_dispatch(
    tmp_path, monkeypatch, capsys
):
    connection_home = tmp_path / "connections"
    command_home = tmp_path / "commands"
    state_home = tmp_path / "state"
    dispatch_home = tmp_path / "dispatch"
    source_home = tmp_path / "source"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"storage:\n  output_dir: {source_home}\nazure:\n  subscriptions: []\n"
    )
    registry = ConnectionRegistry(str(connection_home))
    registry.add(
        SubscriptionConnection(
            connection_id="connection-a",
            name="connection-a",
            tenant_id="tenant-a",
            subscription_id="subscription-connection-a",
            metadata={"environment": "validation"},
        )
    )
    monkeypatch.setenv("AIOPS_RUNTIME_MODE", "validation")
    monkeypatch.setenv("AIOPS_CONNECTION_HOME", str(connection_home))
    monkeypatch.setenv("AIOPS_ONTOLOGY_COMMAND_HOME", str(command_home))
    monkeypatch.setenv("AIOPS_ONTOLOGY_STATE_HOME", str(state_home))
    monkeypatch.setenv("AIOPS_ONTOLOGY_DISPATCH_HOME", str(dispatch_home))
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/p",
    )
    monkeypatch.setenv("FOUNDRY_ONTOLOGY_AGENT_NAME", "ontology-curator")
    monkeypatch.setenv("FOUNDRY_ONTOLOGY_AGENT_VERSION", "7")
    monkeypatch.setenv("AIOPS_CONFIG_PATH", str(config_path))

    entities = [
        _valid_ontology_entity("vm-a", "VirtualMachine"),
        _valid_ontology_entity("app-a", "Application"),
    ]

    class FakeStore:
        is_remote = False

        def current_generation(self):
            return str(source_home / "generation-1")

    class FakePipeline:
        store = FakeStore()

        def refresh(self):
            return SimpleNamespace(manifest={"runId": "inventory-1"})

    class FakeMapper:
        def load(self, *_args, **_kwargs):
            return {
                "ontology_entities": entities,
                "ontology_relationships": [],
            }

    class FakeCurator:
        def __init__(self, **_kwargs):
            pass

        async def propose(self, _run, _batch):
            return {
                "status": "proposed",
                "proposals": [
                    {
                        "subject_id": "vm-a",
                        "subject_type": "VirtualMachine",
                        "predicate": "member_of",
                        "object_id": "app-a",
                        "object_type": "Application",
                        "evidence_refs": ["opaque-missing-evidence"],
                        "confidence": 0.99,
                    }
                ],
            }

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "ontology_discovery.runtime.build_connection_inventory_pipeline",
        lambda *_args, **_kwargs: FakePipeline(),
    )
    monkeypatch.setattr("ontology_discovery.runtime.InventoryDatasetMapper", FakeMapper)
    monkeypatch.setattr("ontology_discovery.runtime.OntologyCurator", FakeCurator)

    assert cli.main(["run-once", "--limit", "1", "--owner", "worker-a"]) == 0

    run_store = OntologyRunStore(
        state_home,
        document_store=OneLakeDocumentStore(state_home),
    )
    runs = run_store.list_runs()
    dispatches = PublisherDispatchStore(str(dispatch_home)).coordinator().list_publish()
    assert len(runs) == len(dispatches) == 1
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["checkpoint"]["name"] == "publisher_dispatch_created"
    assert run_store.list_evidence_batches(run_id=runs[0]["run_id"])
    registry_scope = "tenant-a:subscription-connection-a:connection-a"
    assert run_store.list_proposals(scope=registry_scope)
    assert dispatches[0]["candidate"]["relationships"] == []
    assert dispatches[0]["candidate"]["decision_lineage"][0].endswith(
        ":shadow-excluded"
    )
    output = capsys.readouterr().out
    assert "connection-a" not in output
    assert "tenant-a" not in output
    assert registry_scope not in output


def _valid_ontology_entity(resource_id: str, entity_type: str) -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "subscription_id": "subscription-connection-a",
        "resource_id": resource_id,
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": "inventory-1",
        "entity_type": entity_type,
        "name": resource_id,
        "resource_type": "test/resource",
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": NOW.isoformat(),
        "retired_at": "",
        "ontology_version": "v1",
        "scope": "tenant-a:subscription-connection-a:connection-a",
    }


def test_reconciliation_cadence_watermark_and_drift_survive_restart(tmp_path):
    state_path = tmp_path / "state" / "runs.json"
    store = OntologyRunStore(state_path)

    mode = store.select_reconciliation_mode(
        connection_id="connection-a",
        now=NOW,
        cadence_seconds=3600,
    )
    assert mode["selected_mode"] == "full"
    assert mode["selection_reason"] == "first_run"

    committed = store.commit_reconciliation(
        connection_id="connection-a",
        predecessor_watermark="",
        committed_watermark="watermark-1",
        full_graph={"entities": [{"resource_id": "a"}], "relationships": [], "pending": []},
        incremental_graph={"entities": [{"resource_id": "a"}], "relationships": [], "pending": []},
        dispatch_id="ODP-1",
        now=NOW,
    )
    assert committed["result"]["drift_status"] == "in_sync"
    assert committed["control"]["committed_watermark"] == "watermark-1"

    reconstructed = OntologyRunStore(state_path)
    mode = reconstructed.select_reconciliation_mode(
        connection_id="connection-a",
        now=NOW + timedelta(minutes=1),
        cadence_seconds=3600,
    )
    assert mode["selected_mode"] == "incremental"

    marked = reconstructed.mark_full_reconciliation_due(
        connection_id="connection-a",
        command_id="ODC-maintenance",
        actor_hash="actor-hash",
        reason="recover drift",
        cadence_seconds=7200,
        now=NOW + timedelta(minutes=2),
    )
    assert marked["force_full"] is True
    due = OntologyRunStore(state_path).select_reconciliation_mode(
        connection_id="connection-a",
        now=NOW + timedelta(minutes=3),
        cadence_seconds=3600,
    )
    assert due["selected_mode"] == "full"
    assert due["selection_reason"] == "maintenance_requested"

    repaired = OntologyRunStore(state_path).commit_reconciliation(
        connection_id="connection-a",
        predecessor_watermark="watermark-1",
        committed_watermark="watermark-2",
        full_graph={"entities": [{"resource_id": "authoritative"}], "relationships": [], "pending": []},
        incremental_graph={"entities": [{"resource_id": "drift"}], "relationships": [], "pending": []},
        dispatch_id="ODP-2",
        now=NOW + timedelta(minutes=4),
    )
    assert repaired["result"]["drift_status"] == "drift_detected"
    assert repaired["result"]["repair_authority"] == "full"
    assert repaired["control"]["force_full"] is False

    following = OntologyRunStore(state_path).select_reconciliation_mode(
        connection_id="connection-a",
        now=NOW + timedelta(minutes=5),
        cadence_seconds=3600,
    )
    assert following["selected_mode"] == "incremental"


def test_fixture_prepare_cleanup_and_sweep_are_bounded_and_fenced(tmp_path):
    from ontology_discovery.runtime import ValidationFixtureLifecycle

    connection_home = str(tmp_path / "connections")
    source_connection_home = str(tmp_path / "source-connections")
    fixture_home = str(tmp_path / "fixture")
    state_home = str(tmp_path / "state")
    source = SubscriptionConnection(
        connection_id="source-connection",
        name="Source connection",
        tenant_id="tenant-a",
        subscription_id="subscription-a",
        credential=CredentialReference(
            credential_id="source-sp",
            client_id="source-client",
            tenant_id="tenant-a",
            secret_ref="keyvault://vault/secrets/source-secret",
        ),
        metadata={
            "environment": "development",
            "ontology_discovery_enabled": True,
        },
    )
    ConnectionRegistry(source_connection_home).add(source)
    lifecycle = ValidationFixtureLifecycle(
        connection_home=connection_home,
        source_connection_home=source_connection_home,
        fixture_home=fixture_home,
        state_home=state_home,
        environment="validation",
        owner_id="coordinator-uai",
        tenant_id="tenant-a",
        subscription_id="subscription-a",
        now=lambda: NOW,
    )

    prepared = lifecycle.prepare()
    assert prepared["status"] == "prepared"
    assert len(prepared["connection_ids"]) == 3
    assert len(ConnectionRegistry(connection_home).list()) == 3
    subscription_ids = {
        row.subscription_id
        for row in ConnectionRegistry(connection_home).list()
    }
    assert "subscription-a" in subscription_ids
    assert len(subscription_ids) == 3
    assert sorted(
        row.credential.kind
        for row in ConnectionRegistry(connection_home).list()
    ) == ["managed_identity", "managed_identity", "service_principal"]
    mirrored = ConnectionRegistry(connection_home).get("source-connection")
    assert mirrored.credential == source.credential
    assert mirrored.metadata["fixture_role"] == "head-change"
    assert OntologyRunStore(
        state_home,
        document_store=OneLakeDocumentStore(state_home),
    ).active_or_latest_epoch()["epoch_id"] == prepared["epoch_id"]

    with pytest.raises(RuntimeError, match="active fixture drill"):
        lifecycle.prepare()
    cleaned = ValidationFixtureLifecycle(
        connection_home=connection_home,
        source_connection_home=source_connection_home,
        fixture_home=fixture_home,
        state_home=state_home,
        environment="validation",
        owner_id="coordinator-uai",
        tenant_id="tenant-a",
        subscription_id="subscription-a",
        now=lambda: NOW,
    ).cleanup()
    assert cleaned["status"] == "cleaned"
    assert ConnectionRegistry(connection_home).list() == []
    assert OntologyRunStore(
        state_home,
        document_store=OneLakeDocumentStore(state_home),
    ).active_or_latest_epoch() is None
    assert lifecycle.sweep_expired()["swept"] == 0


def test_watermark_cannot_advance_before_durable_dispatch(tmp_path):
    store = OntologyRunStore(tmp_path / "state.json")
    store.select_reconciliation_mode(
        connection_id="connection-a",
        now=NOW,
        cadence_seconds=3600,
    )

    with pytest.raises(ValueError, match="dispatch"):
        store.commit_reconciliation(
            connection_id="connection-a",
            predecessor_watermark="",
            committed_watermark="watermark-1",
            full_graph={"entities": [], "relationships": [], "pending": []},
            incremental_graph={"entities": [], "relationships": [], "pending": []},
            dispatch_id="",
            now=NOW,
        )

    assert store.get_reconciliation_control("connection-a")[
        "committed_watermark"
    ] == ""
