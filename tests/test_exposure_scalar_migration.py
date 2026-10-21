from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace

import pytest

from fabric.dataset_mapper import InventoryDatasetMapper
from fabric.exposure_scalar_migration import (
    TABLE,
    ExposureScalarMigrationPlan,
    migrate_exposure_scalars,
    migration_rows_hash,
)
from fabric.schema_registry import schema_for
from storage.datasets import DatasetStore
from storage.delta_writer import DeltaWriter
from storage.locking import LeaseLostError
from storage.onelake_writer import OneLakeWriter


def setup(tmp_path, *, empty=False, upgraded=False):
    sources = [] if empty else [
        {
            "id": f"exposure-{scope}", "tenantId": f"tenant-{scope}",
            "subscriptionId": f"sub-{scope}", "connection_id": scope,
            "registryResourceId": f"registry-{scope}",
            "lastObservedTimestamp": "2026-10-21T00:00:00Z",
        } for scope in ("demo", "another")
    ]
    registries = [
        {**row, "id": row["registryResourceId"], "name": row["registryResourceId"]}
        for row in sources
    ]
    store = DatasetStore(tmp_path / "source")
    store.publish(
        {"entities/ContainerImageExposure": sources, "entities/ContainerRegistry": registries},
        {}, {"runId": "source", "startedAt": "2026-10-21T00:00:00Z"}, ontology={},
    )
    datasets = InventoryDatasetMapper().load(store.current_generation(), "publication")
    exposure_rows = {
        row["resource_id"]: row for row in datasets["ontology_entities"]
        if row["entity_type"] == "ContainerImageExposure"
    }
    datasets["ontology_container_registry_entities"] = [
        {
            **exposure_rows[source["id"]], "resource_id": source["registryResourceId"],
            "entity_type": "ContainerRegistry", "payload_json": json.dumps(registry),
        }
        for source, registry in zip(sources, registries, strict=True)
    ]
    onelake = OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lake")
    delta = DeltaWriter(sleep=lambda _: None)
    uris = {
        "target": onelake.table_uri("ontology", "container_image_exposure_entities"),
        "canonical": onelake.table_uri("ontology", "entities"),
        "silver": onelake.table_uri("silver", "container_image_exposure"),
        "registry": onelake.table_uri("ontology", "container_registry_entities"),
    }
    tables = {
        "target": TABLE, "canonical": "ontology_entities",
        "silver": "silver_container_image_exposure", "registry": "ontology_container_registry_entities",
    }
    for key, table in tables.items():
        rows = datasets[table]
        schema = schema_for(table)
        if key == "target" and not upgraded:
            schema = schema_for("ontology_entities")
            rows = [{name: row[name] for name in schema.names} for row in rows]
        delta.write(uris[key], rows, mode="overwrite", schema=schema)
    plan = ExposureScalarMigrationPlan(
        workspace_id="workspace", lakehouse_id="lakehouse", table_schema="",
        target_version=0, canonical_version=0, silver_version=0, registry_version=0,
        authority_fingerprint="a" * 64,
        projected_rows_hash=migration_rows_hash(datasets[TABLE]),
        transaction_id="c" * 64,
    )
    return onelake, delta, plan, uris, datasets


def run(onelake, delta, plan):
    return migrate_exposure_scalars(
        onelake, delta, plan, observe_authority=lambda: "a" * 64,
    )


@pytest.mark.parametrize("empty", [False, True])
def test_existing_delta_upgrade_all_scopes_and_exact_transaction_replay(tmp_path, empty):
    lake, delta, plan, uris, datasets = setup(tmp_path, empty=empty)
    result = run(lake, delta, plan)
    assert result["status"] == "completed"
    assert result["version"] == 1
    assert migration_rows_hash(delta.read(uris["target"])) == plan.projected_rows_hash
    assert len(delta.read(uris["target"])) == (0 if empty else 2)
    assert run(lake, delta, plan)["status"] == "replayed"
    assert delta.version(uris["target"]) == 1
    assert all(delta.version(uri) == 0 for name, uri in uris.items() if name != "target")
    assert datasets["ontology_entities"] == delta.read(uris["canonical"])
    assert result["native_apply"] is False
    assert result["endpoint_quality_qualified"] is False


@pytest.mark.parametrize("empty", [False, True])
def test_already_upgraded_is_noop_including_empty(tmp_path, empty):
    lake, delta, plan, uris, _ = setup(tmp_path, empty=empty, upgraded=True)
    assert run(lake, delta, plan)["status"] == "unchanged"
    assert delta.version(uris["target"]) == 0


@pytest.mark.parametrize("field,value", [
    ("workspace_id", "foreign"), ("lakehouse_id", "foreign"),
    ("table_schema", "foreign"), ("target_version", 1),
    ("canonical_version", -1), ("silver_version", True),
    ("transaction_id", ""), ("authority_fingerprint", ""),
    ("projected_rows_hash", "b" * 64),
])
def test_wrong_target_versions_or_reviewed_hash_rejected(tmp_path, field, value):
    lake, delta, plan, uris, _ = setup(tmp_path)
    with pytest.raises((ValueError, RuntimeError)):
        run(lake, delta, replace(plan, **{field: value}))
    assert delta.version(uris["target"]) == 0


def test_authority_observer_must_match_reviewed_fingerprint(tmp_path):
    lake, delta, plan, uris, _ = setup(tmp_path)
    with pytest.raises(RuntimeError, match="authority"):
        migrate_exposure_scalars(lake, delta, plan, observe_authority=lambda: "b" * 64)
    assert delta.version(uris["target"]) == 0


@pytest.mark.parametrize("change", [
    "membership", "duplicate", "canonical-field", "silver-key", "registry-scope",
    "invalid-registry-json", "invalid-exposure-json", "registry-payload-scope",
    "missing-connection", "connection-conflict", "schema",
])
def test_authority_and_endpoint_failures_before_any_write(tmp_path, change):
    lake, delta, plan, uris, _ = setup(tmp_path)
    key = "target"
    if change in {"silver-key"}:
        key = "silver"
    elif change.startswith("registry") or change in {"invalid-registry-json", "missing-connection", "connection-conflict"}:
        key = "registry"
    elif change == "invalid-exposure-json":
        key = "canonical"
    rows = delta.read(uris[key])
    if change == "membership":
        rows.pop()
    elif change == "duplicate":
        rows.append(rows[0])
    elif change == "canonical-field":
        rows[0]["name"] = "tampered"
    elif change == "silver-key":
        rows[0]["registry_resource_id"] = "unreviewed"
    elif change == "registry-scope":
        rows[0]["tenant_id"] = "foreign"
    elif change in {"invalid-registry-json", "invalid-exposure-json"}:
        rows[0]["payload_json"] = '{"truncated":'
    elif change in {"registry-payload-scope", "missing-connection", "connection-conflict"}:
        payload = json.loads(rows[0]["payload_json"])
        if change == "registry-payload-scope":
            payload["tenantId"] = "foreign"
        elif change == "missing-connection":
            del payload["connection_id"]
        else:
            payload["connectionId"] = "foreign"
        rows[0]["payload_json"] = json.dumps(payload)
    schema = schema_for({
        "target": "ontology_entities", "canonical": "ontology_entities",
        "silver": "silver_container_image_exposure",
        "registry": "ontology_container_registry_entities",
    }[key])
    if change == "schema":
        import pyarrow as pa
        schema = schema.append(pa.field("unexpected", pa.string()))
        rows = [{**row, "unexpected": "x"} for row in rows]
    # Change versions to ensure the test fixture itself is materialized.
    rows = [{**row, "change_version": "fixture-mutated"} for row in rows]
    delta.write(uris[key], rows, mode="overwrite", schema=schema)
    plan = replace(plan, **{key + "_version": delta.version(uris[key])})
    before = delta.version(uris["target"])
    with pytest.raises((ValueError, RuntimeError)):
        run(lake, delta, plan)
    assert delta.version(uris["target"]) == before


def test_timeout_after_durable_commit_reconciles_without_second_write(tmp_path, monkeypatch):
    lake, delta, plan, uris, _ = setup(tmp_path)
    original = delta.write
    writes = []

    def timeout(*args, **kwargs):
        writes.append(args[0])
        original(*args, **kwargs)
        raise TimeoutError("reply lost after commit")

    monkeypatch.setattr(delta, "write", timeout)
    assert run(lake, delta, plan)["status"] == "completed"
    assert writes == [uris["target"]]
    assert delta.version(uris["target"]) == 1
    assert run(lake, delta, plan)["status"] == "replayed"
    assert len(writes) == 1


def test_failure_before_commit_is_not_retried_or_restored(tmp_path, monkeypatch):
    lake, delta, plan, uris, _ = setup(tmp_path)

    def fail(*args, **kwargs):
        raise TimeoutError("no commit")

    monkeypatch.setattr(delta, "write", fail)
    with pytest.raises(RuntimeError, match="without proven commit"):
        run(lake, delta, plan)
    assert delta.version(uris["target"]) == 0


def test_authority_loss_after_commit_restores_original_and_blocks_replay(tmp_path, monkeypatch):
    lake, delta, plan, uris, _ = setup(tmp_path)
    original = delta.write
    before = delta.read(uris["target"])
    state = {"authority": "a" * 64}

    def write(*args, **kwargs):
        result = original(*args, **kwargs)
        state["authority"] = "b" * 64
        return result

    monkeypatch.setattr(delta, "write", write)
    with pytest.raises(RuntimeError, match="original table restored"):
        migrate_exposure_scalars(
            lake, delta, plan, observe_authority=lambda: state["authority"],
        )
    assert delta.version(uris["target"]) == 2
    assert delta.read(uris["target"]) == before
    with pytest.raises(RuntimeError, match="rolled back"):
        run(lake, delta, plan)


def test_intervening_writer_after_commit_is_never_rolled_back(tmp_path, monkeypatch):
    lake, delta, plan, uris, _ = setup(tmp_path)
    original = delta.write

    def write(*args, **kwargs):
        result = original(*args, **kwargs)
        rows = delta.read(uris["target"])
        rows[0]["change_version"] = "other-writer"
        original(uris["target"], rows, mode="overwrite", schema=schema_for(TABLE))
        return result

    monkeypatch.setattr(delta, "write", write)
    with pytest.raises(RuntimeError, match="intervening writer"):
        run(lake, delta, plan)
    assert delta.version(uris["target"]) == 2
    assert delta.read(uris["target"])[0]["change_version"] == "other-writer"


@pytest.mark.parametrize("after_commit", [False, True])
def test_lost_lock_never_writes_or_restores(tmp_path, monkeypatch, after_commit):
    lake, delta, plan, uris, _ = setup(tmp_path)
    state = {"lost": not after_commit}

    class Lock:
        def assert_held(self):
            if state["lost"]:
                raise LeaseLostError("test lost lease")

    @contextmanager
    def lock():
        yield Lock()

    monkeypatch.setattr(lake, "sync_lock", lock)
    original = delta.write

    def write(*args, **kwargs):
        result = original(*args, **kwargs)
        state["lost"] = True
        return result

    monkeypatch.setattr(delta, "write", write)
    with pytest.raises(LeaseLostError):
        run(lake, delta, plan)
    assert delta.version(uris["target"]) == (1 if after_commit else 0)


def test_cas_rejects_writer_between_guard_and_write(tmp_path, monkeypatch):
    lake, delta, plan, uris, _ = setup(tmp_path)
    original = delta.write

    def write(*args, **kwargs):
        old = delta.read(uris["target"])
        old[0]["change_version"] = "racing-writer"
        original(uris["target"], old, mode="overwrite", schema=schema_for("ontology_entities"))
        return original(*args, **kwargs)

    monkeypatch.setattr(delta, "write", write)
    with pytest.raises(RuntimeError, match="without proven commit"):
        run(lake, delta, plan)
    assert delta.version(uris["target"]) == 1
    assert delta.read(uris["target"])[0]["change_version"] == "racing-writer"


@pytest.mark.parametrize("table", ["silver", "registry", "canonical"])
def test_input_head_change_is_rejected_before_write(tmp_path, table):
    lake, delta, plan, uris, _ = setup(tmp_path)
    rows = delta.read(uris[table])
    rows[0]["change_version"] = "unreviewed"
    schema = {
        "silver": "silver_container_image_exposure",
        "registry": "ontology_container_registry_entities",
        "canonical": "ontology_entities",
    }[table]
    delta.write(uris[table], rows, mode="overwrite", schema=schema_for(schema))
    with pytest.raises(RuntimeError, match="version changed"):
        run(lake, delta, plan)
    assert delta.version(uris["target"]) == 0


def test_matching_malformed_canonical_and_typed_payload_is_not_silently_ignored(tmp_path):
    lake, delta, plan, uris, _ = setup(tmp_path)
    for key in ("canonical", "target"):
        rows = delta.read(uris[key])
        for row in rows:
            if row["entity_type"] == "ContainerImageExposure":
                row["payload_json"] = '{"truncated":'
                row["change_version"] = "changed"
        delta.write(uris[key], rows, mode="overwrite", schema=schema_for("ontology_entities"))
    with pytest.raises(ValueError, match="Invalid|JSON|json"):
        run(lake, delta, replace(plan, canonical_version=1, target_version=1))
    assert delta.version(uris["target"]) == 1


@pytest.mark.parametrize("kind", ["schema", "records"])
def test_post_commit_readback_failure_restores_exact_old_table(tmp_path, monkeypatch, kind):
    lake, delta, plan, uris, _ = setup(tmp_path)
    before = delta.read(uris["target"])
    original = getattr(delta, "describe" if kind == "schema" else "read")
    failed = []

    def corrupt(uri, *, version=None, **kwargs):
        result = original(uri, version=version, **kwargs)
        if uri == uris["target"] and version == 1:
            failed.append(True)
            if kind == "schema":
                return {**result, "schema": {}}
            return [{**row, "name": "incorrect"} for row in result]
        return result

    monkeypatch.setattr(delta, "describe" if kind == "schema" else "read", corrupt)
    with pytest.raises(RuntimeError, match="original table restored"):
        run(lake, delta, plan)
    assert failed
    assert delta.read(uris["target"]) == before
    assert delta.version(uris["target"]) == 2


def test_rollback_failure_is_explicit_and_not_replayed(tmp_path, monkeypatch):
    lake, delta, plan, uris, _ = setup(tmp_path)
    original = delta.write
    state = {"authority": "a" * 64}

    def write(*args, **kwargs):
        result = original(*args, **kwargs)
        state["authority"] = "b" * 64
        return result

    def fail(*args, **kwargs):
        raise TimeoutError("restore failed")

    monkeypatch.setattr(delta, "write", write)
    monkeypatch.setattr(delta, "restore", fail)
    with pytest.raises(RuntimeError, match="rollback failed; manual reconciliation"):
        migrate_exposure_scalars(lake, delta, plan, observe_authority=lambda: state["authority"])
    assert delta.version(uris["target"]) == 1


def test_replay_rejects_changed_authority_and_reused_id_with_different_plan(tmp_path):
    lake, delta, plan, uris, _ = setup(tmp_path)
    run(lake, delta, plan)
    with pytest.raises(RuntimeError, match="authority"):
        migrate_exposure_scalars(lake, delta, plan, observe_authority=lambda: "b" * 64)
    with pytest.raises(RuntimeError, match="digest"):
        run(lake, delta, replace(plan, projected_rows_hash="d" * 64))
    assert delta.version(uris["target"]) == 1
