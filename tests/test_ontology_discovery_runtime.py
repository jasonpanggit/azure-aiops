from __future__ import annotations

import asyncio
import inspect
import json
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
    history = epoch["selection_history"]
    assert [row["connection_id"] for row in history] == selected
    assert [row["outcome"] for row in history] == [
        "pending", "succeeded", "succeeded", "succeeded", "exhausted_failure",
    ]
    assert [row["cursor_before"] for row in history] == [0, 1, 2, 3, 0]
    assert [row["cursor_after"] for row in history] == [1, 2, 3, 0, 1]
    assert [row["actor"] for row in history] == [
        f"worker-{index}" for index in range(5)
    ]
    assert all(row["authorization_receipt"] for row in history)
    assert [row["attempt"] for row in history] == [1, 1, 1, 1, 2]


def test_legacy_epoch_loads_without_inventing_selection_history(tmp_path):
    state_path = tmp_path / "runs.json"
    store = OntologyRunStore(state_path)
    store.ensure_eligible_epoch(
        member_ids=["connection-a"], registry_revision=1,
        registry_hash="registry-snapshot", now=NOW,
    )
    document = json.loads(state_path.read_text())
    del document["eligible_epochs"][0]["selection_history"]
    state_path.write_text(json.dumps(document))
    epoch = OntologyRunStore(state_path).active_or_latest_epoch()
    assert epoch["selection_history"] == []
    assert epoch["members"]["connection-a"]["attempt_count"] == 0


def test_deleted_member_retains_closed_exclusion_receipt(tmp_path):
    registry = _registry(tmp_path / "connections", "connection-a")
    store = OntologyRunStore(tmp_path / "runs.json")
    store.ensure_eligible_epoch(
        member_ids=["connection-a"], registry_revision=registry.revision(),
        registry_hash="registry-snapshot", now=NOW,
    )
    registry.delete("connection-a")

    async def unexpected_process(*_args):
        pytest.fail("excluded connection must not reach the processor")

    scheduler = EligibleConnectionScheduler(
        registry=registry, run_store=store, processor=unexpected_process,
        source_generation=lambda _connection: pytest.fail("excluded source lookup"),
        owner="worker-a", now=lambda: NOW,
    )
    result = asyncio.run(scheduler.run_once(limit=1))
    assert result["excluded"] == 1
    history = store.active_or_latest_epoch()["selection_history"]
    assert len(history) == 1
    assert history[0]["outcome"] == "excluded"
    assert history[0]["actor"] == "worker-a"
    assert history[0]["authorization_receipt"]
    assert history[0]["cursor_before"] == history[0]["cursor_after"] == 0


def test_restarted_scheduler_history_reaches_sanitized_drain_validator(tmp_path):
    from scripts.collect_ontology_evidence import (
        sanitize_closed_record,
        summarize_lifecycle_documents,
    )
    from scripts.validate_ontology_discovery_live import derive_drain_evidence

    ids = [f"ontology-fixture-example-{letter}" for letter in ("a", "b", "c")]
    registry = ConnectionRegistry(str(tmp_path / "connections"))
    for connection_id in ids:
        connection = _connection(connection_id)
        connection.metadata.update({
            "environment": "validation",
            "fixture_owner_hash": "owner",
            "fixture_drill_hash": "drill",
            "fixture_fence": 1,
        })
        registry.add(connection)
    state_path = tmp_path / "state" / "runs.json"
    store = OntologyRunStore(state_path, max_attempts=2, retry_base_seconds=1)
    epoch = store.ensure_eligible_epoch(
        member_ids=ids, registry_revision=registry.revision(),
        registry_hash="registry-snapshot", now=NOW,
    )
    fixture = {"drills": [{
        "drill_hash": "drill", "owner_hash": "owner", "fence": 1,
        "status": "prepared", "connection_ids": ids, "epoch_id": epoch["epoch_id"],
        "prepared_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=2)).isoformat(),
        "receipts": [{"event": "prepared", "at": NOW.isoformat()}],
    }]}
    registry_document = {
        "revision": registry.revision(),
        "connections": [connection.to_dict() for connection in registry.list()],
    }

    def snapshot():
        return {"facts": summarize_lifecycle_documents(
            fixture=fixture, registry=registry_document,
            state=json.loads(state_path.read_text()),
        )}

    prepared = snapshot()
    resumed_snapshots = []

    async def process(connection, _run):
        if connection.connection_id == ids[1]:
            raise RuntimeError("retryable")
        return {"status": "succeeded"}

    for index in range(4):
        scheduler = EligibleConnectionScheduler(
            registry=ConnectionRegistry(str(tmp_path / "connections")),
            run_store=OntologyRunStore(
                state_path, max_attempts=2, retry_base_seconds=1,
            ),
            processor=process,
            source_generation=lambda connection: f"source-{connection.connection_id}",
            owner=f"worker-{index}",
            environment="validation",
            now=lambda index=index: NOW + timedelta(seconds=index * 2),
        )
        asyncio.run(scheduler.run_once(limit=1))
        if index < 3:
            resumed_snapshots.append(snapshot())

    final_snapshot = snapshot()
    assert sanitize_closed_record(final_snapshot) == final_snapshot
    result = derive_drain_evidence(
        preflight={"contract": {"validation_connection_root_hash": "sha256:" + "a" * 64}},
        prepared=prepared, receipts=[], final_snapshot=final_snapshot,
    )
    assert result["retry_rotated"] is True
    assert result["durable_rotation_proof"] is True
    assert result["later_member_progress"] is True
    assert len(result["selection_receipts"]) == 4
    assert len(result["process_hashes"]) == 4
    assert all(connection_id not in json.dumps(result) for connection_id in ids)
    for resumed in resumed_snapshots:
        resumed_result = derive_drain_evidence(
            preflight={
                "contract": {
                    "validation_connection_root_hash": "sha256:" + "a" * 64,
                },
            },
            prepared=resumed, receipts=[], final_snapshot=final_snapshot,
        )
        assert resumed_result == result


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


@pytest.mark.parametrize("explicit_owner", ["test-worker", ""])
def test_cli_main_uses_production_runtime_and_closes_it(
    monkeypatch, capsys, explicit_owner
):
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
        lambda *, owner: events.append(f"owner:{owner}") or Runtime(),
    )

    assert cli.main(["run-once", "--limit", "1", "--owner", explicit_owner]) == 0
    assert events == [f"owner:{explicit_owner}", "run:1", "closed"]
    assert capsys.readouterr().out == '{"processed": 1, "selected": 1}\n'


def test_cli_default_owner_is_unique_per_process_invocation(monkeypatch, capsys):
    owners: list[str] = []

    class Runtime:
        async def run_once(self, *, limit):
            assert limit == 1
            return {"selected": 0}

        async def aclose(self):
            return None

    monkeypatch.setattr(cli.socket, "gethostname", lambda: "coordinator-host")
    monkeypatch.setattr(
        cli,
        "build_production_runtime",
        lambda *, owner: owners.append(owner) or Runtime(),
    )

    assert cli.main(["run-once"]) == 0
    assert cli.main(["run-once"]) == 0
    assert len(owners) == 2
    assert all(owner.startswith("coordinator-host:") for owner in owners)
    assert owners[0] != owners[1]
    assert capsys.readouterr().out == '{"selected": 0}\n{"selected": 0}\n'


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

    vm_a_id = (
        "/subscriptions/subscription-connection-a/resourceGroups/apps/providers/"
        "Microsoft.Compute/virtualMachines/vm-a"
    )
    vm_b_id = (
        "/subscriptions/subscription-connection-a/resourceGroups/apps/providers/"
        "Microsoft.Compute/virtualMachines/vm-b"
    )
    entities = [
        _valid_ontology_entity(vm_a_id, "VirtualMachine"),
        _valid_ontology_entity("app-a", "Application"),
        _valid_ontology_entity(vm_b_id, "VirtualMachine"),
        _valid_ontology_entity("app-b", "Application"),
    ]
    relationship = {
        **_valid_ontology_entity("relationship-a", "Application"),
        "subject_id": "app-a",
        "subject_type": "Application",
        "predicate": "hosted_on",
        "object_id": vm_a_id,
        "object_type": "VirtualMachine",
        "source": "resource_tag",
        "confidence": 1.0,
    }
    memberships = [
        {
            **_valid_ontology_entity("membership-a", "Application"),
            "subject_id": vm_a_id,
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_id": "app-a",
            "object_type": "Application",
            "source": "application_tag",
            "confidence": 1.0,
        },
        {
            **_valid_ontology_entity("membership-b", "Application"),
            "subject_id": vm_b_id,
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_id": "app-b",
            "object_type": "Application",
            "source": "application_tag",
            "confidence": 1.0,
        },
    ]
    deterministic = [relationship, *memberships]
    observed_at = datetime.now(UTC)
    bronze_resources = [
        {
            "resource_id": vm_a_id,
            "subscription_id": "subscription-connection-a",
            "source_generation_id": "inventory-1",
            "observed_at": observed_at.isoformat(),
            "payload_json": json.dumps(
                {
                    "id": vm_a_id,
                    "tags": {
                        "aiops.dependencyResourceIds": json.dumps([vm_b_id])
                    },
                }
            ),
        },
        {
            "resource_id": vm_b_id,
            "subscription_id": "subscription-connection-a",
            "source_generation_id": "inventory-1",
            "observed_at": observed_at.isoformat(),
            "payload_json": json.dumps({"id": vm_b_id, "tags": {}}),
        },
    ]
    monitor_row = {
        "TimeGenerated": observed_at.isoformat(),
        "Id": "dependency-1",
        "OperationId": "operation-1",
        "_ResourceId": vm_a_id,
        "_SubscriptionId": "subscription-connection-a",
        "AppRoleName": "frontend",
        "Target": "backend",
        "DependencyType": "HTTP",
        "Success": True,
        "SyntheticSource": "",
    }

    class FakeStore:
        is_remote = False

        def current_generation(self):
            return str(source_home / "generation-1")

    class FakePipeline:
        store = FakeStore()

        def refresh(self):
            return SimpleNamespace(
                manifest={
                    "runId": "inventory-1",
                    "startedAt": observed_at.isoformat(),
                }
            )

    class FakeMapper:
        def load(self, *_args, **_kwargs):
            return {
                "ontology_entities": entities,
                "ontology_relationships": deterministic,
                "bronze_resources": bronze_resources,
            }

    class FakeCurator:
        def __init__(self, **_kwargs):
            pass

        async def propose(self, _run, _batch):
            pair = next(
                value
                for value in _batch["candidate_pairs"]
                if value.get("predicate") == "depends_on"
            )
            return {
                "batch_id": _batch["batch_id"],
                "status": "proposals",
                "proposals": [
                    {
                        "subject_id": pair["subject_id"],
                        "subject_type": pair["subject_type"],
                        "predicate": pair["predicate"],
                        "object_id": pair["object_id"],
                        "object_type": pair["object_type"],
                        "evidence_refs": list(pair["evidence_ids"]),
                        "observed_at": observed_at.isoformat(),
                        "rationale": "Two independently sourced observations corroborate this pair.",
                        "confidence": 0.99,
                        "uncertainty": [],
                        "disposition": "propose",
                    }
                ],
                "missing_evidence": [],
            }

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "ontology_discovery.runtime.build_connection_inventory_pipeline",
        lambda *_args, **_kwargs: FakePipeline(),
    )
    real_build_runtime = cli.build_production_runtime

    def offline_runtime(*, owner):
        return real_build_runtime(
            owner=owner,
            monitor_dependency_reader=lambda _connection: [monitor_row],
            monitor_identity_bindings=lambda _connection: {
                "frontend": vm_a_id,
                "backend": vm_b_id,
            },
        )

    monkeypatch.setattr(cli, "build_production_runtime", offline_runtime)
    monkeypatch.setattr("ontology_discovery.runtime.InventoryDatasetMapper", FakeMapper)
    monkeypatch.setattr("ontology_discovery.runtime.OntologyCurator", FakeCurator)

    assert cli.main(["run-once", "--limit", "1", "--owner", "worker-a"]) == 0

    run_store = OntologyRunStore(
        state_home,
        document_store=OneLakeDocumentStore(state_home),
    )
    runs = run_store.list_runs()
    dispatches = PublisherDispatchStore(str(dispatch_home)).coordinator().list_publish()
    assert len(runs) == len(dispatches) == 1, runs
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["checkpoint"]["name"] == "publisher_dispatch_created"
    assert run_store.list_evidence_batches(run_id=runs[0]["run_id"])
    registry_scope = "tenant-a:subscription-connection-a:connection-a"
    assert run_store.list_proposals(scope=registry_scope)
    assert {
        row["resource_id"] for row in dispatches[0]["candidate"]["relationships"]
    } == {row["resource_id"] for row in deterministic}
    assert dispatches[0]["candidate"]["decision_lineage"][0].endswith(
        ":shadow-excluded"
    )
    dispatched_evidence = run_store.list_evidence_batches(run_id=runs[0]["run_id"])[0][
        "batch"
    ]["evidence_records"]
    assert {row["source"] for row in dispatched_evidence} == {
        "azure-resource-graph:dependency-tag",
        "azure-monitor:AppDependencies",
    }
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
    assert repaired["control"]["force_full"] is True
    assert repaired["control"]["force_full_reason"] == "drift_detected"

    following = OntologyRunStore(state_path).select_reconciliation_mode(
        connection_id="connection-a",
        now=NOW + timedelta(minutes=5),
        cadence_seconds=3600,
    )
    assert following["selected_mode"] == "full"
    assert following["selection_reason"] == "drift_detected"


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
            secret_ref="keyvault://example-vault/secrets/source-secret",
        ),
        metadata={
            "business": {"environment": "development"},
            "ontology_discovery_enabled": True,
        },
    )
    ConnectionRegistry(source_connection_home).add(source)
    ConnectionRegistry(source_connection_home).add(
        SubscriptionConnection(
            connection_id="production-connection",
            name="Production connection",
            tenant_id="tenant-a",
            subscription_id="production-subscription",
            credential=CredentialReference(
                credential_id="production-sp",
                client_id="production-client",
                tenant_id="tenant-a",
                secret_ref="keyvault://example-vault/secrets/production-secret",
            ),
            metadata={
                "business": {"environment": "production"},
                "ontology_discovery_enabled": True,
            },
        )
    )
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
    assert {
        row.connection_id for row in ConnectionRegistry(connection_home).list()
    }.isdisjoint({"production-connection"})
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
