from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .models import MachineObservation, ResourceObservation

#: Sentinel used when a source carries no usable operating-system signal.
UNKNOWN = "Unknown"

#: Product name used for every Windows Server release.
#:
#: The lifecycle catalog is keyed on ``(product, version)`` pairs such as
#: ``("Windows Server", "2016")``. Normalization must emit exactly that shape or
#: :meth:`EOLCatalog.classify_product` falls through to ``Unknown`` and the UI
#: renders "EOL date needs review" for machines we can actually classify.
_WINDOWS_SERVER = "Windows Server"

#: Windows Server ``major.minor.build`` numbers to their catalog version.
#:
#: Build numbers are stable per release, so an Arc agent reporting
#: ``10.0.14393.9140`` is unambiguously Windows Server 2016.
#: https://learn.microsoft.com/en-us/windows-server/get-started/windows-server-release-info
_WINDOWS_BUILD_VERSIONS = {
    "10.0.14393": "2016",
    "10.0.17763": "2019",
    "10.0.20348": "2022",
    "10.0.26100": "2025",
    "6.3.9600": "2012 R2",
    "6.2.9200": "2012",
    "6.1.7601": "2008 R2",
    "6.0.6003": "2008",
}

#: Windows Server release years, newest first so "2012 R2" wins over "2012".
_WINDOWS_RELEASES = ("2025", "2022", "2019", "2016", "2012 R2", "2012", "2008 R2", "2008")

#: Ubuntu codenames used in Azure marketplace offers to their catalog version.
_UBUNTU_CODENAMES = {
    "noble": "24.04 LTS",
    "jammy": "22.04 LTS",
    "focal": "20.04 LTS",
}

#: Canonical catalog product names keyed by the token a source reports.
_LINUX_PRODUCTS = (
    ("red hat enterprise linux", "Red Hat Enterprise Linux"),
    ("redhat", "Red Hat Enterprise Linux"),
    ("rhel", "Red Hat Enterprise Linux"),
    ("ubuntu", "Ubuntu"),
    ("debian", "Debian"),
    ("centos", "CentOS"),
    ("sles", "SLES"),
    ("suse", "SLES"),
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _is_unknown(value: str) -> bool:
    return not value or value.casefold() == "unknown"


def _windows_release(*candidates: str) -> str:
    """Return the catalog version for the first candidate naming a release."""
    for candidate in candidates:
        text = _clean(candidate).casefold()
        if not text:
            continue
        # Normalize "2012-r2"/"2012_r2" so the "2012 R2" token matches.
        text = re.sub(r"[-_]", " ", text)
        for release in _WINDOWS_RELEASES:
            if release.casefold() in text:
                return release
    return ""


def _windows_build_release(version: str) -> str:
    """Return the catalog version for a Windows ``major.minor.build`` string."""
    parts = _clean(version).split(".")
    if len(parts) >= 3:
        return _WINDOWS_BUILD_VERSIONS.get(".".join(parts[:3]), "")
    return ""


def _ubuntu_version(*candidates: str) -> str:
    """Return the catalog version for Ubuntu, which is keyed with an LTS suffix."""
    for candidate in candidates:
        text = _clean(candidate).casefold()
        if not text:
            continue
        for codename, version in _UBUNTU_CODENAMES.items():
            if codename in text:
                return version
        # Accept "22.04", "22_04-lts-gen2", and "22.04 LTS" alike.
        match = re.search(r"(\d{2})[._](\d{2})", text)
        if match:
            release = f"{match.group(1)}.{match.group(2)}"
            return f"{release} LTS" if int(match.group(1)) % 2 == 0 else release
    return ""


def _major_version(*candidates: str) -> str:
    """Return the leading major version number, used by RHEL and Debian."""
    for candidate in candidates:
        match = re.search(r"\d+", _clean(candidate))
        if match:
            return match.group(0)
    return ""


def canonicalize_os(
    *,
    os_name: str = "",
    os_version: str = "",
    os_type: str = "",
    image_publisher: str = "",
    image_offer: str = "",
    image_sku: str = "",
) -> tuple[str, str]:
    """Resolve raw source fields into a catalog-aligned ``(product, version)``.

    Azure exposes the operating system through different fields depending on the
    source: native VMs carry marketplace image coordinates, while Arc machines
    report agent telemetry. Both are reduced here to the same ``(product,
    version)`` vocabulary the lifecycle catalog is keyed on, so EOL dates
    resolve regardless of which source observed the machine.
    """
    name = _clean(os_name)
    version = _clean(os_version)
    haystack = " ".join(
        part for part in (name, version, os_type, image_publisher, image_offer, image_sku) if part
    ).casefold()

    if "windows" in haystack:
        release = (
            _windows_build_release(version)
            or _windows_release(version, name, os_type, image_sku, image_offer)
        )
        # Client Windows is not in the server lifecycle catalog; keep the raw
        # signal so the group stays reviewable rather than mislabelled.
        if not release and re.search(r"windows\s*(10|11|7)\b", haystack):
            client = re.search(r"windows\s*(10|11|7)\b", haystack)
            return f"Windows {client.group(1)}", version or UNKNOWN
        return _WINDOWS_SERVER, release or UNKNOWN

    for token, product in _LINUX_PRODUCTS:
        if token in haystack:
            if product == "Ubuntu":
                release = _ubuntu_version(version, image_sku, image_offer, name)
            else:
                release = _major_version(version, image_sku, name)
            return product, release or UNKNOWN

    if name and not _is_unknown(name):
        return name, version or UNKNOWN
    return UNKNOWN, version or UNKNOWN


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
        image_offer = str(row.get("imageOffer") or "")
        image_publisher = str(row.get("imagePublisher") or "")
        # Native VMs expose the OS through marketplace image coordinates and
        # may also carry osName/osVersion when the row came from a snapshot.
        os_name, os_version = canonicalize_os(
            os_name=str(row.get("osName") or properties.get("osName") or ""),
            os_version=str(row.get("osVersion") or properties.get("osVersion") or ""),
            os_type=os_type,
            image_publisher=image_publisher,
            image_offer=image_offer,
            image_sku=image_sku,
        )

        row = {
            **row,
            "os_name": os_name,
            "os_version": os_version,
            "os_type": os_type,
            "image_publisher": image_publisher,
            "image_offer": image_offer,
            "image_sku": image_sku,
            "image_version": row.get("imageVersion") or "",
        }
    else:
        # Arc machines have actual installed OS info from agent telemetry.
        properties = row.get("properties") if isinstance(row.get("properties"), Mapping) else {}
        os_sku = str(row.get("osSku") or properties.get("osSku") or "")
        os_name, os_version = canonicalize_os(
            os_name=str(row.get("osName") or properties.get("osName") or ""),
            os_version=str(row.get("osVersion") or properties.get("osVersion") or ""),
            os_type=os_sku,
        )

        row = {
            **row,
            "os_name": os_name,
            "os_version": os_version,
            "computer_name": row.get("computerName") or properties.get("computerName") or "",
            "machine_status": row.get("status") or properties.get("status") or "",
            "os_type": os_sku,
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


__all__ = ["canonicalize_os", "normalize_os_inventory", "normalize_paas_resources"]
