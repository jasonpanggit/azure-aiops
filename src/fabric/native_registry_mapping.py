"""Explicit pair-table projection for the native exposure registry binding."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pyarrow as pa

TABLE = "ontology_rel_exposes_container_image_exposure_container_registry"
KEY_COLUMNS = ("subject_id", "object_id")
MAX_SOURCE_ROWS = 100_000


def native_registry_mapping_schema() -> pa.Schema:
    """Return the native-bound two-string-column schema without graph metadata."""
    return pa.schema([
        pa.field("subject_id", pa.string()),
        pa.field("object_id", pa.string()),
    ])


def project_native_registry_mapping(
    relationships: Sequence[Mapping[str, object]],
    exposure_entities: Sequence[Mapping[str, object]],
    registry_entities: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Require exact explicit-binding parity before projecting native pair rows.

    Inputs are active typed products, not an aggregate graph or an arbitrary
    subset. Bound exposures require an existing registry in the same tenant;
    unbound exposures produce no pair. No identity is inferred from image paths
    or hostnames. This helper grants no write authority and does not establish
    source freshness, locking or atomicity across upstream products.
    """
    for rows in (relationships, exposure_entities, registry_entities):
        if not isinstance(rows, (list, tuple)) or len(rows) > MAX_SOURCE_ROWS:
            raise ValueError("Native registry mapping requires bounded typed products")
        if any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("Native registry mapping rows must be mappings")

    def text(row: Mapping[str, object], key: str) -> str:
        value = row.get(key)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"Native registry mapping requires explicit {key}")
        return value

    def index(
        rows: Sequence[Mapping[str, object]], entity_type: str,
    ) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for row in rows:
            if row.get("entity_type") != entity_type or row.get("lifecycle_status") != "active":
                raise ValueError("Native registry mapping requires active typed endpoints")
            identifier = text(row, "resource_id")
            text(row, "tenant_id")
            if identifier in result:
                raise ValueError("Native registry mapping has duplicate endpoint identities")
            result[identifier] = row
        return result

    exposures = index(exposure_entities, "ContainerImageExposure")
    registries = index(registry_entities, "ContainerRegistry")
    expected: set[tuple[str, str]] = set()
    for subject, exposure in exposures.items():
        registry = exposure.get("registry_resource_id")
        if not isinstance(registry, str) or registry != registry.strip():
            raise ValueError("Native registry mapping requires explicit registry_resource_id")
        if not registry:
            continue
        endpoint = registries.get(registry)
        if endpoint is None or endpoint["tenant_id"] != exposure["tenant_id"]:
            raise ValueError("Native registry mapping registry endpoint is missing or cross-tenant")
        expected.add((subject, registry))

    pairs: set[tuple[str, str]] = set()
    relationship_ids: set[str] = set()
    for row in relationships:
        if (
            row.get("subject_type") != "ContainerImageExposure"
            or row.get("predicate") != "exposes"
            or row.get("object_type") != "ContainerRegistry"
            or row.get("lifecycle_status") != "active"
        ):
            raise ValueError("Native registry mapping requires active exposes relationships")
        identifier = text(row, "resource_id")
        pair = (text(row, "subject_id"), text(row, "object_id"))
        if identifier in relationship_ids or pair in pairs:
            raise ValueError("Native registry mapping has duplicate relationships")
        if pair not in expected or text(row, "tenant_id") != exposures[pair[0]]["tenant_id"]:
            raise ValueError("Native registry mapping relationship differs from explicit binding")
        relationship_ids.add(identifier)
        pairs.add(pair)
    if pairs != expected:
        raise ValueError("Native registry mapping relationships are incomplete")
    return [
        {"subject_id": subject, "object_id": registry}
        for subject, registry in sorted(pairs)
    ]
