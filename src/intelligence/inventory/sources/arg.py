from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InventoryQuerySpec:
    name: str
    table: str
    query: str
    incremental: bool = False
    scope: str = "subscriptions"
    version: str = "1.0.0"


def inventory_os_specs() -> list[InventoryQuerySpec]:
    """Independent, fixed ARG queries for machine OS inventory.

    Native VMs and Arc machines intentionally have separate specs.  Apart from
    making source failures attributable, this prevents native image SKU values
    from being mistaken for installed OS releases.
    """
    return [
        InventoryQuerySpec(
            "inventory_native_vm_os",
            "Resources",
            (
                "Resources "
                "| where type =~ 'microsoft.compute/virtualmachines' "
                "| project id, name, type, subscriptionId, resourceGroup, location, tags, "
                "osType=tostring(properties.storageProfile.osDisk.osType), "
                "imagePublisher=tostring(properties.storageProfile.imageReference.publisher), "
                "imageOffer=tostring(properties.storageProfile.imageReference.offer), "
                "imageSku=tostring(properties.storageProfile.imageReference.sku), "
                "imageVersion=tostring(properties.storageProfile.imageReference.version) "
                "| order by id asc"
            ),
            version="inventory-native-vm-os-v1",
        ),
        InventoryQuerySpec(
            "inventory_arc_os",
            "Resources",
            (
                "Resources "
                "| where type =~ 'microsoft.hybridcompute/machines' "
                "| project id, name, type, subscriptionId, resourceGroup, location, tags, "
                "computerName=tostring(properties.osProfile.computerName), "
                "osName=tostring(properties.osName), "
                "osVersion=tostring(properties.osVersion), "
                "osSku=tostring(properties.osSku), "
                "status=tostring(properties.status) "
                "| order by id asc"
            ),
            version="inventory-arc-os-v1",
        ),
    ]


__all__ = ["InventoryQuerySpec", "inventory_os_specs"]

