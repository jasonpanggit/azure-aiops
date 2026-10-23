from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.scope import Scope
from intelligence.inventory import InventoryService, MachineObservation
from intelligence.inventory.normalization import canonicalize_os, normalize_os_inventory
from intelligence.inventory.pipeline import InventoryPipeline
from intelligence.inventory.software_normalization import normalize_configuration_data
from intelligence.inventory.sources.arg import (
    inventory_log_analytics_workspace_specs,
    inventory_os_specs,
)
from intelligence.lifecycle import EOLCatalog, LifecycleStatus
from onboarding.config import ConnectorConfig
from storage.datasets import DatasetStore

FIXTURE = Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"
SOFTWARE_FIXTURE = Path(__file__).parent / "fixtures" / "mock_configurationdata.json"


def _scope(**kwargs: list[str]) -> Scope:
    return Scope.from_mapping(kwargs)


@pytest.fixture
def service() -> InventoryService:
    return InventoryService.from_fixture(
        FIXTURE,
        catalog=EOLCatalog.default(),
    )


def test_fixture_groups_native_and_arc_after_scope_filter(service: InventoryService) -> None:
    result = service.collection(_scope(subscription=["sub-a"]))

    groups = {row["key"]: row for row in result["data"]["groups"]}
    windows = groups["Windows Server|2019"]
    assert windows["machine_count"] == 2
    assert list(windows["source_types"]) == ["arc", "azure_vm"]
    assert "sub-b" not in json.dumps(result)
    assert result["data"]["source_status"]["azure_vm"]["row_count"] == 2


def test_detail_is_exact_resource_join_and_preserves_environment(service: InventoryService) -> None:
    result = service.detail("Windows Server|2019", _scope(subscription=["sub-a"]))

    assert result is not None
    assert [row["resource_id"] for row in result["data"]["machines"]] == [
        "/subscriptions/sub-a/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/web-01",
        "/subscriptions/sub-a/resourceGroups/rg-prod/providers/Microsoft.HybridCompute/machines/shared-name",
    ]
    assert {row["source_type"] for row in result["data"]["machines"]} == {"azure_vm", "arc"}
    assert all(row["environment"] == "prod" for row in result["data"]["machines"])
    assert all(row["evidence"] for row in result["data"]["machines"])
    assert len({row["resource_id"] for row in result["data"]["machines"]}) == 2


def test_unknown_lifecycle_requires_review(service: InventoryService) -> None:
    result = service.detail("Windows Server|2099-preview", _scope(subscription=["sub-a"]))

    assert result is not None
    machine = result["data"]["machines"][0]
    assert machine["lifecycle_status"] == "Unknown"
    assert machine["support_end"] is None
    assert machine["review_required"] is True


def test_scope_is_applied_before_group_counts_and_pagination(service: InventoryService) -> None:
    result = service.collection(_scope(subscription=["sub-b"]), offset=0, limit=1)

    assert result["total"] == 1
    assert result["data"]["groups"][0]["machine_count"] == 1
    assert result["data"]["requested_scope"] == {"subscription": ["sub-b"]}


def test_source_failure_is_not_successful_empty(service: InventoryService) -> None:
    result = service.collection(Scope.unrestricted())

    assert result["data"]["source_status"]["arc"]["state"] == "partial"
    assert result["data"]["source_status"]["arc"]["error"]
    assert any("partial" in warning for warning in result["warnings"])


def test_empty_success_is_distinct_from_unavailable() -> None:
    empty = InventoryService(
        [
            {
                "resource_id": "vm-1",
                "machine_name": "vm-1",
                "source_type": "azure_vm",
                "os_name": "Windows Server",
                "os_version": "2019",
                "subscription_id": "sub-a",
                "resource_group": "rg",
                "environment": "prod",
                "observed_at": "2026-08-25T10:00:00Z",
                "source_status": "ready",
                "evidence": [],
            }
        ]
    )
    assert empty.source_status()["azure_vm"]["state"] == "ready"

    payload = {"source_status": {"azure_vm": {"state": "unavailable", "error": "timeout"}, "arc": "ready"}}
    unavailable = InventoryService.from_fixture(_write_payload(payload))
    assert unavailable.collection(Scope.unrestricted())["data"]["source_status"]["azure_vm"]["state"] == "unavailable"


def test_native_and_arc_queries_are_versioned_and_independent() -> None:
    specs = {spec.name: spec for spec in inventory_os_specs()}

    native = specs["inventory_native_vm_os"]
    arc = specs["inventory_arc_os"]
    assert native.version == "inventory-native-vm-os-v1"
    assert arc.version == "inventory-arc-os-v1"
    assert native.query != arc.query
    assert "imageVersion" in native.query
    assert "osVersion" in arc.query
    assert "| order by id asc" in native.query
    assert "| order by id asc" in arc.query


def test_log_analytics_discovery_selects_configuration_data_dcr_destinations() -> None:
    spec = inventory_log_analytics_workspace_specs()[0]
    query = spec.query

    assert spec.version == "inventory-law-configurationdata-workspaces-v2"
    assert "microsoft.insights/datacollectionrules" in query.casefold()
    assert "Microsoft-ConfigurationData" in query
    assert "properties.destinations.logAnalytics" in query
    assert "microsoft.operationalinsights/workspaces" in query.casefold()
    assert "join kind=inner" in query
    assert "workspaceId=tostring(properties.customerId)" in query


def test_generated_inventory_rows_preserve_source_identity_and_image_uncertainty(
    tmp_path: Path,
) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    observations, statuses = normalize_os_inventory(
        {
            "inventory_native_vm_os": fixture["inventory_native_vm_os"],
            "inventory_arc_os": fixture["inventory_arc_os"],
        },
        "2026-08-25T10:00:00+00:00",
        run_id="inventory-run",
        requested_scope={"subscription": ["sub-a", "sub-b"]},
    )

    native = next(row for row in observations if row["source_type"] == "azure_vm")
    arc = next(row for row in observations if row["source_type"] == "arc")
    assert native["os_name"] == "Windows Server"
    assert native["os_version"] == "2019"
    assert native["image_sku"] == "2019-Datacenter"
    assert native["image_version"] == "latest"
    assert native["environment"] == "prod"
    assert arc["os_name"] == "Ubuntu"
    assert arc["os_version"] == "22.04 LTS"
    assert arc["environment"] == "prod"
    assert native["resource_id"].startswith("/subscriptions/sub-a/")
    assert native["evidence"][0]["query_version"] == "inventory-native-vm-os-v1"

    store = DatasetStore(tmp_path)
    store.publish(
        {
            "inventory/os_observations": observations,
            "inventory/source_status": statuses,
        },
        {},
        {"runId": "inventory-run", "status": "completed"},
    )
    loaded = InventoryService.from_store(store)
    assert loaded is not None
    result = loaded.detail("Windows Server|2019", Scope.from_mapping({"subscription": ["sub-a"]}))
    assert result is not None
    # Both the native VM (image SKU "2019-Datacenter") and the Arc machine
    # resolve to the same lifecycle group, so both sources appear in the detail.
    assert sorted(row["source_type"] for row in result["data"]["machines"]) == [
        "arc",
        "azure_vm",
    ]


def test_inventory_latest_state_deduplicates_by_exact_source_and_resource() -> None:
    payload = {
        "query_version": "inventory-os-v1",
        "observations": [
            {
                "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                "name": "vm",
                "type": "microsoft.compute/virtualMachines",
                "subscriptionId": "sub-a",
                "resourceGroup": "rg",
                "tags": {"ENV": "stage", "EnvironmentName": "prod"},
                "osName": "Windows",
                "osVersion": "2022",
                "observed_at": "2026-08-25T09:00:00Z",
            },
            {
                "id": "/SUBSCRIPTIONS/SUB-A/RESOURCEGROUPS/rg/providers/Microsoft.Compute/virtualMachines/vm",
                "name": "vm",
                "type": "microsoft.compute/virtualMachines",
                "subscriptionId": "sub-a",
                "resourceGroup": "rg",
                "tags": {"ENV": "stage", "EnvironmentName": "prod"},
                "osName": "Windows",
                "osVersion": "2025",
                "observed_at": "2026-08-25T10:00:00Z",
            },
        ],
    }
    service = InventoryService(payload)
    assert len(service.snapshot.observations) == 1
    row = service.snapshot.observations[0]
    assert row.os_version == "2025"
    assert row.environment == "stage"


def test_failed_inventory_family_remains_visible_without_erasing_other_family() -> None:
    observations, status_rows = normalize_os_inventory(
        {
            "inventory_native_vm_os": [
                {
                    "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                    "name": "vm",
                    "type": "microsoft.compute/virtualMachines",
                    "subscriptionId": "sub-a",
                    "resourceGroup": "rg",
                    "tags": {},
                    "osType": "Windows",
                }
            ],
            "inventory_arc_os": [
                {
                    "status": "failed",
                    "provider_status": "failed",
                    "error": "Arc query timed out",
                }
            ],
        },
        "2026-08-25T10:00:00+00:00",
        run_id="inventory-failure-run",
        requested_scope=None,
    )
    statuses = {row["source_type"]: row for row in status_rows}
    assert len(observations) == 1
    assert statuses["azure_vm"]["state"] == "ready"
    assert statuses["arc"]["state"] == "degraded"
    assert statuses["arc"]["error"] == "Arc query timed out"


def test_configuration_data_normalizes_and_exactly_joins_machine_context() -> None:
    machine_service = InventoryService.from_fixture(FIXTURE)
    rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))
    software = normalize_configuration_data(rows, machine_service.snapshot.observations)

    assert len(software) == 2
    seven_zip = next(row for row in software if row.software_name == "7-Zip")
    assert seven_zip.software_version == "19.00"
    assert seven_zip.raw_software_name == "7-Zip v19.00"
    assert seven_zip.join_status == "linked"
    assert seven_zip.environment == "prod"
    assert seven_zip.resource_group == "rg-prod"
    orphan = next(row for row in software if row.software_name == "Contoso Agent")
    assert orphan.join_status == "unlinked"
    assert orphan.source_type is None
    assert orphan.environment == "Unknown"
    assert orphan.resource_group == "Unknown"


def test_software_collection_and_exact_version_detail_are_scope_first() -> None:
    machine_service = InventoryService.from_fixture(FIXTURE)
    rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["software_observations"] = [
        row.to_dict()
        for row in normalize_configuration_data(rows, machine_service.snapshot.observations)
    ]
    payload["software_source_status"] = {
        "logs": {
            "state": "ready",
            "observed_at": "2026-08-25T11:00:00Z",
            "query_version": "inventory-software-v1",
        }
    }
    service = InventoryService(payload)

    collection = service.software_collection(_scope(subscription=["sub-a"]))
    assert [group["key"] for group in collection["data"]["groups"]] == [
        "7-Zip|19.00",
        "Contoso Agent|4.2",
    ]
    detail = service.software_detail("7-Zip", "19.00", _scope(subscription=["sub-a"]))
    assert detail is not None
    assert detail["data"]["machines"][0]["resource_join_status"] == "linked"
    assert detail["data"]["machines"][0]["environment"] == "prod"
    assert service.software_detail("7-Zip", "18.00", _scope(subscription=["sub-a"])) is None


def test_software_latest_guard_handles_duplicates_case_changes_and_hostname_collisions() -> None:
    machine = {
        "id": "/subscriptions/sub-a/resourceGroups/rg-prod/providers/Microsoft.HybridCompute/machines/arc-01",
        "name": "shared-name",
        "type": "microsoft.hybridcompute/machines",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg-prod",
        "tags": {"Environment": "stage"},
        "osName": "Ubuntu",
        "osVersion": "22.04",
        "observed_at": "2026-08-25T08:00:00Z",
    }
    rows = [
        {
            "ConfigDataType": "Software",
            "SoftwareName": "7-Zip 19.00",
            "CurrentVersion": "19.00",
            "Computer": "shared-name",
            "SourceComputerId": "arc-agent",
            "_ResourceId": machine["id"],
            "_SubscriptionId": "sub-a",
            "TimeGenerated": "2026-08-25T09:00:00Z",
        },
        {
            "ConfigDataType": "Software",
            "SoftwareName": "7-Zip v19.00",
            "CurrentVersion": "v19.00",
            "Computer": "shared-name",
            "SourceComputerId": "arc-agent",
            "_ResourceId": machine["id"].upper(),
            "_SubscriptionId": "sub-a",
            "TimeGenerated": "2026-08-25T10:00:00Z",
        },
        {
            "ConfigDataType": "Software",
            "SoftwareName": "7-Zip",
            "CurrentVersion": "18.00",
            "Computer": "shared-name",
            "SourceComputerId": "arc-agent",
            "_ResourceId": machine["id"],
            "_SubscriptionId": "sub-a",
            "TimeGenerated": "2026-08-25T07:00:00Z",
        },
        {
            "ConfigDataType": "Software",
            "SoftwareName": "7-Zip",
            "CurrentVersion": "19.00",
            "Computer": "shared-name",
            "SourceComputerId": "arc-agent",
            "_ResourceId": machine["id"],
            "_SubscriptionId": "sub-a",
            "TimeGenerated": "2026-08-25T10:00:00Z",
        },
        {
            "ConfigDataType": "Software",
            "SoftwareName": "Agent",
            "CurrentVersion": "1",
            "Computer": "shared-name",
            "SourceComputerId": "unlinked-a",
            "_SubscriptionId": "sub-a",
            "TimeGenerated": "2026-08-25T10:00:00Z",
        },
        {
            "ConfigDataType": "Software",
            "SoftwareName": "Agent",
            "CurrentVersion": "1",
            "Computer": "shared-name",
            "SourceComputerId": "unlinked-b",
            "_SubscriptionId": "sub-a",
            "TimeGenerated": "2026-08-25T10:00:00Z",
        },
    ]
    normalized_machine = MachineObservation.from_mapping(machine)
    normalized = normalize_configuration_data(rows, [normalized_machine])

    seven_zip = [row for row in normalized if row.software_name == "7-Zip"]
    agents = [row for row in normalized if row.software_name == "Agent"]
    assert len(seven_zip) == 1
    assert seven_zip[0].software_version == "19.00"
    assert seven_zip[0].source_type == "arc"
    assert seven_zip[0].subscription_id == "sub-a"
    assert seven_zip[0].resource_group == "rg-prod"
    assert seven_zip[0].environment == "stage"
    assert len(agents) == 2
    assert all(row.join_status == "unlinked" for row in agents)
    assert all(row.source_type is None and row.environment == "Unknown" for row in agents)


def test_software_logs_source_failure_is_distinct_from_empty_success() -> None:
    failed = InventoryService(
        {
            "software_observations": [],
            "software_source_status": {
                "logs": {"state": "degraded", "error": "Logs timeout", "row_count": 0}
            },
        }
    )
    failed_result = failed.software_collection(Scope.unrestricted())
    assert failed_result["data"]["groups"] == []
    assert failed_result["data"]["source_status"]["logs"]["state"] == "degraded"
    assert failed_result["warnings"]

    empty = InventoryService(
        {
            "software_observations": [],
            "software_source_status": {"logs": {"state": "ready", "row_count": 0}},
        }
    )
    empty_result = empty.software_collection(Scope.unrestricted())
    assert empty_result["data"]["source_status"]["logs"]["state"] == "ready"
    assert empty_result["warnings"] == []


class _InventorySource:
    def __init__(self, rows: list[dict], law_workspaces: list[dict] | None = None) -> None:
        self.rows = rows
        self.law_workspaces = law_workspaces or []

    def list_subscriptions(self) -> list[dict]:
        return [{"subscriptionId": "sub-a"}]

    def fetch(self, specs, subscription_ids: list[str]) -> dict[str, list[dict]]:
        return {
            "inventory_native_vm_os": self.rows,
            "inventory_log_analytics_workspaces": self.law_workspaces,
        }


class _LogsSource:
    def __init__(self, results: dict[str, list[dict]] | None = None, failures: set[str] | None = None) -> None:
        self.results = results or {}
        self.failures = failures or set()
        self.calls: list[str] = []

    def query_configuration_data(self, workspace_id: str) -> list[dict]:
        self.calls.append(workspace_id)
        if workspace_id in self.failures:
            raise RuntimeError("workspace access denied")
        return self.results.get(workspace_id, [])


def _ingestion(
    tmp_path: Path,
    logs: _LogsSource,
    *,
    law_workspaces: list[dict] | None = None,
) -> InventoryPipeline:
    if law_workspaces is None:
        law_workspaces = [{"workspaceId": "workspace-1"}]
    inventory = json.loads(FIXTURE.read_text(encoding="utf-8"))["inventory_native_vm_os"]
    config = ConnectorConfig(
        output_dir=tmp_path,
        subscriptions=("sub-a",),
        connection_context={"connection_id": "connection-1"},
        cost_management_enabled=False,
    )
    return InventoryPipeline(
        config,
        source=_InventorySource(inventory[:1], law_workspaces),
        logs_client=logs,
        clock=lambda: datetime.fromisoformat("2026-08-25T12:00:00+00:00"),
    )


def test_discovered_workspace_publishes_software_in_the_active_generation(
    tmp_path: Path,
) -> None:
    logs_rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))[:2]
    logs = _LogsSource({"workspace-1": logs_rows})
    ingestion = _ingestion(tmp_path, logs)

    manifest = ingestion.refresh().manifest
    store = DatasetStore(tmp_path)
    software = store.read_dataset("inventory/software_observations")
    loaded = InventoryService.from_store(store)

    assert logs.calls == ["workspace-1"]
    assert manifest["datasets"]["inventory/software_observations"]["rowCount"] == 1
    assert len(software) == 1
    assert software[0]["environment"] == "prod"
    assert software[0]["resource_join_status"] == "linked"
    assert loaded is not None
    assert loaded.software_source_status()["logs"]["state"] == "ready"
    assert loaded.generation_id


def test_workspace_failures_retain_last_known_rows_and_mark_degraded(
    tmp_path: Path,
) -> None:
    logs_rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))[:1]
    first = _ingestion(tmp_path, _LogsSource({"workspace-1": logs_rows}))
    first.refresh()

    failed = _ingestion(
        tmp_path,
        _LogsSource(failures={"workspace-1"}),
    )
    failed.refresh()
    loaded = InventoryService.from_store(DatasetStore(tmp_path))

    assert loaded is not None
    assert len(loaded.snapshot.software_observations) == 1
    status = loaded.software_source_status()["logs"]
    assert status["state"] == "degraded"
    assert "access denied" in status["error"]


def test_successful_empty_workspace_replaces_previous_rows_as_ready_empty(
    tmp_path: Path,
) -> None:
    logs_rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))[:1]
    _ingestion(tmp_path, _LogsSource({"workspace-1": logs_rows})).refresh()
    _ingestion(tmp_path, _LogsSource({"workspace-1": []})).refresh()

    loaded = InventoryService.from_store(DatasetStore(tmp_path))
    assert loaded is not None
    assert loaded.snapshot.software_observations == ()
    assert loaded.software_source_status()["logs"]["state"] == "ready"
    assert loaded.software_source_status()["logs"]["row_count"] == 0


def test_multiple_discovered_workspaces_report_partial_without_browser_input(
    tmp_path: Path,
) -> None:
    logs = _LogsSource(
        {"workspace-1": json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))[:1]},
        failures={"workspace-2"},
    )
    ingestion = _ingestion(
        tmp_path,
        logs,
        law_workspaces=[{"workspaceId": "workspace-1"}, {"workspaceId": "workspace-2"}],
    )

    ingestion.refresh()
    loaded = InventoryService.from_store(DatasetStore(tmp_path))

    assert logs.calls == ["workspace-1", "workspace-2"]
    assert loaded is not None
    status = loaded.software_source_status()["logs"]
    assert status["state"] == "partial"
    assert status["workspace_count"] == 2


def test_no_discovered_workspaces_is_unavailable_and_never_queries_arbitrary_id(
    tmp_path: Path,
) -> None:
    logs = _LogsSource({"attacker-workspace": json.loads(SOFTWARE_FIXTURE.read_text())})
    _ingestion(tmp_path, logs, law_workspaces=[]).refresh()
    loaded = InventoryService.from_store(DatasetStore(tmp_path))

    assert logs.calls == []
    assert loaded is not None
    assert loaded.software_source_status()["logs"]["state"] == "unavailable"
    assert loaded.snapshot.software_observations == ()


def test_dynamic_law_discovery_queries_arg_discovered_workspace(tmp_path: Path) -> None:
    logs_rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))[:1]
    logs = _LogsSource({"discovered-ws": logs_rows})
    ingestion = _ingestion(
        tmp_path,
        logs,
        law_workspaces=[{"workspaceId": "discovered-ws", "name": "law-a"}],
    )

    ingestion.refresh()
    loaded = InventoryService.from_store(DatasetStore(tmp_path))

    assert logs.calls == ["discovered-ws"]
    assert loaded is not None
    status = loaded.software_source_status()["logs"]
    assert status["state"] == "ready"
    assert status["workspace_count"] == 1


def test_discovered_workspaces_are_deduplicated(tmp_path: Path) -> None:
    logs_rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))[:1]
    logs = _LogsSource({"workspace-1": logs_rows, "discovered-ws": []})
    ingestion = _ingestion(
        tmp_path,
        logs,
        law_workspaces=[
            {"workspaceId": "discovered-ws"},
            {"workspaceId": "workspace-1"},
            {"workspaceId": "workspace-1"},
        ],
    )

    ingestion.refresh()
    loaded = InventoryService.from_store(DatasetStore(tmp_path))

    assert logs.calls == ["discovered-ws", "workspace-1"]
    assert loaded is not None
    assert loaded.software_source_status()["logs"]["workspace_count"] == 2


def _write_payload(payload: dict) -> str:
    path = Path("/tmp/inventory-empty-success-test.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_narrative_aggregates_are_scoped_bounded_and_row_free() -> None:
    from api.scope import Scope

    service = InventoryService.from_fixture(FIXTURE)
    aggregates = service.narrative_aggregates(Scope.from_mapping({"subscription": ["sub-a"]}))

    assert aggregates["os_machine_count"] == 4
    assert all(group["machine_count"] <= 4 for group in aggregates["os_groups"])
    assert "machines" not in aggregates
    assert "software_rows" not in aggregates
    assert all("resource_id" not in group for group in aggregates["os_groups"])
    assert aggregates["source_status"]["arc"]["row_count"] == 2


def test_narrative_aggregate_limits_bound_group_payload() -> None:
    from intelligence.inventory.narrative import build_inventory_narrative

    rows = [
        {
            "id": f"/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-{index}",
            "name": f"vm-{index}",
            "type": "Microsoft.Compute/virtualMachines",
            "os_name": "OS",
            "os_version": str(index),
            "subscription_id": "sub-a",
            "resource_group": "rg",
            "environment": "prod",
            "observed_at": "2026-08-25T10:00:00Z",
        }
        for index in range(30)
    ]
    service = InventoryService(rows)
    captured: dict[str, object] = {}

    class FakeNarrator:
        def answer(self, *, question: str, context: dict[str, object]):
            from operations.foundry_agent import AgentAnswer

            captured["context"] = context
            return AgentAnswer(text="Bounded.", agent_name="test")

    result = build_inventory_narrative(service, Scope.from_mapping({"subscription": ["sub-a"]}), FakeNarrator())
    context = captured["context"]
    assert isinstance(context, dict)
    assert len(context["facts"]["fact_items"]) <= 5
    assert context["aggregate_limits"]["max_os_groups"] == 12
    facts = {item["label"]: item["value"] for item in result["data"]["fact_items"]}
    assert facts["OS groups"] == "30"
    assert facts["Machines"] == "30"
    assert facts["EOL risk"] == "0 expired, 0 expiring within 90 days, 0 supported, 30 needs review"
    assert "30 machines across 30 OS groups" in result["data"]["fact_summary"]
    assert result["data"]["status"] == "narrated"


def test_unsupported_inventory_citation_is_not_rendered() -> None:
    from intelligence.inventory.narrative import _citations

    citations = _citations(
        [
            {"source_engine": "untrusted", "source_table": "secret/raw_rows", "timestamp": "now"},
            {"source_engine": "InventoryService", "source_table": "Resources", "timestamp": "now"},
        ]
    )

    assert len(citations) == 1
    assert citations[0]["source_table"] == "Resources"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Native VM: the OS is only discoverable from the marketplace image SKU.
        (
            {
                "os_type": "Windows",
                "image_publisher": "MicrosoftWindowsServer",
                "image_offer": "WindowsServer",
                "image_sku": "2016-datacenter-gensecond",
            },
            ("Windows Server", "2016"),
        ),
        # Arc: the agent reports a build number instead of a release year.
        (
            {
                "os_name": "windows",
                "os_version": "10.0.14393.9140",
                "os_type": "Windows Server 2016 Datacenter",
            },
            ("Windows Server", "2016"),
        ),
        ({"os_name": "Ubuntu", "os_version": "22.04"}, ("Ubuntu", "22.04 LTS")),
        (
            {
                "os_type": "Linux",
                "image_publisher": "Canonical",
                "image_offer": "0001-com-ubuntu-server-jammy",
                "image_sku": "22_04-lts-gen2",
            },
            ("Ubuntu", "22.04 LTS"),
        ),
        (
            {"os_name": "RHEL", "os_version": "8.9"},
            ("Red Hat Enterprise Linux", "8"),
        ),
    ],
)
def test_canonicalize_os_emits_lifecycle_catalog_keys(
    raw: dict[str, str], expected: tuple[str, str]
) -> None:
    """Normalization must emit the ``(product, version)`` pair the catalog is keyed on.

    Regression guard: the catalog lookup is an exact match, so emitting
    ``("Windows", "Windows Server 2016")`` silently degraded every machine to
    "EOL date needs review" even though the release was well known.
    """
    assert canonicalize_os(**raw) == expected

    product, version = expected
    classification = EOLCatalog.default().classify_product(
        product, version, now=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert classification.support_end is not None
    assert classification.status is not LifecycleStatus.UNKNOWN


def test_both_sources_for_one_machine_agree_on_lifecycle_group() -> None:
    """A VM seen as both a native VM and an Arc machine must land in one group."""
    native = canonicalize_os(
        os_type="Windows",
        image_publisher="MicrosoftWindowsServer",
        image_offer="WindowsServer",
        image_sku="2016-datacenter-gensecond",
    )
    arc = canonicalize_os(
        os_name="windows",
        os_version="10.0.14393.9140",
        os_type="Windows Server 2016 Datacenter",
    )
    assert native == arc
