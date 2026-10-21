from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pytest

from fabric import exposure_scalar_migration as migration
from fabric import exposure_scalar_migration_cli as cli
from fabric.exposure_scalar_migration import (
    ExposureScalarMigrationPlan,
    migration_rows_hash,
)
from fabric.exposure_scalar_migration_cli import (
    CATALOG,
    LAKEHOUSE,
    NATIVE_ITEM,
    SOURCE_POINTER,
    TABLE,
    TENANT,
    WORKSPACE,
    ExposureMigrationAuthorityObserver,
    ReadOnlyLakeDocuments,
    document_hash,
    main,
    run_caller,
    validate_identity_token,
    validate_request,
)
from fabric.schema_registry import schema_for
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter


def fixture(tmp_path):
    lake = OneLakeWriter(WORKSPACE, LAKEHOUSE, local_root=tmp_path / "lake")
    delta = DeltaWriter(max_attempts=1)
    generic = {field.name: "" for field in schema_for("ontology_entities")}
    generic.update(
        resource_id="exposure", tenant_id="tenant", subscription_id="subscription",
        timestamp="2026-10-21T01:00:00Z", change_version="first",
        ingestion_run_id="ingestion", entity_type="ContainerImageExposure",
        lifecycle_status="active", ontology_version="source",
        payload_json=json.dumps({
            "id": "exposure", "tenantId": "tenant", "subscriptionId": "subscription",
            "connection_id": "demo", "registryResourceId": "registry",
        }),
    )
    target = lake.table_uri("ontology", "container_image_exposure_entities")
    delta.write(target, [generic], mode="overwrite", schema=schema_for("ontology_entities"))
    current = {**generic, "change_version": "second"}
    delta.write(target, [current], mode="overwrite", schema=schema_for("ontology_entities"))
    delta.write(lake.table_uri("ontology", "entities"), [current], mode="overwrite", schema=schema_for("ontology_entities"))
    delta.write(lake.table_uri("ontology", "relationships"), [], mode="overwrite", schema=schema_for("ontology_relationships"))
    registry = {
        **current, "resource_id": "registry", "entity_type": "ContainerRegistry",
        "payload_json": json.dumps({
            "id": "registry", "tenantId": "tenant", "subscriptionId": "subscription",
            "connection_id": "demo",
        }),
    }
    delta.write(lake.table_uri("ontology", "container_registry_entities"), [registry], mode="overwrite", schema=schema_for("ontology_entities"))
    # The actual Silver schema carries its original source payload too.
    silver = {
        field.name: "" if pa.types.is_string(field.type) else (
            False if pa.types.is_boolean(field.type) else (
                [] if pa.types.is_list(field.type) else 0
            )
        ) for field in schema_for("silver_container_image_exposure")
    }
    silver.update({
        key: current[key] for key in (
            "resource_id", "tenant_id", "subscription_id", "timestamp",
            "change_version", "ingestion_run_id", "payload_json",
        )
    })
    silver["registry_resource_id"] = "registry"
    delta.write(
        lake.table_uri("silver", "container_image_exposure"), [silver],
        mode="overwrite", schema=schema_for("silver_container_image_exposure"),
    )
    marker = {
        "resource_id": "marker", "tenant_id": "system", "subscription_id": "system",
        "timestamp": "2026-10-21T01:00:00Z", "change_version": "v1",
        "ingestion_run_id": "ingestion", "status": "completed",
        "source_run_id": "source", "failed_records": 0,
        "ontology_entity_version": 0, "ontology_relationship_version": 0,
    }
    # Observer tests use an exact marker shape; production uses the same public
    # read/version interface without creating or rewriting ingestion metadata.
    real_read, real_version = delta.read, delta.version
    marker_uri = lake.table_uri("metadata", "ingestion_state")
    delta.read = lambda uri, **kw: [dict(marker)] if uri == marker_uri else real_read(uri, **kw)
    delta.version = lambda uri: 0 if uri == marker_uri else real_version(uri)
    plan = ExposureScalarMigrationPlan(
        WORKSPACE, LAKEHOUSE, "", 1, 0, 0, 0, "a" * 64,
        migration_rows_hash([{**current, "registry_resource_id": "registry", "connection_id": "demo"}]),
        "c" * 64,
    )
    table = (
        f"partition {TABLE} = entity\n mode: directLake\n"
        f"entityName: {TABLE}\n expressionSource: DirectLakeSource\n"
        f"annotation ONT_WorkspaceId = {WORKSPACE}\n annotation ONT_ItemId = {LAKEHOUSE}\n"
        "annotation ONT_ItemKind = Lakehouse\n annotation ONT_PinnedAtUtc = old"
    )
    texts = {
        f"tables/{TABLE}.tmdl": table,
        "expressions.tmdl": f'expression DirectLakeSource = let Source = AzureStorage.DataLake("https://onelake.dfs.pbidedicated.windows.net/{WORKSPACE}/{LAKEHOUSE}", [HierarchicalNavigation=true]) in Source',
        "entities/ContainerImageExposure.tmdl": f"backingTable: {TABLE}",
    }
    definition = {"parts": [
        {"path": name, "payloadType": "InlineBase64", "payload": base64.b64encode(text.encode()).decode()}
        for name, text in texts.items()
    ]}
    docs = {
        SOURCE_POINTER: {"generation": "source"},
        "Files/aiops/generations/source/manifest.json": {
            "runId": "source", "status": "completed",
            "queryVersion": "combined-subscription-connections-v1",
        },
        CATALOG: {"completed_product": "fixture"},
    }
    evidence_path = "Files/aiops/validation/native-scalar/"
    request = {
        "plan": asdict(plan), "publisher_client_id": "1" * 8 + "-1111-1111-1111-" + "1" * 12,
        "publisher_object_id": "2" * 8 + "-2222-2222-2222-" + "2" * 12,
        "source_root": f"abfss://{WORKSPACE}@onelake.dfs.fabric.microsoft.com/{LAKEHOUSE}/Files/aiops",
        "authority_mode": "completed_ingestion",
        "product_authority_evidence": evidence_path + "products.json",
        "consumption_evidence": evidence_path + "consumption.json",
    }
    docs[request["product_authority_evidence"]] = {
        "authority_mode": "completed_ingestion", "workspace_id": WORKSPACE,
        "lakehouse_id": LAKEHOUSE, "table": TABLE, "source_generation": "source",
        "canonical_version": 0, "source_manifest_hash": document_hash(docs["Files/aiops/generations/source/manifest.json"]),
        "catalog_hash": document_hash(docs[CATALOG]), "immutable_product_consumers": [],
    }
    cols = ("resource_id", "tenant_id", "subscription_id", "change_version")
    docs[request["consumption_evidence"]] = {
        "kind": "native-query-delta-head-observations/v1", "workspace_id": WORKSPACE,
        "lakehouse_id": LAKEHOUSE, "item_id": NATIVE_ITEM, "table": TABLE,
        "definition_hash": document_hash(definition),
        "observations": [
            {
                "delta_version": v, "status": "succeeded", "reader": "native_ontology_agent",
                "query_contract": "all-active-exposure-keys-no-version-filter/v1",
                "request_id": f"native-query-{v}", "observed_at": f"2026-10-21T01:0{v}:00Z",
                "native_rows": real_read(target, version=v, columns=cols),
            } for v in (0, 1)
        ],
    }
    for name in ("consumption_evidence", "product_authority_evidence"):
        request[name + "_hash"] = document_hash(docs[request[name]])

    class Documents:
        def read(self, path):
            payload = copy.deepcopy(docs[path])
            return {"payload": payload, "etag": document_hash(payload)}

    class Manager:
        def get_definition(self, item):
            assert item == NATIVE_ITEM
            return copy.deepcopy(definition)

    observer = ExposureMigrationAuthorityObserver(
        request=request, documents=Documents(), manager=Manager(), onelake=lake, delta=delta,
    )
    request["plan"]["authority_fingerprint"] = observer()
    return request, observer, lake, delta, docs, definition, marker


def test_readonly_observer_and_finite_caller_then_transaction_replay(tmp_path):
    request, observer, lake, delta, *_ = fixture(tmp_path)
    target = lake.table_uri("ontology", "container_image_exposure_entities")
    assert run_caller(request, observer=observer, onelake=lake, delta=delta)["mutated"] is False
    assert delta.version(target) == 1
    assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "completed"
    assert delta.version(target) == 2
    assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "replayed"


def sql_fixture(tmp_path):
    request, observer, lake, delta, docs, definition, marker = fixture(tmp_path)
    request["assurance_mode"] = cli.SQL_ASSURANCE
    request["sql_endpoint"] = {
        "server": "reviewed.datawarehouse.fabric.microsoft.com",
        "database": "33333333-3333-3333-3333-333333333333", "schema": "dbo",
    }
    request["reviewed_evidence"] = {
        "product_authority_evidence": copy.deepcopy(docs[request["product_authority_evidence"]]),
        "sql_publication_evidence": {
            "kind": cli.SQL_ASSURANCE, "workspace_id": WORKSPACE, "lakehouse_id": LAKEHOUSE,
            "item_id": NATIVE_ITEM, "table": TABLE, "definition_hash": document_hash(definition),
            "versions": {name: request["plan"][name + "_version"]
                         for name in ("target", "canonical", "silver", "registry")},
            "projected_rows_hash": request["plan"]["projected_rows_hash"],
            "sql_endpoint": request["sql_endpoint"],
            "payload_projection": "varchar(8000);not-connection-authority",
            "acceptance": "source-publication-only;not-native-freshness",
        },
    }
    for name, payload in request["reviewed_evidence"].items():
        request[name + "_hash"] = document_hash(payload)
    # No remote evidence files or synthetic native-instance observations.
    del docs[request["consumption_evidence"]]
    del docs[request["product_authority_evidence"]]
    for key in ("consumption_evidence", "consumption_evidence_hash", "product_authority_evidence"):
        request.pop(key)
    endpoint = cli.SqlEndpoint(**request["sql_endpoint"])

    class Sql:
        def __init__(self):
            self.endpoint = endpoint
            self.transform = lambda table, rows: rows
            self.on_query = lambda: None

        def query(self, statement, parameters=(), *, max_rows):
            self.on_query()
            table = parameters[1] if parameters else (
                TABLE if f"[{TABLE}]" in statement else "ontology_container_registry_entities"
            )
            name = "container_image_exposure_entities" if table == TABLE else "container_registry_entities"
            uri = lake.table_uri("ontology", name)
            version = delta.version(uri)
            if parameters:
                fields = delta.describe(uri, version=version)["schema"]["fields"]
                result = [{"name": field["name"], "type": "varchar", "length": 8000} for field in fields]
            else:
                columns = statement.split(" FROM ")[0].removeprefix("SELECT ").replace("[", "").replace("]", "").split(", ")
                result = [{key: row[key] for key in columns} for row in delta.read(uri, version=version)]
            result = self.transform(table, result)
            if len(result) > max_rows:
                raise ValueError("SQL row bound exceeded")
            return result

    sql = Sql()

    def metadata(method, path):
        assert method == "GET" and path == f"/workspaces/{WORKSPACE}/lakehouses/{LAKEHOUSE}"
        return {"id": LAKEHOUSE, "properties": {"sqlEndpointProperties": {
            "connectionString": endpoint.server, "id": endpoint.database,
        }}}

    observer.manager.client = SimpleNamespace(request=metadata)
    observer = ExposureMigrationAuthorityObserver(
        request=request, documents=observer.documents, manager=observer.manager,
        onelake=lake, delta=delta, sql_reader=sql,
    )
    request["plan"]["authority_fingerprint"] = observer()
    return request, observer, lake, delta, docs, definition, marker, sql


def test_sql_mode_inspect_execute_replay_without_native_receipts_or_remote_evidence(tmp_path):
    request, observer, lake, delta, *_, _sql = sql_fixture(tmp_path)
    validate_request(request, {"AIOPS_IDENTITY_CLASS": "publisher", "AZURE_CLIENT_ID": request["publisher_client_id"]})
    initial = observer()
    assert run_caller(request, observer=observer, onelake=lake, delta=delta)["mutated"] is False
    assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "completed"
    assert observer() == initial
    assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "replayed"


@pytest.mark.parametrize("case", [
    "missing-evidence", "wrong-hash", "wrong-definition", "wrong-endpoint",
    "missing-reader", "schema", "missing-key", "same-count-wrong-key",
    "wrong-scope", "registry-multiplicity", "wrong-scalars", "unknown-mode",
    "silver-head", "registry-head", "source", "definition",
])
def test_sql_assurance_rejects_unqualified_inputs_without_writes(tmp_path, case):
    request, observer, lake, delta, docs, definition, _, sql = sql_fixture(tmp_path)
    target = lake.table_uri("ontology", "container_image_exposure_entities")
    evidence = request["reviewed_evidence"]["sql_publication_evidence"]
    if case == "missing-evidence":
        request["reviewed_evidence"].pop("sql_publication_evidence")
    elif case == "wrong-hash":
        request["sql_publication_evidence_hash"] = "0" * 64
    elif case in ("wrong-definition", "wrong-scalars"):
        evidence["definition_hash" if case == "wrong-definition" else "projected_rows_hash"] = "0" * 64
        request["sql_publication_evidence_hash"] = document_hash(evidence)
    elif case == "wrong-endpoint":
        sql.endpoint = cli.SqlEndpoint("foreign.datawarehouse.fabric.microsoft.com", sql.endpoint.database)
    elif case == "missing-reader":
        observer.sql_reader = None
    elif case == "unknown-mode":
        request["assurance_mode"] = "fallback"
        with pytest.raises(ValueError, match="Unknown assurance"):
            ExposureMigrationAuthorityObserver(
                request=request, documents=observer.documents, manager=observer.manager,
                onelake=lake, delta=delta, sql_reader=sql,
            )
        return
    elif case in ("silver-head", "registry-head"):
        name = "silver" if case == "silver-head" else "registry"
        uri = lake.table_uri(*{
            "silver": ("silver", "container_image_exposure"),
            "registry": ("ontology", "container_registry_entities"),
        }[name])
        original = delta.version
        delta.version = lambda value: original(value) + (1 if value == uri else 0)
    elif case == "source":
        docs[SOURCE_POINTER]["generation"] = "wrong"
    elif case == "definition":
        definition["parts"][0]["payload"] = base64.b64encode(b"wrong").decode()
    else:
        def transform(table, rows):
            rows = copy.deepcopy(rows)
            if case == "schema" and rows and "name" in rows[0]:
                rows[0]["length"] = 4000
            if rows and "resource_id" in rows[0]:
                if case == "missing-key":
                    rows = []
                elif case == "same-count-wrong-key":
                    rows[0]["resource_id"] = "invented"
                elif case == "wrong-scope":
                    rows[0]["tenant_id"] = "foreign"
                elif case == "registry-multiplicity" and table != TABLE:
                    rows.append(rows[0].copy())
            return rows
        sql.transform = transform
    with pytest.raises((ValueError, RuntimeError, KeyError)):
        run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
    assert delta.version(target) == 1


def test_sql_postpublication_scalar_mismatch_restores_original_table(tmp_path):
    request, observer, lake, delta, *_, sql = sql_fixture(tmp_path)
    target = lake.table_uri("ontology", "container_image_exposure_entities")

    def stale(table, rows):
        if table == TABLE and rows and "connection_id" in rows[0]:
            rows[0]["connection_id"] = "stale"
        return rows

    sql.transform = stale
    with pytest.raises(RuntimeError, match="original table restored"):
        run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
    assert delta.version(target) == 3
    assert delta.read(target, version=3) == delta.read(target, version=1)
    assert delta.describe(target, version=3)["schema"] == delta.describe(target, version=1)["schema"]


@pytest.mark.parametrize("case", [
    "converges", "deadline", "lease", "source", "definition", "canonical", "target",
    "wrong-key", "wrong-registry",
])
def test_sql_postcommit_bounded_wait_preserves_guards_and_never_retries_write(
    tmp_path, monkeypatch, case,
):
    request, observer, lake, delta, docs, definition, _, sql = sql_fixture(tmp_path)
    target = lake.table_uri("ontology", "container_image_exposure_entities")
    original_query = sql.query
    original_write = delta.write
    writes, waits = [], []
    now = [0]
    lease_lost = [False]
    original_lock = lake.sync_lock

    def lock_context():
        context = original_lock()
        class Guarded:
            def __enter__(self):
                lock = context.__enter__()
                original_assert = lock.assert_held
                def assert_held():
                    if lease_lost[0]:
                        raise RuntimeError("test lease lost")
                    original_assert()
                monkeypatch.setattr(lock, "assert_held", assert_held)
                return lock
            def __exit__(self, *args):
                return context.__exit__(*args)
        return Guarded()
    monkeypatch.setattr(lake, "sync_lock", lock_context)

    def write(uri, *args, **kwargs):
        writes.append(uri)
        return original_write(uri, *args, **kwargs)
    monkeypatch.setattr(delta, "write", write)

    def query(statement, parameters=(), *, max_rows):
        result = original_query(statement, parameters, max_rows=max_rows)
        if delta.version(target) == 2 and not (case == "converges" and waits):
            if parameters and parameters[1] == TABLE:
                result = [row for row in result if row["name"] not in cli._SCALARS]
            elif not parameters and f"[{TABLE}]" in statement and case == "wrong-key":
                result[0]["resource_id"] = "unrelated"
            elif not parameters and "registry_entities" in statement and case == "wrong-registry":
                result[0]["tenant_id"] = "foreign"
        return result
    sql.query = query

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds
        if case == "lease":
            lease_lost[0] = True
        elif case == "source":
            docs[SOURCE_POINTER]["drift"] = True
        elif case == "definition":
            definition["drift"] = True
        elif case in ("target", "canonical"):
            uri = target if case == "target" else lake.table_uri("ontology", "entities")
            rows = delta.read(uri)
            rows[0]["change_version"] = "other-writer"
            original_write(uri, rows, mode="overwrite", schema=schema_for(
                TABLE if case == "target" else "ontology_entities",
            ))

    monkeypatch.setattr(migration.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(migration.time, "sleep", sleep)
    monkeypatch.setattr(migration, "SQL_PROPAGATION_TIMEOUT_SECONDS", 10)
    if case == "converges":
        assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "completed"
        assert waits == [5]
        assert delta.version(target) == 2
    else:
        with pytest.raises(RuntimeError, match=(
            "lease lost" if case == "lease" else
            "intervening writer" if case == "target" else "original table restored"
        )) as error:
            run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
        if case == "deadline":
            assert waits == [5, 5]
            assert "deadline exceeded" in str(error.value.__cause__)
        if case in ("wrong-key", "wrong-registry"):
            assert waits == []
        if case not in ("lease", "target"):
            assert delta.read(target, version=3) == delta.read(target, version=1)
    assert writes == [target]


def test_sql_mode_rejects_identical_target_head_from_unrelated_transaction(tmp_path):
    request, observer, lake, delta, *_ = sql_fixture(tmp_path)
    target = lake.table_uri("ontology", "container_image_exposure_entities")
    rows = delta.read(target)
    rows[0]["change_version"] = "unrelated"
    delta.write(target, rows, mode="overwrite", schema=schema_for("ontology_entities"))
    delta.restore(target, 1, expected_version=2, transaction_id="e" * 64, transaction_digest="f" * 64)
    with pytest.raises(RuntimeError, match="outside reviewed transaction"):
        run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
    assert delta.version(target) == 3


@pytest.mark.parametrize("case", [
    "late-success", "boundary-success", "before-next-observation",
    "first-observation-overrun", "final-readback-overrun", "before-deadline",
])
def test_sql_propagation_deadline_is_acceptance_cutoff_even_on_success(
    tmp_path, monkeypatch, case,
):
    request, observer, lake, delta, *_, sql = sql_fixture(tmp_path)
    target = lake.table_uri("ontology", "container_image_exposure_entities")
    original_query, original_read, original_write = sql.query, delta.read, delta.write
    now, sleeps, writes = [0.0], [], []
    post_queries = []
    committed_observations = []

    def query(statement, parameters=(), *, max_rows):
        result = original_query(statement, parameters, max_rows=max_rows)
        if delta.version(target) == 2:
            post_queries.append(statement)
            if parameters and parameters[1] == TABLE:
                committed_observations.append(True)
                if len(committed_observations) == 1 and case not in (
                    "first-observation-overrun", "final-readback-overrun",
                ):
                    return [row for row in result if row["name"] not in cli._SCALARS]
                if case == "boundary-success":
                    now[0] = migration.SQL_PROPAGATION_TIMEOUT_SECONDS
                elif case in ("late-success", "first-observation-overrun"):
                    now[0] = migration.SQL_PROPAGATION_TIMEOUT_SECONDS + 1
                elif case == "before-deadline":
                    now[0] = migration.SQL_PROPAGATION_TIMEOUT_SECONDS - 1
        return result

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] = (
            migration.SQL_PROPAGATION_TIMEOUT_SECONDS
            if case == "before-next-observation" else now[0] + seconds
        )

    def read(uri, **kwargs):
        result = original_read(uri, **kwargs)
        if case == "final-readback-overrun" and uri == target and kwargs.get("version") == 2:
            now[0] = migration.SQL_PROPAGATION_TIMEOUT_SECONDS + 1
        return result

    def write(uri, *args, **kwargs):
        writes.append(uri)
        return original_write(uri, *args, **kwargs)

    sql.query = query
    monkeypatch.setattr(delta, "read", read)
    monkeypatch.setattr(delta, "write", write)
    monkeypatch.setattr(migration.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(migration.time, "sleep", sleep)
    if case == "before-deadline":
        assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "completed"
        assert delta.version(target) == 2
    else:
        with pytest.raises(RuntimeError, match="original table restored") as error:
            run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
        assert "deadline exceeded" in str(error.value.__cause__)
        assert delta.read(target, version=3) == delta.read(target, version=1)
    if case == "before-next-observation":
        assert len(committed_observations) == 1
        assert sleeps == [5]
    assert writes == [target]
    assert post_queries


def test_sql_propagation_cutoff_is_explicitly_bounded():
    assert migration.SQL_PROPAGATION_TIMEOUT_SECONDS == 240
    assert migration.SQL_PROPAGATION_POLL_SECONDS == 5


@pytest.mark.parametrize("case", ["registry-collision", "registry-scope", "silver-scope", "malformed-registry"])
def test_sql_mode_preserves_full_delta_authority_checks(tmp_path, monkeypatch, case):
    request, observer, lake, delta, *_, _sql = sql_fixture(tmp_path)
    original_read = delta.read
    layer, name = (
        ("silver", "container_image_exposure") if case == "silver-scope"
        else ("ontology", "container_registry_entities")
    )
    uri = lake.table_uri(layer, name)

    def read(value, **kwargs):
        rows = original_read(value, **kwargs)
        if value == uri:
            if case == "registry-collision":
                rows.append({**rows[0], "tenant_id": "other-tenant"})
            elif case == "malformed-registry":
                rows[0]["payload_json"] = '{"connection_id":'
            else:
                payload = json.loads(rows[0]["payload_json"])
                payload["connection_id"] = "other-connection"
                rows[0]["payload_json"] = json.dumps(payload)
        return rows

    monkeypatch.setattr(delta, "read", read)
    with pytest.raises(ValueError):
        run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
    assert delta.version(lake.table_uri("ontology", "container_image_exposure_entities")) == 1


@pytest.mark.parametrize("empty", [False, True])
def test_sql_mode_old_empty_and_already_additive_noop(tmp_path, empty):
    request, observer, lake, delta, _, _, marker, _ = sql_fixture(tmp_path)
    target = lake.table_uri("ontology", "container_image_exposure_entities")
    if empty:
        for layer, name, schema in (
            ("ontology", "container_image_exposure_entities", "ontology_entities"),
            ("ontology", "entities", "ontology_entities"),
            ("silver", "container_image_exposure", "silver_container_image_exposure"),
            ("ontology", "container_registry_entities", "ontology_entities"),
        ):
            delta.write(lake.table_uri(layer, name), [], mode="overwrite", schema=schema_for(schema))
        for name, parts in {
            "target": ("ontology", "container_image_exposure_entities"),
            "canonical": ("ontology", "entities"),
            "silver": ("silver", "container_image_exposure"),
            "registry": ("ontology", "container_registry_entities"),
        }.items():
            request["plan"][name + "_version"] = delta.version(lake.table_uri(*parts))
        marker["ontology_entity_version"] = request["plan"]["canonical_version"]
        request["plan"]["projected_rows_hash"] = migration_rows_hash([])
        products = request["reviewed_evidence"]["product_authority_evidence"]
        products["canonical_version"] = request["plan"]["canonical_version"]
        request["product_authority_evidence_hash"] = document_hash(products)
        evidence = request["reviewed_evidence"]["sql_publication_evidence"]
        evidence["versions"] = {name: request["plan"][name + "_version"]
                                for name in ("target", "canonical", "silver", "registry")}
        evidence["projected_rows_hash"] = request["plan"]["projected_rows_hash"]
        request["sql_publication_evidence_hash"] = document_hash(evidence)
        observer.plan = ExposureScalarMigrationPlan(**request["plan"])
        request["plan"]["authority_fingerprint"] = observer()
    assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "completed"
    request["plan"]["target_version"] = delta.version(target)
    request["plan"]["transaction_id"] = "e" * 64
    evidence = request["reviewed_evidence"]["sql_publication_evidence"]
    evidence["versions"]["target"] = request["plan"]["target_version"]
    request["sql_publication_evidence_hash"] = document_hash(evidence)
    observer.plan = ExposureScalarMigrationPlan(**request["plan"])
    request["plan"]["authority_fingerprint"] = observer()
    before = delta.version(target)
    assert run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)["status"] == "unchanged"
    assert delta.version(target) == before


@pytest.mark.parametrize("drift", ["definition", "source", "registry", "silver"])
def test_sql_parity_rereads_detect_drift_during_live_query(tmp_path, drift):
    _request, observer, lake, delta, docs, definition, _, sql = sql_fixture(tmp_path)
    calls = []

    def change():
        calls.append(True)
        if len(calls) != 1:
            return
        if drift == "definition":
            definition["changed"] = True
        elif drift == "source":
            docs[SOURCE_POINTER]["changed"] = True
        else:
            uri = lake.table_uri(*{
                "registry": ("ontology", "container_registry_entities"),
                "silver": ("silver", "container_image_exposure"),
            }[drift])
            name = "ontology_entities" if drift == "registry" else "silver_container_image_exposure"
            rows = delta.read(uri)
            rows[0]["change_version"] = "intervening-writer"
            delta.write(uri, rows, mode="overwrite", schema=schema_for(name))

    sql.on_query = change
    with pytest.raises((RuntimeError, ValueError), match="changed|parity mismatch"):
        observer()


@pytest.mark.parametrize("case", [
    "source", "catalog", "manifest", "definition", "marker", "consumption",
    "missing-consumption", "same-observation", "wrong-reader", "wrong-native-rows", "pinned-products",
])
def test_changed_or_unqualified_authority_never_writes(tmp_path, case):
    request, observer, lake, delta, docs, definition, marker = fixture(tmp_path)
    if case == "source":
        docs[SOURCE_POINTER]["generation"] = "foreign"
    elif case == "catalog":
        docs[CATALOG]["changed"] = True
    elif case == "manifest":
        docs["Files/aiops/generations/source/manifest.json"]["status"] = "failed"
    elif case == "definition":
        definition["parts"][0]["payload"] = base64.b64encode(b"wrong native table").decode()
    elif case == "marker":
        marker["source_run_id"] = "foreign"
    elif case == "pinned-products":
        docs[request["product_authority_evidence"]]["immutable_product_consumers"] = ["pinned"]
        request["product_authority_evidence_hash"] = document_hash(docs[request["product_authority_evidence"]])
    else:
        evidence = docs[request["consumption_evidence"]]
        if case == "consumption":
            evidence["item_id"] = "foreign"
        elif case == "missing-consumption":
            evidence.clear()
        elif case == "same-observation":
            evidence["observations"][0] = evidence["observations"][1]
        elif case == "wrong-reader":
            evidence["observations"][1]["reader"] = "sql"
        else:
            evidence["observations"][1]["native_rows"][0]["change_version"] = "invented"
        request["consumption_evidence_hash"] = document_hash(evidence)
    with pytest.raises((ValueError, RuntimeError, KeyError)):
        run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
    assert delta.version(lake.table_uri("ontology", "container_image_exposure_entities")) == 1


@pytest.mark.parametrize("case", ["root", "identity", "class", "target", "path", "authority-mode"])
def test_request_rejects_wrong_roots_identity_and_modes(tmp_path, case):
    request, *_ = fixture(tmp_path)
    env = {"AIOPS_IDENTITY_CLASS": "publisher", "AZURE_CLIENT_ID": request["publisher_client_id"]}
    validate_request(request, env)
    if case == "root":
        request["source_root"] += "/connections"
    elif case == "identity":
        env["AZURE_CLIENT_ID"] = "foreign"
    elif case == "class":
        env["AIOPS_IDENTITY_CLASS"] = "apps"
    elif case == "target":
        request["plan"]["lakehouse_id"] = "foreign"
    elif case == "path":
        request["consumption_evidence"] += "/../else.json"
    else:
        request["authority_mode"] = "maintenance"
    with pytest.raises(ValueError):
        validate_request(request, env)


def test_identity_claims_are_checked_without_exposing_token(tmp_path):
    request, *_ = fixture(tmp_path)
    claims = {
        "tid": TENANT, "oid": request["publisher_object_id"],
        "appid": request["publisher_client_id"], "aud": "https://storage.azure.com/",
    }

    def token():
        return "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"

    validate_identity_token(token(), request)
    for key in tuple(claims):
        old = claims[key]
        claims[key] = "wrong"
        with pytest.raises(ValueError, match="identity token"):
            validate_identity_token(token(), request)
        claims[key] = old


def test_actual_observer_drift_during_migration_guard_blocks_write(tmp_path, monkeypatch):
    request, observer, lake, delta, docs, *_ = fixture(tmp_path)
    original = observer.documents.read
    calls = []

    def drift(path):
        calls.append(path)
        if calls.count(SOURCE_POINTER) == 3:
            docs[CATALOG]["drift"] = True
        return original(path)

    monkeypatch.setattr(observer.documents, "read", drift)
    with pytest.raises(ValueError, match="Product authority"):
        run_caller(request, observer=observer, onelake=lake, delta=delta, execute=True)
    assert delta.version(lake.table_uri("ontology", "container_image_exposure_entities")) == 1


def test_conditional_document_reader_has_no_write_surface_and_checks_etag():
    content = b'{"generation":"source"}'

    class File:
        def get_file_properties(self):
            return SimpleNamespace(etag="v1", size=len(content))

        def download_file(self, **kwargs):
            assert kwargs["etag"] == "v1"
            return SimpleNamespace(readall=lambda: content)

    fs = SimpleNamespace(get_file_client=lambda path: File())
    reader = ReadOnlyLakeDocuments(fs)
    assert reader.read(SOURCE_POINTER)["payload"] == {"generation": "source"}
    with pytest.raises(ValueError):
        reader.read("Files/../secret")


def test_cli_rejects_changed_request_before_any_identity_construction(tmp_path):
    path = tmp_path / "request.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="request bytes changed"):
        main(["--request", str(path), "--request-sha256", "0" * 64])


@pytest.mark.parametrize("drift", ["catalog", "definition", "marker", "canonical", "relationship"])
def test_observer_rejects_torn_read_before_returning_fingerprint(tmp_path, monkeypatch, drift):
    _, observer, lake, delta, docs, definition, _ = fixture(tmp_path)
    original_read = observer.documents.read
    original_version = delta.version
    reads = []

    def read(path):
        reads.append(path)
        if path == SOURCE_POINTER and reads.count(path) == 2:
            if drift == "catalog":
                docs[CATALOG]["changed"] = True
            if drift == "definition":
                definition["parts"][0]["payload"] = base64.b64encode(b"changed").decode()
        return original_read(path)

    def version(uri):
        layer, table = {
            "marker": ("metadata", "ingestion_state"),
            "canonical": ("ontology", "entities"),
            "relationship": ("ontology", "relationships"),
        }.get(drift, ("unused", "unused"))
        if reads.count(SOURCE_POINTER) >= 2 and uri == lake.table_uri(layer, table):
            return original_version(uri) + 1
        return original_version(uri)

    monkeypatch.setattr(observer.documents, "read", read)
    monkeypatch.setattr(delta, "version", version)
    with pytest.raises(RuntimeError, match="changed during observation"):
        observer()


@pytest.mark.parametrize("case", ["etag", "body-size", "non-object", "oversize"])
def test_document_reader_rejects_changed_or_malformed_read(case):
    body = b"[]" if case == "non-object" else b"{}"
    calls = []

    class File:
        def get_file_properties(self):
            calls.append("properties")
            size = 8 * 1024 * 1024 + 1 if case == "oversize" else len(body)
            if case == "body-size":
                size += 1
            return SimpleNamespace(
                size=size, etag="v2" if case == "etag" and len(calls) > 1 else "v1",
            )

        def download_file(self, **kwargs):
            return SimpleNamespace(readall=lambda: body)

    reader = ReadOnlyLakeDocuments(SimpleNamespace(get_file_client=lambda path: File()))
    with pytest.raises((ValueError, RuntimeError, TypeError)):
        reader.read(SOURCE_POINTER)


@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize("sql_mode", [False, True])
def test_cli_composes_explicit_identity_single_attempt_and_readonly_default(
    tmp_path, monkeypatch, capsys, execute, sql_mode,
):
    values = sql_fixture(tmp_path) if sql_mode else fixture(tmp_path)
    request, observer, lake, delta, *_ = values
    calls = []
    requests = []
    real_http_client = httpx.Client
    real_fabric_client = cli.FabricClient
    real_manager = cli.OntologyManager
    definition = observer.manager.get_definition(NATIVE_ITEM)
    operation = "https://api.fabric.microsoft.com/v1/operations/header-proof"

    def respond(request):
        assert request.headers["x-ms-fabric-skill"] == "fabriciq-ontology-cli"
        requests.append((request.method, request.url.path))
        if "/lakehouses/" in request.url.path:
            endpoint = observer.sql_reader.endpoint
            return httpx.Response(200, json={
                "id": LAKEHOUSE, "properties": {"sqlEndpointProperties": {
                    "connectionString": endpoint.server, "id": endpoint.database,
                }},
            })
        if request.url.path.endswith("/getDefinition"):
            return httpx.Response(202, headers={"Location": operation, "Retry-After": "0"})
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json={"definition": definition})
        return httpx.Response(200, json={"status": "Succeeded"})

    def http_client(**kwargs):
        assert kwargs["headers"] == {"x-ms-fabric-skill": "fabriciq-ontology-cli"}
        return real_http_client(**kwargs, transport=httpx.MockTransport(respond))

    class Credential:
        def __init__(self, *, client_id):
            assert client_id == request["publisher_client_id"]
            calls.append("identity")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_token(self, scope):
            assert scope in ("https://storage.azure.com/.default", real_fabric_client.SCOPE)
            claims = {
                "tid": TENANT, "oid": request["publisher_object_id"],
                "appid": request["publisher_client_id"], "aud": "https://storage.azure.com/",
            }
            encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
            return SimpleNamespace(token="header." + encoded + ".signature")

    class Service:
        def __init__(self, endpoint, *, credential):
            assert endpoint == OneLakeWriter.ENDPOINT
            assert isinstance(credential, Credential)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_file_system_client(self, workspace):
            assert workspace == WORKSPACE
            return "filesystem"

    class Lake:
        ENDPOINT = OneLakeWriter.ENDPOINT

        def __new__(cls, workspace, lakehouse, **kwargs):
            assert (workspace, lakehouse) == (WORKSPACE, LAKEHOUSE)
            assert isinstance(kwargs["credential"], Credential)
            assert isinstance(kwargs["service_client"], Service)
            return lake

    def writer(**kwargs):
        assert kwargs["max_attempts"] == 1
        assert callable(kwargs["storage_options_provider"])
        calls.append("single-attempt")
        return delta

    def fabric(credential, *, http_client, max_attempts):
        assert isinstance(credential, Credential) and max_attempts == 1
        return real_fabric_client(
            credential, http_client=http_client, max_attempts=max_attempts, sleep=lambda _: None,
        )

    def manager(client, workspace):
        assert isinstance(client, real_fabric_client) and workspace == WORKSPACE
        return real_manager(client, workspace)

    monkeypatch.setattr(cli, "ManagedIdentityCredential", Credential)
    monkeypatch.setattr(cli, "DataLakeServiceClient", Service)
    monkeypatch.setattr(cli, "OneLakeWriter", Lake)
    monkeypatch.setattr(cli, "DeltaWriter", writer)
    class SqlWriter(cli._ExposureMigrationDeltaWriter):
        def __new__(cls, **kwargs):
            assert sql_mode
            return writer(**kwargs)

    monkeypatch.setattr(cli, "_ExposureMigrationDeltaWriter", SqlWriter)
    monkeypatch.setattr(cli, "FabricClient", fabric)
    monkeypatch.setattr(cli, "OntologyManager", manager)
    monkeypatch.setattr(cli, "ReadOnlyLakeDocuments", lambda fs: observer.documents)
    if sql_mode:
        def sql_reader(endpoint, credential):
            assert endpoint == observer.sql_reader.endpoint
            assert isinstance(credential, Credential)
            return observer.sql_reader
        monkeypatch.setattr(cli, "FabricSqlReader", sql_reader)
    monkeypatch.setattr(cli.httpx, "Client", http_client)
    monkeypatch.setenv("AZURE_CLIENT_ID", request["publisher_client_id"])
    monkeypatch.setenv("AIOPS_IDENTITY_CLASS", "publisher")
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    argv = ["--request", str(path), "--request-sha256", hashlib.sha256(path.read_bytes()).hexdigest()]
    if execute:
        argv.append("--execute")
    assert main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == ("completed" if execute else "inspected")
    assert delta.version(lake.table_uri("ontology", "container_image_exposure_entities")) == (2 if execute else 1)
    assert calls == ["identity", "single-attempt"]
    if sql_mode:
        assert any("/lakehouses/" in path for _, path in requests)
        requests = [(method, path) for method, path in requests if "/lakehouses/" not in path]
    assert len(requests) >= 6 and len(requests) % 3 == 0
    for offset in range(0, len(requests), 3):
        assert requests[offset] == (
            "POST", f"/v1/workspaces/{WORKSPACE}/ontologies/{NATIVE_ITEM}/getDefinition",
        )
        assert requests[offset + 1] == ("GET", "/v1/operations/header-proof")
        assert requests[offset + 2] == ("GET", "/v1/operations/header-proof/result")


def test_sql_reader_fresh_metadata_heads_observe_real_interposed_commit(tmp_path, monkeypatch):
    from deltalake import DeltaTable

    uri = str(tmp_path / "heads")
    writer = DeltaWriter(max_attempts=1)
    writer.write(uri, [{"key": "first"}], mode="overwrite", required_columns=())
    calls = []

    def table(*args, **kwargs):
        calls.append(kwargs)
        return DeltaTable(*args, **kwargs)

    monkeypatch.setattr(cli, "DeltaTable", table)
    reader = cli._ExposureMigrationDeltaWriter(max_attempts=1)
    assert reader.version(uri) == 0
    assert reader.read_heads({"target": uri}) == {"target": 0}
    writer.write(uri, [{"key": "second"}], mode="overwrite", required_columns=())
    assert reader.version(uri) == 1
    assert reader.read_heads({"target": uri}) == {"target": 1}
    assert len(calls) == 4
    assert all(
        call["without_files"] is True and call["skip_stats"] is True and "version" not in call
        for call in calls
    )


def test_sql_reader_pinned_full_reads_keep_files_schema_and_original_fields(tmp_path, monkeypatch):
    from deltalake import DeltaTable

    uri = str(tmp_path / "pinned")
    writer = DeltaWriter(max_attempts=1)
    original = [{"key": "first", "original_payload": '{"untruncated":true}'}]
    writer.write(uri, original, mode="overwrite", required_columns=())
    writer.write(uri, [{"key": "second", "original_payload": "new"}], mode="overwrite", required_columns=())
    calls = []

    def table(*args, **kwargs):
        calls.append(kwargs)
        result = DeltaTable(*args, **kwargs)
        assert result.file_uris()
        assert not kwargs.get("without_files", False)
        return result

    monkeypatch.setattr(cli, "DeltaTable", table)
    reader = cli._ExposureMigrationDeltaWriter(max_attempts=1)
    assert reader.read_pinned({"target": uri}, {"target": 0}) == {"target": original}
    rows, schema = reader.read_snapshot(uri, version=0)
    assert rows == original
    assert schema == writer.describe(uri, version=0)["schema"]
    assert all(call["version"] == 0 for call in calls)


@pytest.mark.parametrize("method", ["version", "read_heads", "read_pinned", "read_snapshot"])
@pytest.mark.parametrize("failure", ["missing", "auth", "history"])
def test_sql_reader_does_not_fallback_or_retry_errors(monkeypatch, method, failure):
    error = RuntimeError(failure)
    calls = []

    def table(*args, **kwargs):
        calls.append((args, kwargs))
        raise error

    monkeypatch.setattr(cli, "DeltaTable", table)
    reader = cli._ExposureMigrationDeltaWriter(max_attempts=1)
    calls_by_method = {
        "version": lambda: reader.version("uri"),
        "read_heads": lambda: reader.read_heads({"target": "uri"}),
        "read_pinned": lambda: reader.read_pinned({"target": "uri"}, {"target": 0}),
        "read_snapshot": lambda: reader.read_snapshot("uri", version=0),
    }
    with pytest.raises(RuntimeError) as caught:
        calls_by_method[method]()
    assert caught.value is error
    assert len(calls) == 1


def test_sql_reader_real_missing_table_and_missing_history_raise(tmp_path):
    reader = cli._ExposureMigrationDeltaWriter(max_attempts=1)
    with pytest.raises(Exception, match="does not exist|No such file|not found"):
        reader.version(str(tmp_path / "missing"))
    uri = str(tmp_path / "existing")
    DeltaWriter(max_attempts=1).write(uri, [{"key": "value"}], mode="overwrite", required_columns=())
    with pytest.raises(Exception, match="version|Version|log"):
        reader.read_snapshot(uri, version=999)


@pytest.mark.parametrize("fail", [False, True])
def test_sql_reader_batch_max_four_options_isolation_and_error_drain(fail):
    lock = threading.Lock()
    ready = threading.Event()
    state = {"started": 0, "active": 0, "maximum": 0, "finished": 0}
    provided = {"token": "current"}
    provider_calls = []
    reader = cli._ExposureMigrationDeltaWriter(
        max_attempts=1, storage_options={"existing": "untouched"},
        storage_options_provider=lambda: (provider_calls.append(1) or provided),
    )
    original_options = dict(reader.storage_options)
    failure = RuntimeError("worker failed")

    def read(uri, options, name):
        assert options == {"token": "current"}
        options["token"] = name
        with lock:
            state["started"] += 1
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            if state["started"] == 4:
                ready.set()
        try:
            assert ready.wait(5)
            if fail and name == "0":
                raise failure
            return uri
        finally:
            with lock:
                state["active"] -= 1
                state["finished"] += 1

    uris = {str(n): f"uri{n}" for n in range(8)}
    if fail:
        with pytest.raises(RuntimeError) as caught:
            reader._batch(uris, read)
        assert caught.value is failure
    else:
        assert reader._batch(uris, read) == uris
    assert state["maximum"] == 4
    assert state["active"] == 0 and state["finished"] == 8
    assert provided == {"token": "current"} and reader.storage_options == original_options
    assert provider_calls == [1]
    reader._batch({"next": "uri"}, lambda *_: None)
    assert provider_calls == [1, 1]


@pytest.mark.parametrize("versions", [{}, {"other": 0}, {"target": True}, {"target": -1}, {"target": 1.5}])
def test_sql_reader_requires_exact_pinned_versions(versions):
    reader = cli._ExposureMigrationDeltaWriter(max_attempts=1)
    with pytest.raises(ValueError, match="exact non-negative versions"):
        reader.read_pinned({"target": "uri"}, versions)


@pytest.mark.parametrize("drift_at", [None, 2, 3])
def test_sql_observer_batched_head_brackets_and_sequential_authority(tmp_path, monkeypatch, drift_at):
    request, observer, lake, delta, *_ = sql_fixture(tmp_path)
    main_thread = threading.get_ident()
    canonical_uri = lake.table_uri("ontology", "entities")
    count = 0
    counter_lock = threading.Lock()

    class Table:
        def __init__(
            self, uri, *, storage_options, version=None, without_files=False,
            skip_stats=False,
        ):
            self.uri, self.pinned = uri, version
            self.without_files, self.skip_stats = without_files, skip_stats

        def version(self):
            nonlocal count
            assert self.without_files is True and self.skip_stats is True and self.pinned is None
            with counter_lock:
                if self.uri == canonical_uri:
                    count += 1
                    if count == drift_at:
                        return delta.version(self.uri) + 1
            return delta.version(self.uri)

        def to_pyarrow_table(self):
            assert self.pinned is not None and not self.without_files
            return SimpleNamespace(to_pylist=lambda: delta.read(self.uri, version=self.pinned))

        def schema(self):
            assert self.pinned is not None and not self.without_files
            return SimpleNamespace(to_json=lambda: json.dumps(delta.describe(self.uri, version=self.pinned)["schema"]))

    def sequential(method):
        def call(*args, **kwargs):
            assert threading.get_ident() == main_thread
            return method(*args, **kwargs)
        return call

    for owner, name in (
        (observer.documents, "read"), (observer.manager, "get_definition"),
        (observer.sql_reader, "query"),
    ):
        monkeypatch.setattr(owner, name, sequential(getattr(owner, name)))
    monkeypatch.setattr(cli, "DeltaTable", Table)
    reader = cli._ExposureMigrationDeltaWriter(max_attempts=1)
    reader.read = delta.read
    observer.delta = reader
    if drift_at is None:
        assert observer() == request["plan"]["authority_fingerprint"]
        assert count == 4
    else:
        with pytest.raises(RuntimeError, match="head changed|heads changed"):
            observer()
