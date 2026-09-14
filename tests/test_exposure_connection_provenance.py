from __future__ import annotations

from fabric.dataset_mapper import _patch_finding_row, temporal_inputs_from_legacy
from fabric.schema_registry import schema_for


def test_patch_finding_preserves_connection_for_temporal_authorization() -> None:
    finding = _patch_finding_row(
        {
            "id": (
                "/subscriptions/sub-a/resourceGroups/rg-a/providers/"
                "Microsoft.HybridCompute/machines/vm-a/softwarePatches/KB5000001"
            ),
            "tenantId": "tenant-a",
            "subscriptionId": "sub-a",
            "connection_id": "demo",
            "targetResourceId": (
                "/subscriptions/sub-a/resourceGroups/rg-a/providers/"
                "Microsoft.HybridCompute/machines/vm-a"
            ),
            "kbId": "5000001",
            "updateName": "Security update",
            "classifications": ["Security"],
            "lastModifiedDateTime": "2026-09-13T00:00:00Z",
            "lastObservedTimestamp": "2026-09-13T00:00:00Z",
        },
        "run-a",
        status="missing",
    )

    assert finding["connection_id"] == "demo"
    observations = temporal_inputs_from_legacy(
        {"silver_patch_findings": [finding]}
    )
    assert len(observations) == 1
    assert observations[0]["connection_id"] == "demo"
    assert observations[0]["connection_id"] != "legacy:sub-a"


def test_patch_finding_schemas_persist_connection_provenance() -> None:
    for table_name in (
        "silver_patch_findings",
        "silver_patch_snapshot_findings",
    ):
        field = schema_for(table_name).field("connection_id")
        assert not field.nullable
