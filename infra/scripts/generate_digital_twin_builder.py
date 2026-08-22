#!/usr/bin/env python3
"""Generate a Fabric Digital Twin Builder definition from the live ontology.

Digital Twin Builder's schema (entity types, relationship types, and
lakehouse-table mappings) is defined by a small, documented JSON structure
(see infra/README.md), but creating/updating the item is only supported for
*user* identities -- not service principals or managed identities. That means
this generator cannot be wired into the SPN-driven Terraform pipeline; it is
meant to be run by a human (after `az login`) whenever the ontology's entity
or relationship *types* change, then pushed once via `push_digital_twin_builder.py`.

New subscriptions being onboarded do NOT require re-running this: onboarding
only adds *rows* to the existing ontology tables (handled by the normal
`fabric sync` pipeline), not new entity/relationship *types*. This script
only needs to be re-run when `ONTOLOGY_ENTITY_TYPES` in
`src/fabric/dataset_mapper.py` gains/loses an entity type, or when a new
relationship shape is introduced.

The generator is data-driven: it lists the tables actually present in the
lakehouse (`ontology_*_entities` and `ontology_rel_*`), rather than
hardcoding a catalog, so it can never drift from what the sync pipeline has
actually written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Base entity type IDs from Fabric's built-in taxonomy. "2" is the generic
# base type used by the tutorial/schema examples; Fabric assigns real IDs
# on creation, but the definition upload requires *some* stable placeholder.
_BASE_ENTITY_TYPE_ID = "2"
_NAMESPACE = "usertypes"

# Deterministic ID allocation: Fabric requires entity/relationship type IDs
# greater than 10,000. Docs don't state an explicit upper bound, but testing
# against the live API shows IDs must fit within 47 bits (values >= 2**47
# consistently fail with ALMOperationImportFailed on EntityType import,
# while values below it succeed) -- so IDs are capped well under that limit.
# We derive stable IDs from a hash of the name so the same ontology always
# regenerates identical IDs (idempotent re-push).
_MAX_ID = 2**46


def _stable_id(name: str, *, floor: int = 10_000) -> str:
    import hashlib

    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    value = int(digest, 16) % _MAX_ID
    return str(max(value, floor))


def _pascal_to_words(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value)


def list_lakehouse_tables(
    workspace_id: str, lakehouse_id: str, *, storage_options: dict[str, str]
) -> list[str]:
    """List table (folder) names under Tables/ in the lakehouse via ADLS Gen2 listing."""
    from azure.storage.filedatalake import DataLakeServiceClient
    from azure.identity import ClientSecretCredential

    credential = ClientSecretCredential(
        tenant_id=storage_options["azure_storage_tenant_id"],
        client_id=storage_options["azure_storage_client_id"],
        client_secret=storage_options["azure_storage_client_secret"],
    )
    account_url = "https://onelake.dfs.fabric.microsoft.com"
    service = DataLakeServiceClient(account_url=account_url, credential=credential)
    file_system = service.get_file_system_client(workspace_id)
    directory = file_system.get_directory_client(f"{lakehouse_id}/Tables")
    return sorted(
        {
            path.name.split("/")[-1]
            for path in directory.get_paths(recursive=False)
            if path.is_directory
        }
    )


def read_table_schema(
    workspace_id: str, lakehouse_id: str, table_name: str, *, storage_options: dict[str, str]
) -> list[str] | None:
    from deltalake import DeltaTable
    from deltalake.exceptions import TableNotFoundError

    uri = f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/{lakehouse_id}/Tables/{table_name}"
    try:
        dt = DeltaTable(uri, storage_options=storage_options)
    except TableNotFoundError:
        # Table folder exists but has no committed Delta log segment yet.
        return None
    return [field.name for field in dt.schema().fields]


# Ontology entity/relationship tables share a fixed set of infrastructure
# columns (see src/fabric/dataset_mapper.py ontology_entity_table /
# ontology_relationship_table). Only these are exposed as Digital Twin
# Builder entity properties; the JSON payload columns are intentionally
# excluded here (DTB properties are scalar, not nested) and can be added as
# named entity type properties later if specific fields need direct mapping.
# `resource_id` must be included: it is the join key used by contextualization
# operations (AttributeName="ResourceId" below) as well as the mapping's
# EntityInstanceIdSchema. It has to appear here as a real property or the
# contextualization join will reference a property that doesn't exist.
_ENTITY_PROPERTY_COLUMNS = ("resource_id", "name", "resource_type", "location", "lifecycle_status")
_VALUE_TYPE_BY_COLUMN = {
    "resource_id": "String",
    "name": "String",
    "resource_type": "String",
    "location": "String",
    "lifecycle_status": "String",
}


def build_definition(
    *,
    workspace_id: str,
    lakehouse_id: str,
    tables: list[str],
    storage_options: dict[str, str],
) -> dict[str, Any]:
    entity_tables = sorted(t for t in tables if t.startswith("ontology_") and t.endswith("_entities") and t not in ("ontology_entities",))
    relationship_tables = sorted(t for t in tables if t.startswith("ontology_rel_"))

    entity_types: dict[str, dict[str, Any]] = {}
    entity_id_by_table: dict[str, str] = {}

    for table in entity_tables:
        # ontology_<slug>_entities -> PascalCase display name
        slug = table[len("ontology_") : -len("_entities")]
        display_name = "".join(part.capitalize() for part in slug.split("_"))
        type_id = _stable_id(f"entity:{display_name}")
        entity_id_by_table[table] = type_id

        columns = read_table_schema(workspace_id, lakehouse_id, table, storage_options=storage_options)
        if columns is None:
            continue
        properties = [
            {
                "Id": _stable_id(f"property:{display_name}:{column}"),
                "Name": "".join(part.capitalize() for part in column.split("_")),
                "ValueType": _VALUE_TYPE_BY_COLUMN.get(column, "String"),
            }
            for column in _ENTITY_PROPERTY_COLUMNS
            if column in columns
        ]
        entity_types[table] = {
            "Id": type_id,
            "Namespace": _NAMESPACE,
            "BaseEntityTypeId": _BASE_ENTITY_TYPE_ID,
            "Name": display_name,
            "Properties": properties,
            "TimeseriesProperties": [],
        }

    relationship_types: dict[str, dict[str, Any]] = {}
    mapping_operations: dict[str, dict[str, Any]] = {}
    contextualization_operations: dict[str, dict[str, Any]] = {}

    for table in relationship_tables:
        columns = read_table_schema(workspace_id, lakehouse_id, table, storage_options=storage_options)
        if columns is None or "subject_type" not in columns or "object_type" not in columns:
            continue
        # ontology_rel_<predicate>_<subject>_<object> is not reliably splittable
        # (predicate/type names can contain underscores), so the subject/object
        # types are resolved from data instead of the table name.
        subject_type, object_type, predicate = _sample_relationship_types(
            workspace_id, lakehouse_id, table, storage_options=storage_options
        )
        if subject_type is None or object_type is None:
            continue
        subject_table = f"ontology_{_slug(subject_type)}_entities"
        object_table = f"ontology_{_slug(object_type)}_entities"
        if subject_table not in entity_id_by_table or object_table not in entity_id_by_table:
            continue

        rel_name = predicate or table
        rel_id = _stable_id(f"relationship:{table}")
        relationship_types[table] = {
            "Id": rel_id,
            "Namespace": _NAMESPACE,
            "RelationshipCardinality": "ManyToOne",
            "Name": rel_name,
            "FirstEntityTypeId": entity_id_by_table[subject_table],
            "SecondEntityTypeId": entity_id_by_table[object_table],
        }

        contextualization_operations[table] = {
            "OperationId": _stable_guid(f"contextualization:{table}"),
            "DisplayName": f"{table}_contextualization",
            "OperationType": "Contextualization",
            "EntityTypeRelationshipId": rel_id,
            "JoinColumns": {
                "FirstColumn": {
                    "EntityId": entity_id_by_table[subject_table],
                    "AttributeName": "ResourceId",
                },
                "SecondColumn": {
                    "EntityId": entity_id_by_table[object_table],
                    "AttributeName": "ResourceId",
                },
            },
        }

    for table, entity_type in entity_types.items():
        op_id = _stable_guid(f"mapping:{table}")
        mapping_operations[table] = {
            "OperationId": op_id,
            "DisplayName": f"{table}_mapping",
            "OperationType": "Mapping",
            "EntityTypeId": entity_type["Id"],
            "MappingOperationProperties": {
                "MappingType": "NonTimeSeries",
                "MappedProperties": [
                    {"SourceColumn": column, "EntityTypePropertyName": prop["Name"]}
                    for column, prop in zip(
                        _ENTITY_PROPERTY_COLUMNS,
                        entity_type["Properties"],
                        strict=False,
                    )
                ],
                "ProcessingType": "Iterative",
                "EntityInstanceIdSchema": ["resource_id"],
                "TimeseriesEntityLinkProperties": None,
            },
            "SourceTableProperties": {
                "SourceType": "LakehouseTables",
                "WorkspaceId": workspace_id,
                "ItemId": lakehouse_id,
                "SourceTableName": table,
                "SourceSchema": None,
            },
            "Filters": None,
        }

    return {
        "lakehouse_id": lakehouse_id,
        "entity_types": entity_types,
        "relationship_types": relationship_types,
        "mapping_operations": mapping_operations,
        "contextualization_operations": contextualization_operations,
    }


def _sample_relationship_types(
    workspace_id: str, lakehouse_id: str, table: str, *, storage_options: dict[str, str]
) -> tuple[str | None, str | None, str | None]:
    from deltalake import DeltaTable
    from deltalake.exceptions import TableNotFoundError

    uri = f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/{lakehouse_id}/Tables/{table}"
    try:
        dt = DeltaTable(uri, storage_options=storage_options)
    except TableNotFoundError:
        # Table folder exists but has no committed Delta log segment yet
        # (e.g. created but never synced with data). Skip it.
        return None, None, None
    dataset = dt.to_pyarrow_dataset()
    if dataset.count_rows() == 0:
        return None, None, None
    batch = dataset.take([0])
    if batch.num_rows == 0:
        return None, None, None
    row = batch.to_pylist()[0]
    return row.get("subject_type"), row.get("object_type"), row.get("predicate")


def _stable_guid(name: str) -> str:
    import hashlib
    import uuid

    digest = hashlib.sha256(name.encode("utf-8")).digest()[:16]
    return str(uuid.UUID(bytes=digest))


def _slug(value: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", words.casefold()).strip("_")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--lakehouse-id", required=True)
    parser.add_argument("--tenant-id", default=os.environ.get("AZURE_TENANT_ID", ""))
    parser.add_argument("--client-id", default=os.environ.get("AZURE_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("AZURE_CLIENT_SECRET", ""))
    parser.add_argument("--output", default="digital_twin_builder_definition.json")
    args = parser.parse_args()

    if not (args.tenant_id and args.client_id and args.client_secret):
        print(
            "AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET must be set"
            " (any SPN with lakehouse read access works for this read-only step).",
            file=sys.stderr,
        )
        return 2

    storage_options = {
        "azure_storage_client_id": args.client_id,
        "azure_storage_tenant_id": args.tenant_id,
        "azure_storage_client_secret": args.client_secret,
        "use_fabric_endpoint": "true",
    }

    tables = list_lakehouse_tables(
        args.workspace_id, args.lakehouse_id, storage_options=storage_options
    )
    definition = build_definition(
        workspace_id=args.workspace_id,
        lakehouse_id=args.lakehouse_id,
        tables=tables,
        storage_options=storage_options,
    )

    Path(args.output).write_text(json.dumps(definition, indent=2, sort_keys=True))
    print(
        f"Wrote {args.output}: "
        f"{len(definition['entity_types'])} entity types, "
        f"{len(definition['relationship_types'])} relationship types"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
