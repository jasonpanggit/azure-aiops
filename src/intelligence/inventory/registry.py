from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .fabric_contracts import contract_for_logical_name


@dataclass(frozen=True)
class InventoryFamily:
    family: str
    logical_dataset: str
    fabric_table: str
    status_dataset: str
    source_types: tuple[str, ...]
    observation_type: str
    scope_fields: tuple[str, ...]
    raw_payload_internal_only: bool = True
    group_key: Callable[..., str] | None = None


class InventoryFamilyRegistry:
    def __init__(self, families: list[InventoryFamily] | tuple[InventoryFamily, ...]) -> None:
        logical: set[str] = set()
        tables: set[str] = set()
        by_name: dict[str, InventoryFamily] = {}
        for family in families:
            if family.logical_dataset in logical:
                raise ValueError(f"Duplicate inventory logical dataset: {family.logical_dataset}")
            if family.fabric_table in tables:
                raise ValueError(f"Duplicate inventory Fabric table: {family.fabric_table}")
            logical.add(family.logical_dataset)
            tables.add(family.fabric_table)
            by_name[family.family] = family
        self._families = by_name

    @property
    def families(self) -> tuple[InventoryFamily, ...]:
        return tuple(self._families.values())

    @property
    def source_types(self) -> frozenset[str]:
        return frozenset(
            source_type
            for family in self._families.values()
            for source_type in family.source_types
        )

    def family(self, name: str) -> InventoryFamily:
        return self._families[name]


def default_inventory_registry() -> InventoryFamilyRegistry:
    from .models import group_key

    os_contract = contract_for_logical_name("inventory/os_observations")
    software_contract = contract_for_logical_name("inventory/software_observations")
    resource_contract = contract_for_logical_name("inventory/resource_observations")
    return InventoryFamilyRegistry(
        [
            InventoryFamily(
                family="os",
                logical_dataset=os_contract.logical_name,
                fabric_table=os_contract.table_name,
                status_dataset="inventory/source_status",
                source_types=("azure_vm", "arc"),
                observation_type="machine",
                scope_fields=("subscription_id", "resource_group", "environment"),
                raw_payload_internal_only=True,
                group_key=group_key,
            ),
            InventoryFamily(
                family="software",
                logical_dataset=software_contract.logical_name,
                fabric_table=software_contract.table_name,
                status_dataset="inventory/software_source_status",
                source_types=("logs",),
                observation_type="software",
                scope_fields=("subscription_id", "resource_group", "environment"),
                raw_payload_internal_only=True,
            ),
            InventoryFamily(
                family="paas",
                logical_dataset=resource_contract.logical_name,
                fabric_table=resource_contract.table_name,
                status_dataset="inventory/source_status",
                source_types=("arg",),
                observation_type="resource",
                scope_fields=("subscription_id", "resource_group", "location"),
                raw_payload_internal_only=True,
            ),
        ]
    )


def registered_source_types() -> frozenset[str]:
    return default_inventory_registry().source_types


__all__ = [
    "InventoryFamily",
    "InventoryFamilyRegistry",
    "default_inventory_registry",
    "registered_source_types",
]
