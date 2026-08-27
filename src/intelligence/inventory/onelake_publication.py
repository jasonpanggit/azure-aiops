from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa

from storage.delta_writer import DeltaWriteMode, DeltaWriter, DeltaWriteResult
from storage.onelake_writer import OneLakeWriter

from .fabric_contracts import InventoryFabricContract


@dataclass(frozen=True)
class InventoryTableWrite:
    table_name: str
    table_uri: str
    result: DeltaWriteResult


@dataclass
class InventoryOneLakePublisher:
    """Write inventory-owned ARG/LAW outputs to governed OneLake Delta tables."""

    onelake: OneLakeWriter
    delta_writer: DeltaWriter = field(default_factory=DeltaWriter)

    def publish_table(
        self,
        contract: InventoryFabricContract,
        rows: Sequence[Mapping[str, Any]],
    ) -> InventoryTableWrite:
        table_uri = self.onelake.table_uri("inventory", contract.table_name.removeprefix("inventory_"))
        result = self.delta_writer.write(
            table_uri,
            [_fabric_row(contract, row) for row in rows],
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=contract.identity_fields,
            schema=contract.schema,
            required_columns=contract.required_fields,
        )
        return InventoryTableWrite(
            table_name=contract.table_name,
            table_uri=table_uri,
            result=result,
        )


def _fabric_row(contract: InventoryFabricContract, row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    string_fields = {
        field.name for field in contract.schema if pa.types.is_string(field.type)
    }
    for field_name in string_fields:
        value = normalized.get(field_name)
        if value is not None and not isinstance(value, str):
            normalized[field_name] = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return normalized


__all__ = ["InventoryOneLakePublisher", "InventoryTableWrite"]
