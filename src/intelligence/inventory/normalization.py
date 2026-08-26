from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .models import MachineObservation, ResourceObservation


def normalize_os_inventory(
    payload: Mapping[str, list[dict]],
    observed: str,
    *,
    run_id: str,
    requested_scope: dict[str, list[str]] | None,
) -> tuple[list[dict], list[dict]]:
    """Normalize native VM and Arc OS query families into compatibility rows."""

    families = (
        ("inventory_native_vm_os", "azure_vm", "inventory-native-vm-os-v1"),
        ("inventory_arc_os", "arc", "inventory-arc-os-v1"),
    )
    observations: list[dict] = []
    statuses: list[dict] = []
    for family, source_type, default_query_version in families:
        rows = [row for row in payload.get(family, []) if isinstance(row, Mapping)]
        failed = next(
            (
                row
                for row in rows
                if str(row.get("status") or row.get("provider_status") or "").casefold()
                in {"failed", "unavailable"}
            ),
            None,
        )
        query_version = str((rows[0] if rows else {}).get("query_version") or default_query_version)
        family_observations: list[MachineObservation] = []
        if failed is None:
            for row in rows:
                source_id = str(row.get("id") or row.get("resource_id") or "").strip()
                if not source_id:
                    continue
                normalized = _normalize_machine_row(
                    dict(row),
                    source_type=source_type,
                    observed=observed,
                    query_version=query_version,
                    source_id=source_id,
                )
                family_observations.append(
                    MachineObservation.from_mapping(
                        normalized,
                        default_status="ready",
                        query_version=query_version,
                    )
                )
        current = _latest_inventory_observations(family_observations)
        observations.extend(item.to_dict() for item in current)
        status = "degraded" if failed else "ready"
        timestamps = [item.observed_at for item in current]
        statuses.append(
            {
                "source_type": source_type,
                "state": status,
                "observed_at": max(timestamps, default=observed),
                "query_version": query_version,
                "row_count": len(current),
                "error": str((failed or {}).get("error") or ""),
                "run_id": run_id,
                "requested_scope": requested_scope or {},
            }
        )
    return observations, statuses


def _normalize_machine_row(
    row: dict[str, Any],
    *,
    source_type: str,
    observed: str,
    query_version: str,
    source_id: str,
) -> dict[str, Any]:
    if source_type == "azure_vm":
        properties = row.get("properties") if isinstance(row.get("properties"), Mapping) else {}
        os_type = str(row.get("osType") or row.get("os_type") or properties.get("osType") or "")
        row = {
            **row,
            "os_name": os_type or "Unknown OS",
            "os_version": "Unknown",
            "os_type": os_type,
            "image_publisher": row.get("imagePublisher") or "",
            "image_offer": row.get("imageOffer") or "",
            "image_sku": row.get("imageSku") or "",
            "image_version": row.get("imageVersion") or "",
        }
    else:
        properties = row.get("properties") if isinstance(row.get("properties"), Mapping) else {}
        row = {
            **row,
            "os_name": row.get("osName") or properties.get("osName") or "",
            "os_version": row.get("osVersion") or properties.get("osVersion") or "Unknown",
            "computer_name": row.get("computerName") or properties.get("computerName") or "",
            "machine_status": row.get("status") or properties.get("status") or "",
            "os_type": row.get("osSku") or properties.get("osSku") or "",
        }
    row["source_type"] = source_type
    row["observed_at"] = str(row.get("observed_at") or row.get("observedAt") or observed)
    row["query_version"] = query_version
    row["source_status"] = "ready"
    row["evidence"] = [
        {
            "source_engine": "Azure Resource Graph",
            "source_table": "Resources",
            "observed_at": row["observed_at"],
            "source_id": source_id,
            "query_version": query_version,
        }
    ]
    return row


def _latest_inventory_observations(rows: list[MachineObservation]) -> list[MachineObservation]:
    selected: dict[tuple[str, str], MachineObservation] = {}
    for row in rows:
        key = (row.source_type, row.resource_id.casefold())
        previous = selected.get(key)
        if previous is None or _inventory_time(row.observed_at) >= _inventory_time(previous.observed_at):
            selected[key] = row
    return sorted(selected.values(), key=lambda row: (row.source_type, row.resource_id.casefold()))


def _inventory_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def normalize_paas_resources(
    rows: list[dict],
    observed: str,
    *,
    run_id: str,
) -> list[dict]:
    """Project non-VM/Arc generic Resources rows into ResourceObservation rows."""
    observations: list[ResourceObservation] = []
    for row in rows:
        resource_type = str(row.get("type") or row.get("resource_type") or "").casefold()
        if resource_type in {
            "microsoft.compute/virtualmachines",
            "microsoft.hybridcompute/machines",
        }:
            continue
        if not str(row.get("id") or row.get("resource_id") or "").strip():
            continue
        observations.append(
            ResourceObservation.from_provider_row(
                dict(row),
                family="paas",
                observed_at=str(row.get("observed_at") or row.get("observedAt") or observed),
                ingestion_run_id=run_id,
                query_version=str(row.get("query_version") or "inventory-resources-v1"),
            )
        )
    return [row.to_fabric_row() for row in observations]


__all__ = ["normalize_os_inventory", "normalize_paas_resources"]
