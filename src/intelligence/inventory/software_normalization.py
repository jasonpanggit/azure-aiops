"""Deterministic software identity normalization and mapping projection."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from api.scope import Scope

from .mapping_repository import SoftwareMapping, SoftwareMappingRepository
from .models import MachineObservation, SoftwareObservation

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
    """Normalize software rows and retain only the current exact installation state."""

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


def deterministic_identity(raw_name: str, raw_version: str) -> tuple[str, str]:
    """Normalize only safe case/whitespace/version-prefix representations."""
    return canonical_software_identity(raw_name, raw_version)


def mapping_for_observation(
    row: SoftwareObservation,
    repository: SoftwareMappingRepository,
) -> SoftwareMapping | None:
    """Find an exact raw identity mapping, including publisher separation."""
    row_scope = Scope.from_mapping(
        {
            "subscription": [row.subscription_id] if row.subscription_id else [],
            "environment": [row.environment] if row.environment else [],
        }
    )
    for mapping in repository.read().mappings:
        if (
            mapping.raw_name == row.raw_software_name
            and mapping.raw_version == row.raw_software_version
            and mapping.publisher == row.publisher
            and scopes_overlap(
                row_scope,
                Scope.from_mapping(mapping.scope_predicate),
            )
        ):
            return mapping
    return None


def project_mapping(row: SoftwareObservation, mapping: SoftwareMapping) -> SoftwareObservation:
    """Apply only an approved mapping while retaining raw identity evidence."""
    return SoftwareObservation(
        **{
            **row.__dict__,
            "software_name": mapping.canonical_name,
            "software_version": mapping.canonical_version,
            "canonical_identity": mapping.canonical_identity,
            "mapping_id": mapping.mapping_id,
            "mapping_status": mapping.status,
            "mapping_revision": mapping.revision,
            "mapping_method": mapping.method,
            "mapping_confidence": mapping.confidence,
            "mapping_provenance": dict(mapping.provenance),
            "mapping_source_timestamp": mapping.source_timestamp,
        }
    )


def annotate_mapping(row: SoftwareObservation, mapping: SoftwareMapping) -> SoftwareObservation:
    """Expose review metadata without allowing an unapproved mapping to group."""
    return SoftwareObservation(
        **{
            **row.__dict__,
            "mapping_id": mapping.mapping_id,
            "mapping_status": mapping.status,
            "mapping_revision": mapping.revision,
            "mapping_method": mapping.method,
            "mapping_confidence": mapping.confidence,
            "mapping_provenance": dict(mapping.provenance),
            "mapping_source_timestamp": mapping.source_timestamp,
        }
    )


def suggestion_from_model_output(
    *,
    repository: SoftwareMappingRepository,
    raw_name: str,
    raw_version: str,
    publisher: str,
    model_output: Mapping[str, Any],
    source_timestamp: str,
    scope_predicate: Mapping[str, Any] | None = None,
) -> SoftwareMapping:
    """Persist malformed model output as a visible, non-authoritative review item."""
    deterministic_name, deterministic_version = deterministic_identity(raw_name, raw_version)
    errors: list[str] = []
    canonical_name = model_output.get("canonical_name") or model_output.get("name")
    canonical_version = model_output.get("canonical_version") or model_output.get("version")
    if not isinstance(canonical_name, str) or not canonical_name.strip():
        errors.append("canonical_name_missing")
        canonical_name = deterministic_name
    if not isinstance(canonical_version, str) or not canonical_version.strip():
        errors.append("canonical_version_missing")
        canonical_version = deterministic_version
    confidence = model_output.get("confidence", 0)
    try:
        confidence = float(confidence)
        if not 0 <= confidence <= 1:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("confidence_invalid")
        confidence = 0
    provided_provenance = model_output.get("provenance")
    provenance = (
        {
            key: str(value)[:512]
            for key, value in provided_provenance.items()
            if isinstance(key, str) and isinstance(value, (str, int, float, bool))
        }
        if isinstance(provided_provenance, Mapping)
        else {}
    )
    provenance["source"] = "ai"
    if errors:
        provenance["validation_error"] = ",".join(errors)
    return repository.suggest(
        raw_name=raw_name,
        raw_version=raw_version,
        publisher=publisher,
        canonical_name=str(canonical_name).strip(),
        canonical_version=str(canonical_version).strip(),
        method="ai",
        confidence=confidence,
        provenance=provenance,
        source_timestamp=source_timestamp,
        scope_predicate=scope_predicate,
        reason="Malformed model output retained as non-authoritative suggestion."
        if errors
        else "",
    )


def scopes_overlap(left: Scope, right: Scope) -> bool:
    for dimension in set(left.dimensions) & set(right.dimensions):
        if not left.values(dimension) & right.values(dimension):
            return False
    return True


def canonical_software_identity(name: str, version: str) -> tuple[str, str]:
    """Return deterministic display identity while preserving raw values."""

    clean_name = _clean(name) or "Unknown Software"
    clean_version = _clean(version) or "Unknown"
    clean_version = _VERSION_PREFIX.sub("", clean_version).strip() or "Unknown"
    suffix = _TRAILING_VERSION.search(clean_name)
    if suffix and _normalize_version(suffix.group(0)) == _normalize_version(clean_version):
        clean_name = clean_name[: suffix.start()].strip(" -_")
    return clean_name or "Unknown Software", clean_version


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


def _normalize_version(value: str) -> str:
    return _VERSION_PREFIX.sub("", _clean(value)).casefold().replace(" ", "")


def _clean(value: Any) -> str:
    return _SPACE.sub(" ", str(value or "").strip())


def _machine_key(row: SoftwareObservation) -> str:
    if row.resource_id:
        return f"resource:{row.resource_id.casefold()}"
    if row.source_computer_id:
        return f"source:{row.subscription_id.casefold()}:{row.source_computer_id.casefold()}"
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
