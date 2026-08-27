from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .models import MachineObservation, ResourceObservation


# Windows OS version to canonical product name mapping
# Based on Windows Server release versions: https://learn.microsoft.com/en-us/windows-server/get-started/windows-server-release-info
_WINDOWS_VERSION_MAP = {
    "10.0.14393": "Windows Server 2016",      # RTM
    "10.0.17763": "Windows Server 2019",      # RTM
    "10.0.20348": "Windows Server 2022",      # RTM
    "10.0.26100": "Windows Server 2025",      # RTM
    "6.3.9600": "Windows Server 2012 R2",     # RTM
    "6.2.9200": "Windows Server 2012",        # RTM
    "6.1.7601": "Windows Server 2008 R2",     # SP1
    "6.0.6003": "Windows Server 2008",        # SP2
}


def _canonicalize_windows_version(version_str: str) -> str:
    """Map Windows version numbers to canonical product names.
    
    Args:
        version_str: Version string like "10.0.14393.9140" or "Windows Server 2016"
        
    Returns:
        Canonical OS name like "Windows Server 2016" or "Unknown" if not mappable
    """
    if not version_str or version_str.casefold() in {"unknown", ""}:
        return "Unknown"
    
    # Already a canonical name
    if version_str.casefold().startswith("windows server"):
        return version_str
    
    # Extract major.minor.build from version string (e.g., "10.0.14393" from "10.0.14393.9140")
    parts = version_str.split(".")
    if len(parts) >= 3:
        major_minor_build = ".".join(parts[:3])
        if major_minor_build in _WINDOWS_VERSION_MAP:
            return _WINDOWS_VERSION_MAP[major_minor_build]
    
    return "Unknown"


def _canonicalize_os_name(os_name: str) -> str:
    """Standardize OS name capitalization and format.
    
    Args:
        os_name: Raw OS name from ARG (e.g., "windows", "Windows", "linux")
        
    Returns:
        Canonical OS name (e.g., "Windows", "Linux", "Unknown")
    """
    if not os_name:
        return "Unknown"
    
    normalized = os_name.strip().casefold()
    if normalized.startswith("windows"):
        return "Windows"
    elif normalized.startswith("linux"):
        return "Linux"
    elif normalized.startswith("ubuntu"):
        return "Ubuntu"
    elif normalized.startswith("rhel") or normalized.startswith("red hat"):
        return "RHEL"
    elif normalized.startswith("debian"):
        return "Debian"
    elif normalized.startswith("centos"):
        return "CentOS"
    elif normalized.startswith("sles"):
        return "SLES"
    elif normalized.startswith("mac") or normalized.startswith("darwin"):
        return "macOS"
    
    return os_name.strip() if os_name.strip() else "Unknown"


def _extract_windows_version_from_sku(image_sku: str) -> str:
    """Extract Windows Server version from Azure VM image SKU.
    
    Args:
        image_sku: Image SKU string like "2016-Datacenter", "2019-Datacenter-gensecond", etc.
        
    Returns:
        Canonical OS name like "Windows Server 2016" or "Unknown" if not extractable
    """
    if not image_sku:
        return "Unknown"
    
    # Extract year from SKU (e.g., "2016" from "2016-Datacenter")
    sku_lower = image_sku.strip().casefold()
    
    # Match common Windows Server SKU patterns
    if "2025" in sku_lower:
        return "Windows Server 2025"
    elif "2022" in sku_lower:
        return "Windows Server 2022"
    elif "2019" in sku_lower:
        return "Windows Server 2019"
    elif "2016" in sku_lower:
        return "Windows Server 2016"
    elif "2012-r2" in sku_lower or "2012 r2" in sku_lower:
        return "Windows Server 2012 R2"
    elif "2012" in sku_lower:
        return "Windows Server 2012"
    elif "2008-r2" in sku_lower or "2008 r2" in sku_lower:
        return "Windows Server 2008 R2"
    elif "2008" in sku_lower:
        return "Windows Server 2008"
    
    # Also check for client Windows versions
    if "win11" in sku_lower or "windows-11" in sku_lower:
        return "Windows 11"
    elif "win10" in sku_lower or "windows-10" in sku_lower:
        return "Windows 10"
    elif "windows-7" in sku_lower or "win7" in sku_lower:
        return "Windows 7"
    
    return "Unknown"


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
        image_sku = str(row.get("imageSku") or "").strip()
        
        # For native VMs, extract version from image SKU
        canonical_os_name = _canonicalize_os_name(os_type) if os_type else "Unknown"
        
        # Extract version from SKU for Windows, otherwise Unknown
        if canonical_os_name == "Windows" and image_sku:
            os_version = _extract_windows_version_from_sku(image_sku)
        else:
            os_version = "Unknown"
        
        row = {
            **row,
            "os_name": canonical_os_name,
            "os_version": os_version,
            "os_type": os_type,
            "image_publisher": row.get("imagePublisher") or "",
            "image_offer": row.get("imageOffer") or "",
            "image_sku": image_sku,
            "image_version": row.get("imageVersion") or "",
        }
    else:
        # Arc machines have actual installed OS info from agent telemetry
        properties = row.get("properties") if isinstance(row.get("properties"), Mapping) else {}
        raw_os_name = str(row.get("osName") or properties.get("osName") or "").strip()
        raw_os_version = str(row.get("osVersion") or properties.get("osVersion") or "").strip()
        
        # Canonicalize OS name
        canonical_os_name = _canonicalize_os_name(raw_os_name)
        
        # For Windows, map version numbers to product names; for others, keep raw version
        if canonical_os_name == "Windows":
            canonical_os_version = _canonicalize_windows_version(raw_os_version)
        else:
            canonical_os_version = raw_os_version if raw_os_version else "Unknown"
        
        row = {
            **row,
            "os_name": canonical_os_name,
            "os_version": canonical_os_version,
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
