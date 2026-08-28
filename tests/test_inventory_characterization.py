from __future__ import annotations

import json
import re
from pathlib import Path

from inventory_harness import refresh_inventory

from api.evidence import envelope
from api.routers.inventory import _evidence
from api.scope import Scope
from intelligence.inventory.models import SOURCE_STATES, SOURCE_TYPES, group_key
from intelligence.inventory.service import InventoryService
from onboarding.ingestion_storage import DatasetStore

GOLDEN_ROOT = Path(__file__).parent / "fixtures" / "inventory_golden"
EXPECTED_INVENTORY_DATASETS = {
    "inventory/os_observations",
    "inventory/source_status",
    "inventory/software_observations",
    "inventory/software_source_status",
}
EXPECTED_MACHINE_KEYS = [
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
]
EXPECTED_OS_STATUS_KEYS = [
    "error",
    "observed_at",
    "query_version",
    "requested_scope",
    "row_count",
    "run_id",
    "source_type",
    "state",
]
EXPECTED_SOFTWARE_STATUS_KEYS = [
    "error",
    "observed_at",
    "query_version",
    "requested_scope",
    "row_count",
    "source_type",
    "state",
    "workspace_count",
]
EXPECTED_SOFTWARE_KEYS = [
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
]


def test_inventory_contract_end_to_end_from_refresh_to_api_envelope(tmp_path: Path) -> None:
    manifest = refresh_inventory(tmp_path)
    store = DatasetStore(tmp_path)
    service = InventoryService.from_store(store)

    assert service is not None
    assert {
        name for name in manifest["datasets"] if name.startswith("inventory/")
    } == EXPECTED_INVENTORY_DATASETS

    machines = store.read_dataset("inventory/os_observations")
    machine = next(row for row in machines if row["machine_name"] == "web-01")
    assert sorted(machine) == EXPECTED_MACHINE_KEYS
    assert machine == json.loads((GOLDEN_ROOT / "machine_web_01.json").read_text())

    software = store.read_dataset("inventory/software_observations")
    seven_zip = next(row for row in software if row["software_name"] == "7-Zip")
    assert sorted(seven_zip) == EXPECTED_SOFTWARE_KEYS
    assert seven_zip == json.loads((GOLDEN_ROOT / "software_7zip.json").read_text())

    assert sorted(store.read_dataset("inventory/source_status")[0]) == EXPECTED_OS_STATUS_KEYS
    assert sorted(store.read_dataset("inventory/software_source_status")[0]) == EXPECTED_SOFTWARE_STATUS_KEYS

    collection = service.collection(Scope.from_mapping({"subscription": ["sub-a"]}))
    # The native VM's image SKU ("2019-Datacenter") resolves to the same
    # lifecycle group as the Arc machine, so there is no phantom
    # "Windows|Unknown" group for a machine whose release is well known.
    assert collection["total"] == 2
    assert {group["key"] for group in collection["data"]["groups"]} == {
        "Ubuntu|22.04 LTS",
        "Windows Server|2019",
    }
    assert collection["data"]["source_status"]["azure_vm"]["row_count"] == 1

    body = envelope(
        collection["data"],
        evidence=_evidence(service),
        scope={"subscription": ["sub-a"]},
        knowledge_version=collection["data"]["query_version"],
        warnings=collection["warnings"],
        pagination={"offset": 0, "limit": 100, "total": collection["total"], "next_offset": None},
    )
    assert body["evidence"][0]["source_table"] == "inventory/os_observations"
    assert body["knowledge_version"] == "1.0.0"
    assert body["pagination"]["total"] == 2


def test_group_keys_status_evidence_and_pagination_are_contractual(
    tmp_path: Path,
) -> None:
    refresh_inventory(tmp_path)
    service = InventoryService.from_store(DatasetStore(tmp_path))

    assert service is not None
    assert group_key("Windows Server", "2019") == "Windows Server|2019"
    assert group_key("", "") == "Unknown OS|Unknown"
    assert re.fullmatch(r"^[^|/\\]{1,120}\|[^|/\\]{1,120}$", "Windows Server|2019")

    first_page = service.collection(Scope.unrestricted(), offset=0, limit=1)
    second_page = service.collection(Scope.unrestricted(), offset=1, limit=1)
    all_rows = service.collection(Scope.unrestricted(), offset=0, limit=100)
    walked = [*first_page["data"]["groups"], *second_page["data"]["groups"]]
    remaining = service.collection(Scope.unrestricted(), offset=2, limit=100)
    walked.extend(remaining["data"]["groups"])
    assert [row["key"] for row in walked] == [row["key"] for row in all_rows["data"]["groups"]]
    assert len({row["key"] for row in walked}) == len(walked)

    statuses = {
        **all_rows["data"]["source_status"],
        **service.software_collection(Scope.unrestricted())["data"]["source_status"],
    }
    assert {row["source_type"] for row in statuses.values()} <= SOURCE_TYPES
    assert {row["state"] for row in statuses.values()} <= SOURCE_STATES

    evidence_items = [*all_rows["evidence"], *service.software_collection(Scope.unrestricted())["evidence"]]
    assert evidence_items
    for item in evidence_items:
        assert item["source_engine"]
        assert item["source_table"]
        assert item["timestamp"]
        assert "query_version" not in item or item["query_version"]
