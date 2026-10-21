from __future__ import annotations

import json
from pathlib import Path

import pytest
from deltalake import DeltaTable

from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import InventoryDatasetMapper
from fabric.schema_registry import schema_for
from fabric.sync_service import FabricSyncService, ontology_generation_products
from storage.datasets import DatasetStore
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter

TABLE = "ontology_container_image_exposure_entities"
REGISTRY = "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.containerregistry/registries/acr"


def _source(**overrides):
    return {
        "id": "exposure-one",
        "name": "Image exposure",
        "tenantId": "tenant1",
        "subscriptionId": "sub1",
        "connection_id": "demo",
        "registryResourceId": REGISTRY.upper(),
        "lastObservedTimestamp": "2026-10-21T00:00:00Z",
        **overrides,
    }


def _map(tmp_path: Path, sources):
    store = DatasetStore(tmp_path / "source")
    store.publish(
        {"entities/ContainerImageExposure": sources},
        {}, {"runId": "source-one", "startedAt": "2026-10-21T00:00:00Z"},
        ontology={},
    )
    return InventoryDatasetMapper().load(store.current_generation(), "publication-one")


def test_native_exposure_scalar_preserves_generic_entity_and_silver_mapping(tmp_path):
    datasets = _map(tmp_path, [_source()])
    typed = datasets[TABLE]
    assert len(typed) == 1
    generic = next(
        row for row in datasets["ontology_entities"]
        if row["entity_type"] == "ContainerImageExposure"
    )
    assert typed[0] == {
        **generic, "registry_resource_id": REGISTRY, "connection_id": "demo",
    }
    assert typed[0]["registry_resource_id"] == (
        datasets["silver_container_image_exposure"][0]["registry_resource_id"]
    )
    assert json.loads(typed[0]["payload_json"])["registryResourceId"] == REGISTRY.upper()
    assert not DataQualityValidator().validate_table(TABLE, typed).failures
    assert "registry_resource_id" not in schema_for("ontology_entities").names
    assert "registry_resource_id" not in schema_for("ontology_application_entities").names


def test_missing_registry_remains_explicitly_unbound_without_id_inference(tmp_path):
    datasets = _map(tmp_path, [_source(
        id=REGISTRY + "/images/image", registryResourceId=None, connection_id=None,
    )])
    assert datasets[TABLE][0]["registry_resource_id"] == ""
    assert datasets[TABLE][0]["connection_id"] == ""
    assert len(datasets[TABLE]) == 1


@pytest.mark.parametrize("alias", [
    "connection_id", "connectionId",
    "subscription_connection_id", "subscriptionConnectionId",
])
def test_connection_scope_uses_only_explicit_existing_aliases(tmp_path, alias):
    source = _source()
    del source["connection_id"]
    source[alias] = "demo"
    assert _map(tmp_path, [source])[TABLE][0]["connection_id"] == "demo"


@pytest.mark.parametrize("delta", [
    {"registryResourceId": REGISTRY + "-different"},
    {"tenantId": "foreign"},
    {"subscriptionId": "foreign"},
    {"connection_id": "foreign"},
])
def test_conflicting_or_cross_scope_duplicate_binding_is_rejected(tmp_path, delta):
    with pytest.raises(ValueError, match="ambiguous or cross-scope"):
        _map(tmp_path, [_source(), _source(**delta)])


@pytest.mark.parametrize(("delta", "error"), [
    ({"connectionId": "foreign"}, ValueError),
    ({"registryResourceId": {"id": REGISTRY}}, TypeError),
    ({"connection_id": ["demo"]}, TypeError),
])
def test_invalid_or_conflicting_scalar_scope_is_rejected(tmp_path, delta, error):
    with pytest.raises(error, match="Container exposure"):
        _map(tmp_path, [_source(**delta)])


@pytest.mark.parametrize("sources", [[], [_source()]])
def test_native_exposure_delta_and_empty_shape_keep_ontology_metadata(tmp_path, sources):
    rows = _map(tmp_path, sources)[TABLE]
    schema = schema_for(TABLE)
    generic = schema_for("ontology_entities")
    assert schema.names == [*generic.names, "registry_resource_id", "connection_id"]
    for field in generic:
        assert schema.field(field.name) == field
    writer = DeltaWriter()
    target = tmp_path / "typed"
    previous_rows = [{name: row[name] for name in generic.names} for row in rows]
    writer.write(str(target), previous_rows, mode="overwrite", schema=generic)
    writer.write(str(target), rows, mode="overwrite", schema=schema)
    materialized = DeltaTable(str(target)).to_pyarrow_table()
    assert materialized.schema.names == schema.names
    assert materialized.to_pylist() == rows
    replay = writer.write(str(target), rows, mode="overwrite", schema=schema)
    if rows:
        assert replay.skipped


def test_typed_schema_requires_both_additive_scalar_columns(tmp_path):
    row = _map(tmp_path, [_source()])[TABLE][0]
    for name in ("registry_resource_id", "connection_id"):
        invalid = {key: value for key, value in row.items() if key != name}
        assert DataQualityValidator().validate_table(TABLE, [invalid]).failures


def test_lifecycle_rebuild_and_candidate_publication_preserve_scalar_contract(tmp_path, monkeypatch):
    datasets = _map(tmp_path, [_source()])
    service = FabricSyncService(
        source_root=tmp_path / "source",
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lake"),
        delta_writer=DeltaWriter(), validator=DataQualityValidator(),
    )
    monkeypatch.setattr(service, "_authoritative_ontology_predecessor", lambda: ([], []))
    synchronized = service._synchronize_ontology(
        datasets, "version-two", "2026-10-21T01:00:00Z",
    )
    row = synchronized[TABLE][0]
    assert row["registry_resource_id"] == REGISTRY
    assert row["connection_id"] == "demo"
    assert row["ontology_version"] == "version-two"
    assert not DataQualityValidator().validate_table(TABLE, [row]).failures
    products = ontology_generation_products(
        synchronized["ontology_entities"], synchronized["ontology_relationships"],
        generation_id="candidate-one", source_generation="source-one",
        content_hash="content", authorization_digest="auth",
        attestation_digest="attestation", validation={},
    )
    assert products[TABLE] == synchronized[TABLE]
    assert products["ontology_entities"] == synchronized["ontology_entities"]


def test_generic_payload_scope_cannot_rebind_typed_ontology_entity(tmp_path):
    from fabric.dataset_mapper import container_exposure_ontology_rows

    generic = _map(tmp_path, [_source()])["ontology_entities"]
    exposure = next(row for row in generic if row["entity_type"] == "ContainerImageExposure")
    payload = json.loads(exposure["payload_json"])
    payload["tenantId"] = "foreign"
    with pytest.raises(ValueError, match="scope mismatch"):
        container_exposure_ontology_rows([
            {**exposure, "payload_json": json.dumps(payload)},
        ])


def test_retired_candidate_keeps_history_but_no_typed_membership(tmp_path):
    exposure = next(
        row for row in _map(tmp_path, [_source()])["ontology_entities"]
        if row["entity_type"] == "ContainerImageExposure"
    )
    retired = {**exposure, "lifecycle_status": "retired"}
    products = ontology_generation_products(
        [retired], [], generation_id="candidate-one",
        source_generation="source-one", content_hash="content",
        authorization_digest="auth", attestation_digest="attestation",
        validation={},
    )
    assert products["ontology_entities"] == [retired]
    assert products[TABLE] == []
