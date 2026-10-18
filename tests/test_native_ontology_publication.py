from __future__ import annotations

import base64
import json
from copy import deepcopy
from types import SimpleNamespace

import pyarrow as pa
import pytest
from deltalake import write_deltalake
from test_ontology_publisher_runtime import _candidate

from fabric.dataset_mapper import ontology_entity_table, ontology_relationship_table
from ontology.native_publication import NativeOntologyPublication
from ontology.ontology_publisher import OntologyPublisher
from ontology_discovery import publisher_cli
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter


class NativeManager:
    def __init__(self):
        self.item = None
        self.definition = {}
        self.writes = []
        self.corrupt_readback = False

    def resolve(self, **kwargs):
        return deepcopy(self.item)

    def get_definition(self, item_id):
        return {} if self.corrupt_readback else deepcopy(self.definition)

    def create(self, name, definition):
        self.writes.append("create")
        self.item = {"id": "native-item", "displayName": name}
        self.definition = deepcopy(definition)
        return deepcopy(self.item)

    def update_definition(self, item_id, definition):
        self.writes.append("update")
        self.definition = deepcopy(definition)


@pytest.fixture
def native(tmp_path):
    delta = DeltaWriter()
    lake = OneLakeWriter("workspace", "lakehouse", local_root=tmp_path)
    candidate = _candidate()
    marker = {
        "status": "completed", "failed_records": 0,
        "ingestion_run_id": "run-17", "source_run_id": "source-17",
        "timestamp": "2026-09-07T00:00:00Z",
        "ontology_entity_version": 0, "ontology_relationship_version": 0,
    }
    tables = {
        "metadata_ingestion_state": [marker],
        "ontology_entities": candidate["entities"],
        "ontology_relationships": candidate["relationships"],
    }
    for entity in candidate["entities"]:
        tables[ontology_entity_table(entity["entity_type"])] = [entity]
    relationship = candidate["relationships"][0]
    tables[ontology_relationship_table(
        relationship["subject_type"], relationship["predicate"], relationship["object_type"]
    )] = [relationship]
    catalog = [
        {"name": name, "type": "Managed"} for name in tables if name.startswith("ontology_")
    ]
    for name, rows in tables.items():
        layer, suffix = name.split("_", 1)
        delta.write(lake.table_uri(layer, suffix), rows, mode="overwrite", required_columns=None)
    manager = NativeManager()
    publication = NativeOntologyPublication(
        delta=delta, onelake=lake,
        lakehouse=SimpleNamespace(list_tables=lambda _: catalog),
        publisher=OntologyPublisher(
            manager, workspace_id="workspace", lakehouse_id="lakehouse", source_schema=""
        ),
        ontology_name="Operational_Context_Ontology_v2",
    )
    return SimpleNamespace(
        publication=publication, delta=delta, lake=lake, manager=manager,
        catalog=catalog, candidate=candidate, marker=marker,
    )


def test_preview_and_publish_only_native_item_with_exact_definition(native):
    preview = native.publication.preview(source_generation="run-17")
    assert native.manager.writes == []
    assert preview["entity_type_count"] == 2
    assert preview["relationship_type_count"] == 1
    assert preview["binding_count"] == 3
    assert preview["source_run_id"] == "source-17"
    assert preview["preview_hash"] == native.publication.preview(
        source_generation="run-17"
    )["preview_hash"]
    result = native.publication.publish(
        source_generation="run-17", expected_preview_hash=preview["preview_hash"]
    )
    assert result["definition_verified"] is True
    assert result["item_id"] == "native-item"
    assert native.manager.writes == ["create"]
    assert all(native.delta.version(uri) == version for uri, version in preview["heads"].items())
    for part in preview["definition"]["parts"]:
        if "/Contextualizations/" in part["path"]:
            payload = json.loads(base64.b64decode(part["payload"]))
            assert next(iter(payload["dataBindingTable"])) == "sourceType"


def test_existing_matching_native_item_is_read_only(native):
    preview = native.publication.preview(source_generation="run-17")
    native.manager.item = {"id": "existing"}
    native.manager.definition = preview["definition"]
    preview = native.publication.preview(source_generation="run-17")
    result = native.publication.publish(
        source_generation="run-17", expected_preview_hash=preview["preview_hash"]
    )
    assert result["action"] == "unchanged"
    assert native.manager.writes == []


@pytest.mark.parametrize("generation", ["", "source-17", "earlier-run"])
def test_preview_requires_exact_latest_completed_ingestion(native, generation):
    with pytest.raises(ValueError, match="generation|ingestion"):
        native.publication.preview(source_generation=generation)
    assert native.manager.writes == []


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [("status", "failed", "No completed"), ("failed_records", 1, "incomplete"),
     ("source_run_id", "", "provenance"), ("ontology_entity_version", -1, "invalid Delta")],
)
def test_incomplete_source_never_reaches_native_write(native, field, value, error):
    native.marker[field] = value
    native.delta.write(
        native.lake.table_uri("metadata", "ingestion_state"), [native.marker],
        mode="overwrite", required_columns=None,
    )
    with pytest.raises(ValueError, match=error):
        native.publication.preview(source_generation="run-17")
    assert native.manager.writes == []


def test_partial_canonical_head_is_rejected(native):
    rows = deepcopy(native.candidate["entities"])
    rows[0]["change_version"] = "v2"
    native.delta.write(
        native.lake.table_uri("ontology", "entities"), rows,
        mode="overwrite", required_columns=None,
    )
    assert native.delta.version(native.lake.table_uri("ontology", "entities")) == 1
    with pytest.raises(ValueError, match="head"):
        native.publication.preview(source_generation="run-17")


@pytest.mark.parametrize("problem", ["missing", "external", "wrong_rows", "wrong_schema"])
def test_unusable_or_mismatched_typed_binding_is_rejected(native, problem, monkeypatch):
    name = ontology_entity_table("VirtualMachine")
    if problem == "missing":
        native.catalog[:] = [table for table in native.catalog if table["name"] != name]
    elif problem == "external":
        next(table for table in native.catalog if table["name"] == name)["type"] = "External"
    elif problem == "wrong_rows":
        row = deepcopy(native.candidate["entities"][0])
        row["name"] = "not-the-completed-source"
        row["change_version"] = "v2"
        native.delta.write(
            native.lake.table_uri("ontology", name.removeprefix("ontology_")),
            [row], mode="overwrite", required_columns=None,
        )
    else:
        describe = native.delta.describe

        def wrong_schema(uri, *, version):
            result = describe(uri, version=version)
            result["schema"]["fields"][0]["type"] = "long"
            return result

        monkeypatch.setattr(native.delta, "describe", wrong_schema)
    with pytest.raises(ValueError, match="managed table|differs|string columns"):
        native.publication.preview(source_generation="run-17")
    assert native.manager.writes == []


def test_stale_preview_is_rejected_before_any_native_write(native):
    preview = native.publication.preview(source_generation="run-17")
    native.manager.item = {"id": "concurrently-created"}
    native.manager.definition = preview["definition"]
    with pytest.raises(ValueError, match="preview changed"):
        native.publication.publish(
            source_generation="run-17", expected_preview_hash=preview["preview_hash"]
        )
    assert native.manager.writes == []


def test_native_creation_without_readable_definition_is_not_success(native, monkeypatch):
    preview = native.publication.preview(source_generation="run-17")
    create = native.manager.create

    def corrupt(name, definition):
        result = create(name, definition)
        native.manager.definition["parts"].pop()
        return result

    monkeypatch.setattr(native.manager, "create", corrupt)
    with pytest.raises(RuntimeError, match="readback differs"):
        native.publication.publish(
            source_generation="run-17", expected_preview_hash=preview["preview_hash"]
        )


def test_native_item_get_must_verify_exact_published_id(native, monkeypatch):
    preview = native.publication.preview(source_generation="run-17")
    resolve = native.manager.resolve

    def wrong_item(**kwargs):
        if kwargs.get("ontology_id"):
            return {"id": "wrong-item"}
        return resolve(**kwargs)

    monkeypatch.setattr(native.manager, "resolve", wrong_item)
    with pytest.raises(RuntimeError, match="item GET"):
        native.publication.publish(
            source_generation="run-17", expected_preview_hash=preview["preview_hash"]
        )


@pytest.mark.parametrize("field", ["source", "model_derived"])
def test_model_derived_canonical_edges_are_not_promoted(native, monkeypatch, field):
    read = native.delta.read

    def derived(uri, **kwargs):
        rows = read(uri, **kwargs)
        if str(uri).endswith("ontology_relationships"):
            rows[0][field] = "model" if field == "source" else True
        return rows

    monkeypatch.setattr(native.delta, "read", derived)
    with pytest.raises(ValueError, match="Model-derived"):
        native.publication.preview(source_generation="run-17")
    assert native.manager.writes == []


def test_native_cli_does_not_build_intake_or_full_sync(monkeypatch, capsys):
    config = SimpleNamespace()
    monkeypatch.setattr(publisher_cli.PublisherRuntimeConfig, "from_env", lambda: config)
    monkeypatch.setattr(
        publisher_cli, "build_publisher_runtime",
        lambda _: pytest.fail("native command must not construct intake or sync"),
    )
    calls = []

    def run(received, **kwargs):
        assert received is config
        calls.append(kwargs)
        return {"preview_hash": "approved"}

    monkeypatch.setattr(publisher_cli, "run_native_publication", run)
    assert publisher_cli.main(["native-preview", "--source-generation", "run-17"]) == 0
    assert calls == [{"source_generation": "run-17", "preview_hash": ""}]
    assert json.loads(capsys.readouterr().out)["preview_hash"] == "approved"
    with pytest.raises(SystemExit):
        publisher_cli.main(["native-publish", "--source-generation", "run-17"])
    assert len(calls) == 1
    assert publisher_cli.main([
        "native-publish", "--source-generation", "run-17", "--preview-hash", "approved", "--yes"
    ]) == 0
    assert calls[-1] == {"source_generation": "run-17", "preview_hash": "approved"}


@pytest.mark.parametrize(
    ("mode", "environment", "drill"),
    [("validation", "production", False), ("production", "validation", False),
     ("production", "production", True)],
)
def test_native_runtime_rejects_validation_or_drill_before_clients(mode, environment, drill):
    config = SimpleNamespace(runtime_mode=mode, environment=environment, drill_enabled=drill)
    with pytest.raises(PermissionError, match="non-drill production"):
        publisher_cli.run_native_publication(config, source_generation="run-17")


def test_delta_metadata_requires_pinned_valid_version(native):
    uri = native.lake.table_uri("ontology", "entities")
    assert native.delta.describe(uri, version=0)["version"] == 0
    for version in (-1, True, "0"):
        with pytest.raises(ValueError, match="non-negative integer"):
            native.delta.describe(uri, version=version)


def test_retained_metadata_requires_proven_completed_canonical_rows(native):
    previous = deepcopy(native.marker)
    for kind in ("entities", "relationships"):
        rows = deepcopy(native.candidate[kind])
        for row in rows:
            row.update(
                ingestion_run_id="run-18", ontology_version="v2",
                timestamp="2026-09-08T00:00:00Z",
            )
        write_deltalake(
            native.lake.table_uri("ontology", kind), pa.Table.from_pylist(rows),
            mode="overwrite",
        )
    current = {
        **previous, "ingestion_run_id": "run-18", "source_run_id": "source-18",
        "timestamp": "2026-09-08T00:00:00Z",
        "ontology_entity_version": 1, "ontology_relationship_version": 1,
    }
    native.delta.write(
        native.lake.table_uri("metadata", "ingestion_state"), [previous, current],
        mode="overwrite", required_columns=None,
    )
    preview = native.publication.preview(source_generation="run-18")
    assert sum(table["retained_generation_rows"] for table in preview["tables"]) == 3
    assert all(table["row_ontology_versions"] == ["v1"] for table in preview["tables"])
    assert native.manager.writes == []


def test_metadata_only_difference_without_completed_provenance_is_rejected(native):
    name = ontology_entity_table("VirtualMachine")
    row = deepcopy(native.candidate["entities"][0])
    row["ontology_version"] = "uncompleted-version"
    write_deltalake(
        native.lake.table_uri("ontology", name.removeprefix("ontology_")),
        pa.Table.from_pylist([row]), mode="overwrite",
    )
    with pytest.raises(ValueError, match="no completed generation provenance"):
        native.publication.preview(source_generation="run-17")
    assert native.manager.writes == []


def test_binding_column_mapping_is_rejected(native, monkeypatch):
    describe = native.delta.describe

    def mapped(uri, *, version):
        result = describe(uri, version=version)
        result["configuration"]["delta.columnMapping.mode"] = "name"
        return result

    monkeypatch.setattr(native.delta, "describe", mapped)
    with pytest.raises(ValueError, match="Column mapping is unsupported"):
        native.publication.preview(source_generation="run-17")
