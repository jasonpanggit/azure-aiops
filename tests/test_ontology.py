from __future__ import annotations

import json

from ontology.entity_builder import EntityBuilder


def test_explicit_image_kind_cannot_be_reclassified_as_server() -> None:
    source = {
        "tenant_id": "tenant-1",
        "subscription_id": "subscription-1",
        "resource_id": "ontology://logical_image/example",
        "entity_type": "LogicalImage",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "name": "platform/api",
        "payload_json": json.dumps(
            {
                "target_kind": "container_image",
                "fabric_key": "logical-image:v1:platform/api",
            },
            sort_keys=True,
        ),
    }

    entity = next(
        row
        for row in EntityBuilder().build([source], "ontology-generation-1")
        if row["resource_id"] == source["resource_id"]
    )

    assert entity["entity_type"] == "LogicalImage"
    assert entity["entity_type"] not in {
        "Resource",
        "Server",
        "VirtualMachine",
        "ArcServer",
    }
