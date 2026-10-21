from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pytest

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
def test_cli_composes_explicit_identity_single_attempt_and_readonly_default(
    tmp_path, monkeypatch, capsys, execute,
):
    request, observer, lake, delta, *_ = fixture(tmp_path)
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
    monkeypatch.setattr(cli, "FabricClient", fabric)
    monkeypatch.setattr(cli, "OntologyManager", manager)
    monkeypatch.setattr(cli, "ReadOnlyLakeDocuments", lambda fs: observer.documents)
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
    assert len(requests) >= 6 and len(requests) % 3 == 0
    for offset in range(0, len(requests), 3):
        assert requests[offset] == (
            "POST", f"/v1/workspaces/{WORKSPACE}/ontologies/{NATIVE_ITEM}/getDefinition",
        )
        assert requests[offset + 1] == ("GET", "/v1/operations/header-proof")
        assert requests[offset + 2] == ("GET", "/v1/operations/header-proof/result")
