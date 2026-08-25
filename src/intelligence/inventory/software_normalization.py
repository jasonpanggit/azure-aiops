"""Deterministic software identity normalization and mapping projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from api.scope import Scope
from hermes_arg_connector.inventory_normalize import canonical_software_identity

from .mapping_repository import SoftwareMapping, SoftwareMappingRepository
from .models import SoftwareObservation


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
