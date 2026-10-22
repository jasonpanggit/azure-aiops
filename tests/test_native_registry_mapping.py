from __future__ import annotations

from copy import deepcopy

import pyarrow as pa
import pytest

from fabric.native_registry_mapping import (
    KEY_COLUMNS,
    TABLE,
    native_registry_mapping_schema,
    project_native_registry_mapping,
)


def products():
    registry = {
        "resource_id": "/registry",
        "entity_type": "ContainerRegistry",
        "tenant_id": "tenant",
        "lifecycle_status": "active",
    }
    exposures = [{
        "resource_id": f"/exposure/{key}",
        "entity_type": "ContainerImageExposure",
        "tenant_id": "tenant",
        "registry_resource_id": "/registry",
        "lifecycle_status": "active",
    } for key in ("b", "a")]
    edges = [{
        "resource_id": f"edge-{key}",
        "subject_id": f"/exposure/{key}",
        "object_id": "/registry",
        "subject_type": "ContainerImageExposure",
        "predicate": "exposes",
        "object_type": "ContainerRegistry",
        "tenant_id": "tenant",
        "lifecycle_status": "active",
        "payload_json": "{}",
    } for key in ("b", "a")]
    return edges, exposures, [registry]


def test_native_projection_preserves_exact_two_column_schema_and_stable_pairs():
    source = products()
    before = deepcopy(source)
    result = project_native_registry_mapping(*source)
    assert result == [
        {"subject_id": "/exposure/a", "object_id": "/registry"},
        {"subject_id": "/exposure/b", "object_id": "/registry"},
    ]
    assert project_native_registry_mapping(*[list(reversed(rows)) for rows in source]) == result
    assert source == before
    assert KEY_COLUMNS == ("subject_id", "object_id")
    assert TABLE == "ontology_rel_exposes_container_image_exposure_container_registry"
    schema = native_registry_mapping_schema()
    assert schema.names == ["subject_id", "object_id"]
    assert all(field.type == pa.string() and field.nullable for field in schema)
    assert pa.Table.from_pylist(result, schema=schema).to_pylist() == result


@pytest.mark.parametrize("target,key,value", [
    (0, "predicate", "impacts"),
    (0, "subject_type", "Resource"),
    (0, "object_type", "Resource"),
    (0, "subject_id", "/missing"),
    (0, "object_id", "/missing"),
    (0, "tenant_id", "another-tenant"),
    (0, "resource_id", ""),
    (0, "lifecycle_status", "retired"),
    (1, "entity_type", "Resource"),
    (1, "tenant_id", "another-tenant"),
    (1, "registry_resource_id", "/missing"),
    (1, "registry_resource_id", None),
    (1, "registry_resource_id", " /registry"),
    (1, "resource_id", ""),
    (1, "lifecycle_status", "retired"),
    (2, "entity_type", "Resource"),
    (2, "tenant_id", "another-tenant"),
])
def test_invalid_or_mismatched_bindings_fail_closed(target, key, value):
    source = products()
    source[target][0][key] = value
    with pytest.raises(ValueError, match="Native registry mapping"):
        project_native_registry_mapping(*source)


@pytest.mark.parametrize("target", [0, 1, 2])
def test_duplicate_product_identities_are_not_silently_collapsed(target):
    source = products()
    source[target].append(deepcopy(source[target][0]))
    with pytest.raises(ValueError, match="duplicate"):
        project_native_registry_mapping(*source)


def test_duplicate_pairs_with_different_edge_ids_are_rejected():
    edges, exposures, registries = products()
    edges.append({**edges[0], "resource_id": "different"})
    with pytest.raises(ValueError, match="duplicate"):
        project_native_registry_mapping(edges, exposures, registries)


def test_missing_generated_edge_is_not_an_accepted_subset():
    edges, exposures, registries = products()
    with pytest.raises(ValueError, match="incomplete"):
        project_native_registry_mapping(edges[:1], exposures, registries)


def test_unbound_exposure_is_explicit_not_inferred_from_target_or_hostname():
    edges, exposures, registries = products()
    exposures[0].update(
        registry_resource_id="", targetResourceId="/registry", registryHost="acr.azurecr.io",
    )
    result = project_native_registry_mapping(edges[1:], exposures, registries)
    assert result == [{"subject_id": "/exposure/a", "object_id": "/registry"}]


def test_missing_registry_is_not_silently_skipped():
    edges, exposures, _ = products()
    with pytest.raises(ValueError, match="missing"):
        project_native_registry_mapping(edges, exposures, [])


def test_empty_products_project_empty_mapping_for_governed_retirement():
    assert project_native_registry_mapping([], [], []) == []


@pytest.mark.parametrize("target", [0, 1, 2])
@pytest.mark.parametrize("invalid", [None, {}, "rows", [None], [{}] * 100_001])
def test_malformed_or_unbounded_products_are_rejected(target, invalid):
    source = list(products())
    source[target] = invalid
    with pytest.raises(ValueError, match="Native registry mapping"):
        project_native_registry_mapping(*source)


def test_missing_scalar_is_not_treated_as_explicitly_unbound():
    source = products()
    del source[1][0]["registry_resource_id"]
    with pytest.raises(ValueError, match="explicit registry_resource_id"):
        project_native_registry_mapping(*source)


def test_tuple_products_use_the_same_projection_contract():
    source = products()
    assert project_native_registry_mapping(*(tuple(rows) for rows in source)) == (
        project_native_registry_mapping(*source)
    )
