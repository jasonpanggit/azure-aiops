"""Canonical installed-software normalization and authoritative machine joins."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from intelligence.inventory.models import MachineObservation, SoftwareObservation

_SPACE = re.compile(r"\s+")
_VERSION_PREFIX = re.compile(r"^[vV]\s*")
_TRAILING_VERSION = re.compile(r"\s+v?\d[\w.+~-]*$", re.IGNORECASE)


def normalize_configuration_data(
    rows: Iterable[Mapping[str, Any]],
    machines: Iterable[MachineObservation | Mapping[str, Any]] = (),
    *,
    observed_at: str = "",
    query_version: str = "inventory-software-v1",
) -> list[SoftwareObservation]:
    """Normalize software rows and retain only the current exact installation state.

    Rows are first reduced by exact machine plus canonical software name so a
    newer version replaces an older observation.  A second guard is keyed by
    exact machine plus canonical name/version, which removes representation
    duplicates such as ``7-Zip 19.00`` and ``7-Zip v19.00`` without fuzzy
    hostname matching.
    """

    machine_index = _machine_index(machines)
    candidates: list[SoftwareObservation] = []
    for index, row in enumerate(rows):
        if str(row.get("ConfigDataType") or row.get("config_data_type") or "").casefold() != "software":
            continue
        candidates.append(
            _software_row(
                row,
                machine_index,
                observed_at=observed_at,
                query_version=query_version,
                fallback_index=index,
            )
        )

    latest_by_name: dict[tuple[str, str], SoftwareObservation] = {}
    for row in candidates:
        key = (_machine_key(row), row.software_name.casefold())
        previous = latest_by_name.get(key)
        if previous is None or _newer(row, previous):
            latest_by_name[key] = row

    guarded: dict[tuple[str, str], SoftwareObservation] = {}
    for row in latest_by_name.values():
        key = (_machine_key(row), row.canonical_identity.casefold())
        previous = guarded.get(key)
        if previous is None or _newer(row, previous):
            guarded[key] = row
    return sorted(
        guarded.values(),
        key=lambda row: (
            row.software_name.casefold(),
            row.software_version.casefold(),
            row.resource_id.casefold(),
            row.machine_name.casefold(),
        ),
    )


# Names used by callers that describe the source rather than the operation.
normalize_software_observations = normalize_configuration_data


def _machine_index(
    machines: Iterable[MachineObservation | Mapping[str, Any]],
) -> dict[str, MachineObservation]:
    index: dict[str, MachineObservation] = {}
    for machine in machines:
        item = (
            machine
            if isinstance(machine, MachineObservation)
            else MachineObservation.from_mapping(dict(machine))
        )
        resource_id = item.resource_id.strip()
        if resource_id:
            index.setdefault(resource_id.casefold(), item)
    return index


def _software_row(
    row: Mapping[str, Any],
    machine_index: dict[str, MachineObservation],
    *,
    observed_at: str,
    query_version: str,
    fallback_index: int,
) -> SoftwareObservation:
    raw_name = _clean(row.get("SoftwareName") or row.get("software_name"))
    raw_version = _clean(row.get("CurrentVersion") or row.get("software_version"))
    name, version = canonical_software_identity(raw_name, raw_version)
    resource_id = _clean(row.get("_ResourceId") or row.get("resource_id"))
    machine = machine_index.get(resource_id.casefold()) if resource_id else None
    generated_at = _clean(row.get("TimeGenerated") or row.get("time_generated") or observed_at)
    if not generated_at:
        generated_at = "1970-01-01T00:00:00+00:00"
    if machine:
        subscription_id = machine.subscription_id
        resource_group = machine.resource_group
        environment = machine.environment
        machine_name = machine.machine_name
        source_type: str | None = machine.source_type
        join_status = "linked"
    else:
        subscription_id = _clean(row.get("_SubscriptionId") or row.get("subscription_id"))
        resource_group = "Unknown"
        environment = "Unknown"
        machine_name = _clean(row.get("Computer") or row.get("computer"))
        source_type = None
        join_status = "unlinked"
    source_computer_id = _clean(row.get("SourceComputerId") or row.get("source_computer_id"))
    evidence = (
        {
            "source_engine": "Azure Monitor Logs",
            "source_table": "ConfigurationData",
            "observed_at": generated_at,
            "source_id": resource_id or source_computer_id,
            "query_version": query_version,
        },
    )
    # Rows without an authoritative resource ID must never collapse solely
    # because two machines report the same hostname.
    if not resource_id and not source_computer_id:
        machine_name = f"{machine_name}#{fallback_index}"
    return SoftwareObservation(
        software_name=name,
        software_version=version,
        raw_software_name=raw_name,
        raw_software_version=raw_version,
        canonical_identity=f"{name}|{version}",
        resource_id=resource_id,
        machine_name=machine_name,
        source_computer_id=source_computer_id,
        source_type=source_type,
        join_status=join_status,
        subscription_id=subscription_id,
        resource_group=resource_group,
        environment=environment,
        publisher=_clean(row.get("Publisher") or row.get("publisher")),
        software_type=_clean(row.get("SoftwareType") or row.get("software_type")),
        observed_at=generated_at,
        evidence=evidence,
    )


def canonical_software_identity(name: str, version: str) -> tuple[str, str]:
    """Return deterministic display identity while preserving raw values."""

    clean_name = _clean(name) or "Unknown Software"
    clean_version = _clean(version) or "Unknown"
    clean_version = _VERSION_PREFIX.sub("", clean_version).strip() or "Unknown"
    # ConfigurationData deployments sometimes put the version in SoftwareName
    # as well as CurrentVersion. Remove it only when it agrees with the version.
    suffix = _TRAILING_VERSION.search(clean_name)
    if suffix and _normalize_version(suffix.group(0)) == _normalize_version(clean_version):
        clean_name = clean_name[: suffix.start()].strip(" -_")
    return clean_name or "Unknown Software", clean_version


def _normalize_version(value: str) -> str:
    return _VERSION_PREFIX.sub("", _clean(value)).casefold().replace(" ", "")


def _clean(value: Any) -> str:
    return _SPACE.sub(" ", str(value or "").strip())


def _machine_key(row: SoftwareObservation) -> str:
    if row.resource_id:
        return f"resource:{row.resource_id.casefold()}"
    if row.source_computer_id:
        return f"source:{row.subscription_id.casefold()}:{row.source_computer_id.casefold()}"
    # The index-bearing machine name intentionally prevents hostname collisions.
    return f"unlinked:{row.subscription_id.casefold()}:{row.machine_name.casefold()}"


def _newer(candidate: SoftwareObservation, previous: SoftwareObservation) -> bool:
    candidate_time = _time(candidate.observed_at)
    previous_time = _time(previous.observed_at)
    if candidate_time != previous_time:
        return candidate_time > previous_time
    return (
        candidate.raw_software_name.casefold(),
        candidate.raw_software_version.casefold(),
    ) >= (
        previous.raw_software_name.casefold(),
        previous.raw_software_version.casefold(),
    )


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
