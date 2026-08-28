from __future__ import annotations

import json
from pathlib import Path

import pytest
from deltalake import DeltaTable

from intelligence.inventory.models import SOURCE_STATES

EXPECTED_CONTRACTS = {
    "inventory/os_observations": "inventory_os_observations",
    "inventory/source_status": "inventory_source_status",
    "inventory/software_observations": "inventory_software_observations",
    "inventory/software_source_status": "inventory_software_source_status",
}

MACHINE_KEYS = {
    "computer_name",
    "days_remaining",
    "environment",
    "evidence",
    "image_offer",
    "image_publisher",
    "image_sku",
    "image_version",
    "lifecycle_evidence",
    "lifecycle_status",
    "machine_name",
    "machine_status",
    "observed_at",
    "os_name",
    "os_type",
    "os_version",
    "query_version",
    "resource_group",
    "resource_id",
    "review_required",
    "source_status",
    "source_type",
    "subscription_id",
    "support_channel",
    "support_end",
}

OS_STATUS_KEYS = {
    "error",
    "observed_at",
    "query_version",
    "requested_scope",
    "row_count",
    "run_id",
    "source_type",
    "state",
}

SOFTWARE_STATUS_KEYS = {
    "error",
    "observed_at",
    "query_version",
    "requested_scope",
    "row_count",
    "source_type",
    "state",
    "workspace_count",
}

SOFTWARE_KEYS = {
    "canonical_identity",
    "canonical_name",
    "canonical_version",
    "computer",
    "environment",
    "evidence",
    "join_status",
    "machine_name",
    "mapping_confidence",
    "mapping_id",
    "mapping_method",
    "mapping_provenance",
    "mapping_revision",
    "mapping_source_timestamp",
    "mapping_status",
    "observed_at",
    "publisher",
    "raw_identity",
    "raw_software_name",
    "raw_software_version",
    "resource_group",
    "resource_id",
    "resource_join_status",
    "software_name",
    "software_type",
    "software_version",
    "source_computer_id",
    "source_type",
    "subscription_id",
    "time_generated",
}


def test_inventory_contract_maps_every_logical_dataset_to_fabric_table() -> None:
    from intelligence.inventory.fabric_contracts import INVENTORY_FABRIC_CONTRACTS

    assert EXPECTED_CONTRACTS.items() <= {
        logical_name: contract.table_name
        for logical_name, contract in INVENTORY_FABRIC_CONTRACTS.items()
    }.items()


@pytest.mark.parametrize(
    ("logical_name", "expected_fields"),
    [
        ("inventory/os_observations", MACHINE_KEYS),
        ("inventory/source_status", OS_STATUS_KEYS),
        ("inventory/software_observations", SOFTWARE_KEYS),
        ("inventory/software_source_status", SOFTWARE_STATUS_KEYS),
    ],
)
def test_inventory_contract_schemas_cover_characterized_row_keys(
    logical_name: str, expected_fields: set[str]
) -> None:
    from fabric.schema_registry import schema_for
    from intelligence.inventory.fabric_contracts import contract_for_logical_name

    contract = contract_for_logical_name(logical_name)

    assert expected_fields <= set(schema_for(contract.table_name).names)


def test_inventory_contract_quality_rejects_invalid_required_and_status_rows() -> None:
    from intelligence.inventory.fabric_contracts import (
        validate_inventory_dataset,
    )

    missing = validate_inventory_dataset(
        "inventory/os_observations",
        [
            {
                "machine_name": "vm-1",
                "source_type": "azure_vm",
                "source_status": "ready",
            }
        ],
    )
    invalid_state = validate_inventory_dataset(
        "inventory/source_status",
        [
            {
                "source_type": "azure_vm",
                "state": "invented",
                "observed_at": "2026-08-25T12:00:00+00:00",
                "query_version": "inventory-native-vm-os-v1",
                "row_count": 1,
                "error": "",
                "run_id": "run-1",
                "requested_scope": {"subscription": ["sub-a"]},
            }
        ],
    )

    assert any(failure["rule"] == "required_fields" for failure in missing.failures)
    assert any(failure["rule"] == "source_state" for failure in invalid_state.failures)


def test_inventory_contract_rejects_duplicate_identity_and_assessment_fields() -> None:
    from intelligence.inventory.fabric_contracts import (
        validate_inventory_dataset,
    )

    base = {
        "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        "machine_name": "vm-1",
        "source_type": "azure_vm",
        "os_name": "Windows",
        "os_version": "Unknown",
        "subscription_id": "sub-a",
        "resource_group": "rg",
        "environment": "prod",
        "observed_at": "2026-08-25T12:00:00+00:00",
        "evidence": [],
        "source_status": "ready",
        "lifecycle_status": "Unknown",
        "support_end": None,
        "days_remaining": None,
        "review_required": False,
        "query_version": "inventory-native-vm-os-v1",
        "os_type": "Windows",
        "image_publisher": "",
        "image_offer": "",
        "image_sku": "",
        "image_version": "",
        "computer_name": "",
        "machine_status": "",
        "support_channel": "",
        "lifecycle_evidence": [],
    }

    duplicate = validate_inventory_dataset("inventory/os_observations", [base, dict(base)])
    assessment = validate_inventory_dataset(
        "inventory/os_observations",
        [{**base, "vulnerability_count": 3}],
    )

    assert any(failure["rule"] == "duplicates" for failure in duplicate.failures)
    assert any(failure["rule"] == "assessment_fields" for failure in assessment.failures)
    assert SOURCE_STATES == {"ready", "partial", "stale", "degraded", "unavailable"}


def test_standalone_inventory_refresh_publishes_os_rows_without_hermes_sync(tmp_path) -> None:
    from inventory_harness import refresh_inventory

    from intelligence.inventory.fabric_contracts import fabric_table_for_logical_name
    from intelligence.inventory.service import InventoryService
    from onboarding.ingestion_storage import DatasetStore

    manifest = refresh_inventory(tmp_path)
    store = DatasetStore(tmp_path)
    service = InventoryService.from_store(store)

    assert service is not None
    assert store.read_dataset("inventory/os_observations")
    assert manifest["fabricTables"]["inventory/os_observations"] == fabric_table_for_logical_name(
        "inventory/os_observations"
    )


def test_inventory_refresh_writes_arg_and_law_rows_to_onelake_delta_tables(tmp_path) -> None:
    from inventory_harness import _InventorySource, _LogsSource

    from intelligence.inventory.fabric_publication import InventoryFabricPublisher
    from intelligence.inventory.onelake_publication import InventoryOneLakePublisher
    from intelligence.inventory.pipeline import InventoryPipeline
    from onboarding.config import ConnectorConfig
    from storage.datasets import DatasetStore
    from storage.onelake_writer import OneLakeWriter

    fixture = json.loads((Path(__file__).parent / "fixtures" / "mock_inventory_arg.json").read_text())
    fixture.setdefault("inventory_log_analytics_workspaces", [{"workspaceId": "workspace-1"}])
    software_rows = json.loads(
        (Path(__file__).parent / "fixtures" / "mock_configurationdata.json").read_text()
    )
    lakehouse_root = tmp_path / "lakehouse"
    config = ConnectorConfig(
        output_dir=tmp_path / "compat",
        subscriptions=("sub-a", "sub-b"),
        connection_context={"connection_id": "connection-1"},
        cost_management_enabled=False,
    )
    publisher = InventoryFabricPublisher(
        DatasetStore(config.output_dir),
        onelake=InventoryOneLakePublisher(
            OneLakeWriter("workspace", "lakehouse", local_root=lakehouse_root)
        ),
    )

    result = InventoryPipeline(
        config,
        source=_InventorySource(fixture),
        logs_client=_LogsSource(software_rows),
        publisher=publisher,
    ).refresh()

    assert set(result.manifest["fabricTableWrites"]) >= {
        "inventory_os_observations",
        "inventory_software_observations",
        "inventory_resource_observations",
        "inventory_software_source_status",
    }
    assert (
        DeltaTable(str(lakehouse_root / "Tables" / "inventory_os_observations"))
        .to_pyarrow_table()
        .num_rows
        > 0
    )
    assert (
        DeltaTable(str(lakehouse_root / "Tables" / "inventory_software_observations"))
        .to_pyarrow_table()
        .num_rows
        > 0
    )
