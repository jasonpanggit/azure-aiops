"""Fabric/OneLake table contracts for inventory-owned publication.

The inventory domain keeps the existing slash-delimited logical dataset names
as its compatibility API while publishing to Fabric-safe table names.  These
contracts are intentionally inventory-owned: generic Fabric modules may look up
schemas, but they do not encode inventory lifecycle knowledge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from .models import SOURCE_STATES


@dataclass(frozen=True)
class InventoryFabricContract:
    logical_name: str
    table_name: str
    schema: pa.Schema
    required_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]
    source_status_table: str = ""


@dataclass(frozen=True)
class InventoryQualityReport:
    table_name: str
    rows_checked: int
    rule_counts: dict[str, int] = field(default_factory=dict)
    failures: tuple[dict[str, Any], ...] = ()

    @property
    def failed_records(self) -> int:
        return len({int(failure["row_index"]) for failure in self.failures})

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "rows_checked": self.rows_checked,
            "failed_records": self.failed_records,
            "passed": self.passed,
            "rule_counts": dict(self.rule_counts),
            "failures": list(self.failures),
        }


_OS_SCHEMA = pa.schema(
    [
        pa.field("resource_id", pa.string(), nullable=False),
        pa.field("machine_name", pa.string(), nullable=False),
        pa.field("source_type", pa.string(), nullable=False),
        pa.field("os_name", pa.string(), nullable=False),
        pa.field("os_version", pa.string(), nullable=False),
        pa.field("subscription_id", pa.string(), nullable=False),
        pa.field("resource_group", pa.string(), nullable=False),
        pa.field("environment", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("evidence", pa.list_(pa.struct([
            pa.field("source_engine", pa.string()),
            pa.field("source_table", pa.string()),
            pa.field("observed_at", pa.string()),
            pa.field("source_id", pa.string()),
            pa.field("query_version", pa.string()),
        ]))),
        pa.field("source_status", pa.string(), nullable=False),
        pa.field("lifecycle_status", pa.string(), nullable=False),
        pa.field("support_end", pa.string()),
        pa.field("days_remaining", pa.int64()),
        pa.field("review_required", pa.bool_(), nullable=False),
        pa.field("query_version", pa.string(), nullable=False),
        pa.field("os_type", pa.string(), nullable=False),
        pa.field("image_publisher", pa.string(), nullable=False),
        pa.field("image_offer", pa.string(), nullable=False),
        pa.field("image_sku", pa.string(), nullable=False),
        pa.field("image_version", pa.string(), nullable=False),
        pa.field("computer_name", pa.string(), nullable=False),
        pa.field("machine_status", pa.string(), nullable=False),
        pa.field("support_channel", pa.string(), nullable=False),
        pa.field("lifecycle_evidence", pa.list_(pa.string())),
    ]
)

_SOURCE_STATUS_SCHEMA = pa.schema(
    [
        pa.field("source_type", pa.string(), nullable=False),
        pa.field("state", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("query_version", pa.string(), nullable=False),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("error", pa.string(), nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("requested_scope", pa.string(), nullable=False),
    ]
)

_SOFTWARE_SCHEMA = pa.schema(
    [
        pa.field("software_name", pa.string(), nullable=False),
        pa.field("software_version", pa.string(), nullable=False),
        pa.field("canonical_name", pa.string(), nullable=False),
        pa.field("canonical_version", pa.string(), nullable=False),
        pa.field("canonical_identity", pa.string(), nullable=False),
        pa.field("raw_software_name", pa.string(), nullable=False),
        pa.field("raw_software_version", pa.string(), nullable=False),
        pa.field("raw_identity", pa.struct([
            pa.field("name", pa.string()),
            pa.field("version", pa.string()),
        ])),
        pa.field("resource_id", pa.string(), nullable=False),
        pa.field("machine_name", pa.string(), nullable=False),
        pa.field("computer", pa.string(), nullable=False),
        pa.field("source_computer_id", pa.string(), nullable=False),
        pa.field("source_type", pa.string()),
        pa.field("join_status", pa.string(), nullable=False),
        pa.field("resource_join_status", pa.string(), nullable=False),
        pa.field("subscription_id", pa.string(), nullable=False),
        pa.field("resource_group", pa.string(), nullable=False),
        pa.field("environment", pa.string(), nullable=False),
        pa.field("publisher", pa.string(), nullable=False),
        pa.field("software_type", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("time_generated", pa.string(), nullable=False),
        pa.field("evidence", pa.list_(pa.struct([
            pa.field("source_engine", pa.string()),
            pa.field("source_table", pa.string()),
            pa.field("observed_at", pa.string()),
            pa.field("source_id", pa.string()),
            pa.field("query_version", pa.string()),
        ]))),
        pa.field("mapping_id", pa.string(), nullable=False),
        pa.field("mapping_status", pa.string(), nullable=False),
        pa.field("mapping_revision", pa.int64(), nullable=False),
        pa.field("mapping_method", pa.string(), nullable=False),
        pa.field("mapping_confidence", pa.float64(), nullable=False),
        pa.field("mapping_provenance", pa.string()),
        pa.field("mapping_source_timestamp", pa.string(), nullable=False),
    ]
)

_SOFTWARE_STATUS_SCHEMA = pa.schema(
    [
        pa.field("source_type", pa.string(), nullable=False),
        pa.field("state", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("query_version", pa.string(), nullable=False),
        pa.field("row_count", pa.int64(), nullable=False),
        pa.field("error", pa.string(), nullable=False),
        pa.field("workspace_count", pa.int64(), nullable=False),
        pa.field("requested_scope", pa.string(), nullable=False),
    ]
)

_RESOURCE_OBSERVATION_SCHEMA = pa.schema(
    [
        pa.field("tenant_id", pa.string(), nullable=False),
        pa.field("subscription_id", pa.string(), nullable=False),
        pa.field("resource_id", pa.string(), nullable=False),
        pa.field("timestamp", pa.string(), nullable=False),
        pa.field("change_version", pa.string(), nullable=False),
        pa.field("ingestion_run_id", pa.string(), nullable=False),
        pa.field("resource_name", pa.string(), nullable=False),
        pa.field("resource_type", pa.string(), nullable=False),
        pa.field("resource_group", pa.string(), nullable=False),
        pa.field("location", pa.string(), nullable=False),
        pa.field("family", pa.string(), nullable=False),
        pa.field("sku", pa.string(), nullable=False),
        pa.field("tier", pa.string(), nullable=False),
        pa.field("runtime", pa.string(), nullable=False),
        pa.field("provisioning_state", pa.string(), nullable=False),
        pa.field("os_name", pa.string(), nullable=False),
        pa.field("os_version", pa.string(), nullable=False),
        pa.field("source_type", pa.string(), nullable=False),
        pa.field("source_table", pa.string(), nullable=False),
        pa.field("observed_at", pa.string(), nullable=False),
        pa.field("query_version", pa.string(), nullable=False),
        pa.field("provider_payload_json", pa.string(), nullable=False),
        pa.field("tags_json", pa.string(), nullable=False),
        pa.field("provenance_json", pa.string(), nullable=False),
    ]
)

INVENTORY_FABRIC_CONTRACTS: dict[str, InventoryFabricContract] = {
    "inventory/os_observations": InventoryFabricContract(
        logical_name="inventory/os_observations",
        table_name="inventory_os_observations",
        schema=_OS_SCHEMA,
        required_fields=(
            "resource_id",
            "machine_name",
            "source_type",
            "subscription_id",
            "resource_group",
            "observed_at",
            "evidence",
            "source_status",
            "query_version",
        ),
        identity_fields=("source_type", "resource_id"),
        source_status_table="inventory_source_status",
    ),
    "inventory/source_status": InventoryFabricContract(
        logical_name="inventory/source_status",
        table_name="inventory_source_status",
        schema=_SOURCE_STATUS_SCHEMA,
        required_fields=(
            "source_type",
            "state",
            "observed_at",
            "query_version",
            "row_count",
            "run_id",
            "requested_scope",
        ),
        identity_fields=("source_type",),
    ),
    "inventory/software_observations": InventoryFabricContract(
        logical_name="inventory/software_observations",
        table_name="inventory_software_observations",
        schema=_SOFTWARE_SCHEMA,
        required_fields=(
            "software_name",
            "software_version",
            "canonical_identity",
            "resource_id",
            "machine_name",
            "source_computer_id",
            "join_status",
            "subscription_id",
            "resource_group",
            "environment",
            "observed_at",
            "evidence",
        ),
        identity_fields=("resource_id", "source_computer_id", "canonical_identity"),
        source_status_table="inventory_software_source_status",
    ),
    "inventory/software_source_status": InventoryFabricContract(
        logical_name="inventory/software_source_status",
        table_name="inventory_software_source_status",
        schema=_SOFTWARE_STATUS_SCHEMA,
        required_fields=(
            "source_type",
            "state",
            "observed_at",
            "query_version",
            "row_count",
            "workspace_count",
            "requested_scope",
        ),
        identity_fields=("source_type",),
    ),
    "inventory/resource_observations": InventoryFabricContract(
        logical_name="inventory/resource_observations",
        table_name="inventory_resource_observations",
        schema=_RESOURCE_OBSERVATION_SCHEMA,
        required_fields=(
            "tenant_id",
            "subscription_id",
            "resource_id",
            "timestamp",
            "change_version",
            "ingestion_run_id",
            "resource_type",
            "family",
            "source_type",
            "source_table",
            "observed_at",
            "query_version",
            "provider_payload_json",
            "provenance_json",
        ),
        identity_fields=("family", "resource_id"),
    ),
}

INVENTORY_FABRIC_SCHEMAS_BY_TABLE = {
    contract.table_name: contract.schema
    for contract in INVENTORY_FABRIC_CONTRACTS.values()
}


def contract_for_logical_name(logical_name: str) -> InventoryFabricContract:
    try:
        return INVENTORY_FABRIC_CONTRACTS[logical_name]
    except KeyError as exc:
        raise KeyError(f"No inventory Fabric contract for dataset: {logical_name}") from exc


def contract_for_table_name(table_name: str) -> InventoryFabricContract:
    for contract in INVENTORY_FABRIC_CONTRACTS.values():
        if contract.table_name == table_name:
            return contract
    raise KeyError(f"No inventory Fabric contract for table: {table_name}")


def logical_name_for_table(table_name: str) -> str:
    return contract_for_table_name(table_name).logical_name


def fabric_table_for_logical_name(logical_name: str) -> str:
    return contract_for_logical_name(logical_name).table_name


def validate_inventory_dataset(
    logical_name: str,
    rows: Sequence[Mapping[str, Any]],
) -> InventoryQualityReport:
    contract = contract_for_logical_name(logical_name)
    failures: list[dict[str, Any]] = []
    counts = {
        "required_fields": 0,
        "duplicates": 0,
        "source_state": 0,
        "assessment_fields": 0,
    }
    seen: set[tuple[str, ...]] = set()
    for index, row in enumerate(rows):
        missing = [field for field in contract.required_fields if _missing(row.get(field))]
        if missing:
            counts["required_fields"] += 1
            failures.append(_failure(index, "required_fields", ",".join(missing)))

        identity = tuple(str(row.get(field) or "").casefold() for field in contract.identity_fields)
        if any(identity):
            if identity in seen:
                counts["duplicates"] += 1
                failures.append(_failure(index, "duplicates", "|".join(identity)))
            seen.add(identity)

        state = row.get("state") if logical_name.endswith("source_status") else row.get("source_status")
        if state is not None and str(state).casefold() not in SOURCE_STATES:
            counts["source_state"] += 1
            failures.append(_failure(index, "source_state", str(state)))

        assessment_fields = sorted(set(row) - set(contract.schema.names))
        if assessment_fields:
            counts["assessment_fields"] += 1
            failures.append(_failure(index, "assessment_fields", ",".join(assessment_fields)))

    return InventoryQualityReport(
        table_name=contract.table_name,
        rows_checked=len(rows),
        rule_counts=counts,
        failures=tuple(failures),
    )


def _missing(value: Any) -> bool:
    return value is None or value == ""


def _failure(index: int, rule: str, detail: str) -> dict[str, Any]:
    return {"row_index": index, "rule": rule, "detail": detail}


__all__ = [
    "INVENTORY_FABRIC_CONTRACTS",
    "INVENTORY_FABRIC_SCHEMAS_BY_TABLE",
    "InventoryFabricContract",
    "InventoryQualityReport",
    "contract_for_logical_name",
    "contract_for_table_name",
    "fabric_table_for_logical_name",
    "logical_name_for_table",
    "validate_inventory_dataset",
]
