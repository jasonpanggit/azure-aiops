"""Synthetic local sinks only; no fixture is an accepted live output manifest."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pyarrow as pa
import pytest

import fabric.sync_service as sync
from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import ONTOLOGY_ENTITY_TYPES, ONTOLOGY_RELATIONSHIP_TYPES
from fabric.maintenance_output import (
    GenerationOutputContext,
    GenerationOutputPolicy,
    describe_outputs,
    output_digest,
)
from fabric.sync_service import (
    FabricSyncService,
    _generation_catalog,
    ontology_generation_products,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
)
from ontology_discovery.publisher import PublicationSafetyError
from storage.delta_writer import DeltaWriteMode, DeltaWriteResult
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter


class Sink:
    def __init__(self):
        self.calls = []
        self.rows = {}

    def write(self, uri, rows, *, mode, schema):
        assert mode == DeltaWriteMode.OVERWRITE
        self.calls.append((uri, deepcopy(rows), schema))
        self.rows[uri] = deepcopy(rows)
        return DeltaWriteResult(rows_processed=len(rows), version=1)

    def version(self, uri):
        return 1 if uri in self.rows else None

    def read(self, uri, *, version):
        assert version == 1
        return self.rows[uri]


def example(tmp_path, monkeypatch, *, operation="admission", generation="candidate"):
    sink = Sink()
    lake = OneLakeWriter("synthetic-workspace", "synthetic-lake", local_root=tmp_path / "lake")
    service = FabricSyncService(
        source_root=tmp_path / "source", onelake=lake,
        delta_writer=sink, validator=DataQualityValidator(),
    )
    catalogs = []

    def write_json(writer, path, payload):
        catalogs.append((str(writer.local_root), path, deepcopy(payload)))

    monkeypatch.setattr(OneLakeWriter, "write_json", write_json)
    target = {
        "tenant_id": "synthetic-tenant", "subscription_id": "synthetic-subscription",
        "connection_id": "synthetic-connection", "workspace_id": lake.workspace_id,
        "item_id": lake.lakehouse_id, "definition_fingerprint": "synthetic-definition",
    }
    manifest = {
        "generation_id": generation, "source_generation": "synthetic-source",
        "content_hash": "synthetic-content",
        "entity_hash": output_digest([]), "relationship_hash": output_digest([]),
    }
    staged = {
        "manifest": manifest, "entities": [], "relationships": [],
        "validation": {"passed": True},
    }
    auth = {"authorization_digest": "synthetic-auth", "attestation_digest": "synthetic-attestation"}
    context = GenerationOutputContext(
        operation=operation, generation_id=generation,
        source_generation=manifest["source_generation"],
        content_hash=manifest["content_hash"], **auth,
        staged_manifest_digest=output_digest(manifest),
        validation_digest=output_digest(staged["validation"]),
        expected_target=tuple(sorted(target.items())),
    )
    args = {
        "entities": staged["entities"], "relationships": staged["relationships"],
        "generation_id": generation, "source_generation": context.source_generation,
        "content_hash": context.content_hash, **auth, "validation": staged["validation"],
    }
    products = ontology_generation_products(**args)
    catalog = _generation_catalog(
        products, {name: {"version": None} for name in products},
        generation, context.content_hash,
    )
    policy = GenerationOutputPolicy(
        context=context, manifest=describe_outputs(products, lake, catalog),
        protected_roots=(str(tmp_path / "production"),),
        entity_types=tuple(sorted(ONTOLOGY_ENTITY_TYPES)),
        relationship_triples=tuple(sorted(ONTOLOGY_RELATIONSHIP_TYPES)),
    )
    return SimpleNamespace(
        service=service, lake=lake, sink=sink, catalogs=catalogs, target=target,
        context=context, policy=policy, args=args, staged=staged, auth=auth, products=products,
    )


def materialize(env, **kwargs):
    return env.service.materialize_ontology_generation(
        **env.args, output_policy=env.policy, output_context=env.context, **kwargs,
    )


def test_complete_registry_empty_tables_and_catalog_accepted(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    checks = []
    written = materialize(env, guard=lambda: checks.append(True))
    assert set(written) == set(env.products)
    assert len(env.sink.calls) == len(env.products)
    assert any(not rows for _, rows, _ in env.sink.calls)
    assert len(checks) == len(env.products) + 1
    assert len(env.catalogs) == 1
    catalog = env.catalogs[0][2]
    assert {row["name"] for row in catalog["tables"]} == set(written)
    assert all(row["deltaVersion"] == 1 for row in catalog["tables"])
    assert catalog["generationId"] == env.context.generation_id


@pytest.mark.parametrize("kind", ["entity", "late-active-triple", "inactive-triple"])
def test_candidate_closure_precedes_product_builder(tmp_path, monkeypatch, kind):
    env = example(tmp_path, monkeypatch)
    if kind == "entity":
        env.args["entities"] = [{"entity_type": "ZZZUnknown"}]
    else:
        env.args["relationships"] = [{
            "subject_type": "ZZZUnknown", "predicate": "ZZZUnreviewed",
            "object_type": "ZZZUnknown", "lifecycle_status":
                "inactive" if kind == "inactive-triple" else "active",
        }]

    def forbidden(*args, **kwargs):
        pytest.fail("unknown closure reached product builder")

    monkeypatch.setattr(sync, "ontology_generation_products", forbidden)
    with pytest.raises(PublicationSafetyError, match="closure"):
        materialize(env)
    assert env.sink.calls == env.catalogs == []


@pytest.mark.parametrize(
    "change",
    ["last-content", "last-count", "last-schema", "last-uri", "missing", "extra",
     "catalog", "native", "config", "candidate", "validation"],
)
def test_complete_manifest_mismatch_has_zero_sink_calls(tmp_path, monkeypatch, change):
    env = example(tmp_path, monkeypatch)
    manifest = env.policy.manifest
    tables = list(manifest.tables)
    if change.startswith("last-"):
        field, value = {
            "last-content": ("content_digest", "0" * 64),
            "last-count": ("row_count", 987),
            "last-schema": ("arrow_schema_digest", "0" * 64),
            "last-uri": ("physical_uri", str(tmp_path / "wrong-table")),
        }[change]
        tables[-1] = replace(tables[-1], **{field: value})
        manifest = replace(manifest, tables=tuple(tables))
    elif change == "missing":
        manifest = replace(manifest, tables=manifest.tables[:-1])
    elif change == "extra":
        tables.append(replace(tables[-1], logical_name="zz_extra", physical_uri=str(tmp_path / "extra")))
        manifest = replace(manifest, tables=tuple(tables))
    elif change == "catalog":
        manifest = replace(manifest, catalog_json='{"wrong":"last-output"}')
    elif change == "native":
        env.service.ontology_publisher = SimpleNamespace(publish=lambda **kw: pytest.fail("native call"))
    elif change == "config":
        env.lake.table_schema = "unreviewed"
    elif change == "candidate":
        env.context = replace(env.context, staged_manifest_digest="different")
    else:
        env.args["validation"] = {"passed": False}
    with pytest.raises(PublicationSafetyError, match="output_manifest"):
        env.policy = replace(env.policy, manifest=manifest)
        materialize(env)
    assert env.sink.calls == env.catalogs == []


@pytest.mark.parametrize("change", ["duplicate", "protected", "catalog-parent", "native-policy"])
def test_policy_rejects_aliases_production_and_native(tmp_path, monkeypatch, change):
    env = example(tmp_path, monkeypatch)
    manifest = env.policy.manifest
    if change == "native-policy":
        manifest = replace(manifest, native_enabled=True)
    elif change == "catalog-parent":
        manifest = replace(manifest, catalog_uri=str(tmp_path / "lake"))
    else:
        tables = list(manifest.tables)
        tables[-1] = replace(
            tables[-1],
            physical_uri=tables[0].physical_uri if change == "duplicate"
            else str(tmp_path / "production/Tables/injected"),
        )
        manifest = replace(manifest, tables=tuple(tables))
    with pytest.raises(PublicationSafetyError):
        replace(env.policy, manifest=manifest)
    assert env.sink.calls == env.catalogs == []


@pytest.mark.parametrize("field", ["local_root", "table_schema", "workspace_id", "storage_options"])
def test_guard_cannot_redirect_sink_after_preflight(tmp_path, monkeypatch, field):
    env = example(tmp_path, monkeypatch)

    def guard():
        setattr(env.lake, field, {
            "local_root": tmp_path / "production",
            "table_schema": "other", "workspace_id": "other",
            "storage_options": {"secret": "DO_NOT_LEAK"},
        }[field])

    with pytest.raises(PublicationSafetyError, match="target_changed") as caught:
        materialize(env, guard=guard)
    assert "DO_NOT_LEAK" not in str(caught.value)
    assert env.sink.calls == env.catalogs == []


def composed(env, tmp_path, policies, *, isolated=True):
    materializer = CandidateGenerationMaterializer(
        storage=SimpleNamespace(read_pointer=lambda: None),
        documents=OneLakeDocumentStore(str(tmp_path / "control")),
        service=env.service, authorizer=None, target_id="synthetic",
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        expected_target=env.target, definition_fingerprint=lambda: "synthetic-definition",
        isolated_output=isolated, output_policies=policies,
    )
    materializer.bind(owner_id="synthetic-owner", fence=1, predecessor=None, pointer_etag=None)
    materializer.lease.assert_held = lambda: None
    materializer._guard_write = lambda: None
    materializer._reauthorize_admission = lambda: None
    materializer._reauthorize_restore = lambda: None
    materializer._catalog_read = lambda: env.catalogs[-1][2]
    materializer.receipts.put = lambda generation, receipt: receipt
    return materializer


@pytest.mark.parametrize("operation", ["admission", "restoration"])
def test_composition_passes_independently_bound_operation_policy(tmp_path, monkeypatch, operation):
    env = example(tmp_path, monkeypatch, operation=operation, generation="retained" if operation == "restoration" else "new")
    materializer = composed(env, tmp_path, (env.policy,))
    result = materializer._materialize(
        env.context.generation_id, env.staged, env.auth,
        kind="restoration" if operation == "restoration" else "materialization",
    )
    assert set(result["products"]) == set(env.products)
    assert result["generation_id"] == env.context.generation_id
    assert len(env.catalogs) == 1


def test_admission_policy_cannot_authorize_restoration(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    materializer = composed(env, tmp_path, (env.policy,))
    with pytest.raises(PublicationSafetyError, match="operation_policy_missing"):
        materializer._materialize(env.context.generation_id, env.staged, env.auth, kind="restoration")
    assert env.sink.calls == env.catalogs == []


def test_isolated_composition_requires_explicit_policy(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    with pytest.raises(PublicationSafetyError, match="policies_missing"):
        composed(env, tmp_path, ())
    assert env.sink.calls == env.catalogs == []


def test_legacy_service_default_does_not_require_policy(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    result = env.service.materialize_ontology_generation(**env.args)
    assert set(result) == set(env.products)
    assert len(env.catalogs) == 1


@pytest.mark.parametrize("kind", ["product", "catalog", "schema"])
def test_final_generated_output_is_checked_before_first_write(tmp_path, monkeypatch, kind):
    env = example(tmp_path, monkeypatch)
    if kind == "product":
        def altered_products(*args, **kwargs):
            products = ontology_generation_products(*args, **kwargs)
            products[max(products)].append({"unreviewed": "last-row"})
            return products
        monkeypatch.setattr(sync, "ontology_generation_products", altered_products)
    elif kind == "catalog":
        def altered_catalog(*args):
            catalog = _generation_catalog(*args)
            catalog["tables"][-1]["rowCount"] += 1
            return catalog
        monkeypatch.setattr(sync, "_generation_catalog", altered_catalog)
    else:
        original = sync.schema_for
        last = env.policy.manifest.tables[-1].logical_name

        def altered_schema(name):
            schema = original(name)
            if name == last:
                # Same column names, different type: catalog-only checking misses this.
                return schema.set(0, pa.field(schema.names[0], pa.int32()))
            return schema
        monkeypatch.setattr(sync, "schema_for", altered_schema)
    with pytest.raises(PublicationSafetyError, match="complete_manifest"):
        materialize(env)
    assert env.sink.calls == env.catalogs == []


def test_original_candidate_and_sink_mutation_do_not_change_later_products(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    calls = []

    def guard():
        # A caller-held mutable validation mapping must not alter built quality rows.
        env.args["validation"]["passed"] = False

    original_write = env.sink.write

    def mutate_rows(uri, rows, **kwargs):
        result = original_write(uri, rows, **kwargs)
        rows.append({"unreviewed": True})
        calls.append(True)
        return result

    env.sink.write = mutate_rows
    materialize(env, guard=guard)
    assert len(calls) == len(env.products)
    assert all(not any("unreviewed" in row for row in rows) for _, rows, _ in env.sink.calls)
    quality = next(rows for uri, rows, _ in env.sink.calls if uri.endswith("ontology_quality_report"))
    assert quality[0]["passed"] is True


@pytest.mark.parametrize("root", [
    "abfss://w@onelake.dfs.fabric.microsoft.com/l/Tables/%2fother",
    "abfss://w@onelake.dfs.fabric.microsoft.com/l/Tables/../other",
    "abfss://w@onelake.dfs.fabric.microsoft.com/l/Tables/%2E%2E/other",
    "abfss://w@onelake.dfs.fabric.microsoft.com/l/Tables//other",
])
def test_encoded_and_dot_segment_protected_roots_are_not_accepted(tmp_path, monkeypatch, root):
    env = example(tmp_path, monkeypatch)
    with pytest.raises(PublicationSafetyError, match="location"):
        replace(env.policy, protected_roots=(root,))
    assert env.sink.calls == env.catalogs == []


def test_symlink_production_alias_is_rejected(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    (tmp_path / "production").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "production", target_is_directory=True)
    tables = list(env.policy.manifest.tables)
    tables[-1] = replace(tables[-1], physical_uri=str(tmp_path / "alias/table"))
    with pytest.raises(PublicationSafetyError, match="protected_destination"):
        replace(env.policy, manifest=replace(env.policy.manifest, tables=tuple(tables)))


def test_remote_sink_is_explicitly_unsupported_without_cloud_calls(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    env.lake.local_root = None
    with pytest.raises(PublicationSafetyError, match="unsupported_sink"):
        materialize(env)
    assert env.sink.calls == env.catalogs == []


def test_wrong_retained_content_fails_independent_restoration_binding(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch, operation="restoration", generation="retained")
    materializer = composed(env, tmp_path, (env.policy,))
    env.staged["manifest"]["content_hash"] = "different-retained-content"
    with pytest.raises(PublicationSafetyError, match="operation_policy_missing"):
        materializer._materialize("retained", env.staged, env.auth, kind="restoration")
    assert env.sink.calls == env.catalogs == []


def test_frozen_schema_and_catalog_survive_callback_registry_mutation(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("write-time callback changed the validated schema/catalog")

    def guard():
        monkeypatch.setattr(sync, "schema_for", forbidden)
        monkeypatch.setattr(sync, "_generation_catalog", forbidden)

    materialize(env, guard=guard)
    assert len(env.sink.calls) == len(env.products)
    assert len(env.catalogs) == 1


def test_known_nonempty_candidate_preserves_canonical_and_typed_rows(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    entity_type = next(name for name in ONTOLOGY_ENTITY_TYPES if name != "ContainerImageExposure")
    row = {
        "entity_type": entity_type, "resource_id": "synthetic-resource",
        "tenant_id": "synthetic-tenant", "subscription_id": "synthetic-subscription",
        "timestamp": "2026-01-01T00:00:00Z", "change_version": "synthetic-change",
        "ingestion_run_id": "synthetic-run", "lifecycle_status": "active",
    }
    env.args["entities"] = [row]
    products = ontology_generation_products(**env.args)
    catalog = _generation_catalog(
        products, {name: {"version": None} for name in products},
        env.context.generation_id, env.context.content_hash,
    )
    env.policy = replace(
        env.policy, manifest=describe_outputs(products, env.lake, catalog),
    )
    materialize(env)
    canonical = next(rows for uri, rows, _ in env.sink.calls if uri.endswith("ontology_entities"))
    assert canonical == [row]
    assert sum(row in rows for _, rows, _ in env.sink.calls) >= 2


@pytest.mark.parametrize("operation", ["admission", "restoration"])
def test_composition_rejects_unknown_inactive_triple_before_either_builder(
    tmp_path, monkeypatch, operation,
):
    import ontology_discovery.maintenance_materialization as maintenance

    env = example(tmp_path, monkeypatch, operation=operation)
    materializer = composed(env, tmp_path, (env.policy,))
    env.staged["relationships"] = [{
        "subject_type": "Unknown", "predicate": "unknown", "object_type": "Unknown",
        "lifecycle_status": "inactive",
    }]

    def forbidden(*args, **kwargs):
        pytest.fail("unvalidated candidate reached product builder")

    monkeypatch.setattr(sync, "ontology_generation_products", forbidden)
    monkeypatch.setattr(maintenance, "ontology_generation_products", forbidden)
    with pytest.raises(PublicationSafetyError, match="relationship_closure"):
        materializer._materialize(
            env.context.generation_id, env.staged, env.auth,
            kind="restoration" if operation == "restoration" else "materialization",
        )
    assert env.sink.calls == env.catalogs == []


def test_mutation_after_first_write_stops_without_redirecting_remaining_sinks(tmp_path, monkeypatch):
    env = example(tmp_path, monkeypatch)
    guards = []

    def guard():
        guards.append(True)
        if len(guards) == 2:
            env.lake.table_schema = "unreviewed"

    with pytest.raises(PublicationSafetyError, match="target_changed"):
        materialize(env, guard=guard)
    assert len(env.sink.calls) == 1
    assert "unreviewed" not in env.sink.calls[0][0]
    assert env.catalogs == []


def test_source_type_to_table_alias_is_rejected(tmp_path, monkeypatch):
    import fabric.maintenance_output as output

    env = example(tmp_path, monkeypatch)
    monkeypatch.setattr(output, "ontology_relationship_table", lambda *triple: "ontology_duplicate")
    with pytest.raises(PublicationSafetyError, match="type_mapping_alias"):
        replace(env.policy)
    assert env.sink.calls == env.catalogs == []


@pytest.mark.parametrize("field", ["onelake", "delta", "ontology_publisher", "ontology_id"])
def test_callback_cannot_replace_target_or_enable_native(tmp_path, monkeypatch, field):
    env = example(tmp_path, monkeypatch)

    def guard():
        replacement = {
            "onelake": OneLakeWriter("other", "other", local_root=tmp_path / "production"),
            "delta": Sink(), "ontology_publisher": object(), "ontology_id": "unreviewed",
        }[field]
        setattr(env.service, field, replacement)

    with pytest.raises(PublicationSafetyError, match="target_changed"):
        materialize(env, guard=guard)
    assert env.sink.calls == env.catalogs == []


@pytest.mark.parametrize("redirect", ["Tables", "Files", "Files/ontology/metadata"])
@pytest.mark.parametrize("boundary", ["first", "midrun", "catalog"])
def test_callback_descendant_symlink_redirect_stops_sinks(
    tmp_path, monkeypatch, redirect, boundary,
):
    env = example(tmp_path, monkeypatch)
    protected = tmp_path / "production"
    protected.mkdir()
    env.lake.local_root.mkdir()
    checks = []
    trigger = {"first": 1, "midrun": 2, "catalog": len(env.products) + 1}[boundary]

    def guard():
        checks.append(True)
        if len(checks) == trigger:
            path = env.lake.local_root / redirect
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(protected, target_is_directory=True)

    with pytest.raises(PublicationSafetyError, match="destination"):
        materialize(env, guard=guard)
    assert len(env.sink.calls) == trigger - 1
    assert env.catalogs == []


@pytest.mark.parametrize("redirect", [
    "Tables", "Tables/ontology_entities", "Files",
    "Files/ontology/metadata", "Files/ontology/metadata/catalog.json",
])
def test_preexisting_descendant_symlink_is_rejected_even_inside_target(
    tmp_path, monkeypatch, redirect,
):
    env = example(tmp_path, monkeypatch)
    env.lake.local_root.mkdir()
    destination = env.lake.local_root / "otherwise-safe"
    destination.mkdir()
    path = env.lake.local_root / redirect
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(destination, target_is_directory=True)
    # Manifest URI string equality cannot bless even inside-target links.
    with pytest.raises(PublicationSafetyError, match="destination"):
        materialize(env)
    assert env.sink.calls == env.catalogs == []
