"""Typed, bounded page context contracts for contextual Copilot requests.

The browser is not an authority.  It submits the bounded state it rendered and
the API validates that state before any specialist is invoked.  Keeping this
contract separate from the provider models also makes a request replayable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.scope import Scope
from operations.orchestration_contract import (
    AzureEntityRef,
    CanonicalCoverage,
    CanonicalEvidence,
    CanonicalEvidenceSnapshot,
    DomainEntityRef,
    EntityRef,
    EvidenceSnapshotV2,
    SnapshotConflict,
    SnapshotEvidence,
)

MAX_SNAPSHOT_BYTES = 128 * 1024
MAX_SELECTED_RESOURCES = 50
MAX_EVIDENCE_ROWS = 200
MAX_EVIDENCE_ROW_BYTES = 8 * 1024


def _canonical_resource_attributes(resource_id: str) -> dict[str, str]:
    """Derive authorization dimensions from an Azure resource ID.

    Snapshot attributes are presentation data supplied by the browser.  The
    canonical ID is the only identity input used for scope authorization.
    """
    value = str(resource_id or "").strip()
    parts = [part for part in value.split("/") if part]
    if (
        not value.startswith("/")
        or len(parts) < 2
        or parts[0].casefold() != "subscriptions"
        or not parts[1]
    ):
        raise ValueError("resource identifiers must be canonical resource IDs")
    attributes = {"subscription": parts[1].casefold()}
    if len(parts) == 2:
        return attributes
    if len(parts) >= 4 and parts[2].casefold() == "resourcegroups":
        if not parts[3]:
            raise ValueError("resource identifiers must be canonical resource IDs")
        attributes["resource_group"] = parts[3].casefold()
    provider_index = next(
        (index for index, part in enumerate(parts) if part.casefold() == "providers"),
        None,
    )
    if provider_index is None or len(parts) <= provider_index + 2:
        raise ValueError("resource identifiers must be canonical resource IDs")
    return attributes


def _canonical_resource_id(resource_id: str) -> str:
    _canonical_resource_attributes(resource_id)
    return "/" + "/".join(part.casefold() for part in resource_id.split("/") if part)


def _normalized_identity_part(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def _digest(prefix: str, *parts: str) -> str:
    encoded = json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()[:32]}"


_STATUS_WARNING = {
    "ok": 0,
    "empty": 1,
    "partial": 2,
    "unavailable": 3,
    "denied": 4,
}
_SEVERITY_PRIORITY = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
_QUALITY_PRIORITY = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
_FRESHNESS_PRIORITY = {
    "unavailable": 0,
    "stale": 1,
    "partial": 2,
    "unknown": 3,
    "fresh": 4,
}
_FRESHNESS_WARNING = {
    "fresh": 0,
    "unknown": 1,
    "partial": 2,
    "stale": 3,
    "unavailable": 4,
}

DomainEntityResolver = Callable[
    [DomainEntityRef],
    Mapping[str, Any] | None,
]


def _canonical_entity(
    entity: EntityRef,
    *,
    effective_scope: Scope,
    domain_resolver: DomainEntityResolver | None,
) -> str:
    if isinstance(entity, AzureEntityRef):
        resource_id = _canonical_resource_id(entity.resource_id)
        if not effective_scope.matches(_canonical_resource_attributes(resource_id)):
            raise ValueError("snapshot entity is outside the effective read scope")
        return f"azure:{resource_id}"

    if domain_resolver is None:
        raise ValueError("domain entity requires a server-side identity resolver")
    resolution = domain_resolver(entity)
    if not isinstance(resolution, Mapping):
        raise TypeError("domain entity resolver must return identity metadata")
    canonical_source_key = str(resolution.get("source_key") or "").strip()
    scope_payload = resolution.get("scope")
    if (
        not canonical_source_key
        or not isinstance(scope_payload, Mapping)
        or not effective_scope.matches(scope_payload)
    ):
        raise ValueError("snapshot entity is outside the effective read scope")
    return ":".join(
        (
            "domain",
            _normalized_identity_part(entity.namespace),
            _normalized_identity_part(entity.kind),
            _normalized_identity_part(canonical_source_key),
        )
    )


def _row_freshness(
    source: str,
    freshness_by_source: Mapping[str, str],
) -> str:
    return freshness_by_source.get(_normalized_identity_part(source), "unknown")


def _canonical_row(
    row: SnapshotEvidence,
    *,
    entity_key: str,
    freshness: str,
    selected_entity_keys: set[str],
) -> CanonicalEvidence:
    source_key = row.source_key or row.evidence_id
    stable_id = _digest(
        "evidence",
        _normalized_identity_part(row.source),
        _normalized_identity_part(source_key),
        entity_key,
        _normalized_identity_part(row.claim_type),
    )
    normalized_data = json.dumps(
        row.data,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    variant_id = _digest("variant", stable_id, normalized_data)
    return CanonicalEvidence(
        stable_id=stable_id,
        variant_id=variant_id,
        entity_key=entity_key,
        source=row.source,
        source_key=source_key,
        claim_type=row.claim_type,
        status=row.status,
        freshness=freshness,
        observed_at=row.observed_at,
        citations=sorted({row.evidence_id, *row.citations}),
        selected=row.selected or entity_key in selected_entity_keys,
        direct=row.direct,
        actionable=row.actionable,
        severity=row.severity,
        quality=row.quality,
        data=row.data,
    )


def _stronger_value(
    left: str,
    right: str,
    priorities: Mapping[str, int],
) -> str:
    return max((left, right), key=lambda item: priorities[item])


def _merge_duplicate(
    current: CanonicalEvidence,
    incoming: CanonicalEvidence,
) -> CanonicalEvidence:
    return current.model_copy(
        update={
            "status": _stronger_value(
                current.status,
                incoming.status,
                _STATUS_WARNING,
            ),
            "freshness": _stronger_value(
                current.freshness,
                incoming.freshness,
                _FRESHNESS_WARNING,
            ),
            "observed_at": max(current.observed_at, incoming.observed_at),
            "citations": sorted({*current.citations, *incoming.citations}),
            "selected": current.selected or incoming.selected,
            "direct": current.direct or incoming.direct,
            "actionable": current.actionable or incoming.actionable,
            "severity": _stronger_value(
                current.severity,
                incoming.severity,
                _SEVERITY_PRIORITY,
            ),
            "quality": _stronger_value(
                current.quality,
                incoming.quality,
                _QUALITY_PRIORITY,
            ),
        }
    )


def _retention_key(row: CanonicalEvidence) -> tuple[int, ...] | tuple[Any, ...]:
    return (
        -int(row.selected),
        -int(row.direct),
        -int(row.actionable),
        -_SEVERITY_PRIORITY[row.severity],
        -_FRESHNESS_PRIORITY[row.freshness],
        -_QUALITY_PRIORITY[row.quality],
        row.stable_id,
        row.variant_id,
    )


def canonicalize_snapshot_v2(
    snapshot: EvidenceSnapshotV2,
    *,
    effective_scope: Scope,
    domain_resolver: DomainEntityResolver | None = None,
    retention_limit: int = MAX_EVIDENCE_ROWS,
) -> CanonicalEvidenceSnapshot:
    """Authorize, canonicalize, rank, retain, and citation-close snapshot v2.

    All entity identities are authorized before ranking so a low-priority or
    truncated row can never bypass the effective read scope.
    """

    if not 1 <= retention_limit <= MAX_EVIDENCE_ROWS:
        raise ValueError("snapshot retention limit is outside the policy bound")

    freshness_by_source: dict[str, str] = {}
    for record in snapshot.freshness:
        source = _normalized_identity_part(record.source)
        previous = freshness_by_source.get(source)
        freshness_by_source[source] = (
            record.status
            if previous is None
            else _stronger_value(
                previous,
                record.status,
                _FRESHNESS_WARNING,
            )
        )

    selected_entity_keys = {
        _canonical_entity(
            entity,
            effective_scope=effective_scope,
            domain_resolver=domain_resolver,
        )
        for entity in snapshot.selected_entities
    }

    authorized_rows: list[CanonicalEvidence] = []
    for row in snapshot.evidence:
        entity = row.entity
        if entity is None and row.resource_id.startswith("/"):
            entity = AzureEntityRef(type="azure", resource_id=row.resource_id)
        if entity is None:
            raise ValueError("snapshot evidence is missing canonical entity identity")
        entity_key = _canonical_entity(
            entity,
            effective_scope=effective_scope,
            domain_resolver=domain_resolver,
        )
        authorized_rows.append(
            _canonical_row(
                row,
                entity_key=entity_key,
                freshness=_row_freshness(row.source, freshness_by_source),
                selected_entity_keys=selected_entity_keys,
            )
        )

    deduplicated: dict[tuple[str, str], CanonicalEvidence] = {}
    for row in authorized_rows:
        key = (row.stable_id, row.variant_id)
        existing = deduplicated.get(key)
        deduplicated[key] = row if existing is None else _merge_duplicate(existing, row)

    ranked = sorted(deduplicated.values(), key=_retention_key)
    retained = ranked[:retention_limit]
    discarded_count = len(ranked) - len(retained)

    retained_refs = {citation for row in retained for citation in row.citations}
    for claim in snapshot.material_claims:
        discarded_refs = sorted(set(claim.evidence_refs) - retained_refs)
        if discarded_refs:
            raise ValueError(
                f"material claim {claim.claim_id!r} has discarded evidence reference "
                f"{discarded_refs[0]!r}"
            )

    conflict_groups: dict[str, list[str]] = {}
    for row in retained:
        conflict_groups.setdefault(row.stable_id, []).append(row.variant_id)
    conflicts = [
        SnapshotConflict(
            conflict_id=_digest("conflict", stable_id),
            stable_id=stable_id,
            variant_ids=sorted(set(variant_ids)),
        )
        for stable_id, variant_ids in sorted(conflict_groups.items())
        if len(set(variant_ids)) > 1
    ]

    uncertainty: list[str] = []
    if not snapshot.coverage.complete:
        uncertainty.append("visible subset is incomplete")
    for source, status in sorted(freshness_by_source.items()):
        if status != "fresh":
            uncertainty.append(f"{source} freshness is {status}")
    if conflicts:
        uncertainty.append("conflicting evidence requires resolution")
    if discarded_count:
        suffix = "row" if discarded_count == 1 else "rows"
        uncertainty.append(
            f"evidence retention limit discarded {discarded_count} {suffix}"
        )

    insufficiency_reasons: list[str] = []
    classification = "ready"
    if not retained:
        if snapshot.coverage.complete and snapshot.coverage.total_count == 0:
            classification = "empty"
        else:
            classification = "insufficient_evidence"
            insufficiency_reasons.append("no usable evidence remains")
    else:
        statuses = {row.status for row in retained}
        if statuses == {"denied"}:
            insufficiency_reasons.append("all retained evidence is denied")
        elif statuses == {"unavailable"}:
            insufficiency_reasons.append("all retained evidence is unavailable")
        elif not statuses & {"ok", "partial"}:
            insufficiency_reasons.append("no usable evidence remains")
        if all(
            row.freshness in {"stale", "unavailable"}
            or row.status in {"unavailable", "denied"}
            for row in retained
        ):
            insufficiency_reasons.append(
                "all retained evidence is stale or unavailable"
            )
        for claim in snapshot.material_claims:
            if claim.requires_complete_coverage and not snapshot.coverage.complete:
                insufficiency_reasons.append(
                    f"{claim.claim_id} requires complete coverage"
                )
        if insufficiency_reasons:
            classification = "insufficient_evidence"

    return CanonicalEvidenceSnapshot(
        page_kind=snapshot.page_kind,
        page_id=snapshot.page_id,
        coverage=CanonicalCoverage(
            visible_count=snapshot.coverage.visible_count,
            total_count=snapshot.coverage.total_count,
            complete=snapshot.coverage.complete,
            state="complete" if snapshot.coverage.complete else "partial",
        ),
        evidence=retained,
        conflicts=conflicts,
        uncertainty=list(dict.fromkeys(uncertainty)),
        classification=classification,
        insufficiency_reasons=list(dict.fromkeys(insufficiency_reasons)),
    )


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SelectedResource(SnapshotModel):
    resource_id: str = Field(min_length=1, max_length=512)
    resource_type: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=256)
    attributes: dict[str, str] = Field(default_factory=dict)


class FreshnessRecord(SnapshotModel):
    source: str = Field(min_length=1, max_length=128)
    observed_at: str = Field(min_length=1, max_length=128)
    status: Literal["fresh", "stale", "partial", "unavailable"] = "fresh"


class ScopeAuthorization(SnapshotModel):
    declared: dict[str, list[str]] = Field(default_factory=dict)
    authorized: bool = True

    @field_validator("declared")
    @classmethod
    def valid_dimensions(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        # Scope performs the canonical dimension validation and normalization.
        Scope.from_mapping(value)
        return value


class EvidenceRow(SnapshotModel):
    evidence_id: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    resource_id: str = Field(default="", max_length=512)
    section: str = Field(min_length=1, max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "empty", "unavailable", "denied"] = "ok"
    observed_at: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def bounded_row(self) -> EvidenceRow:
        if (
            len(json.dumps(self.data, default=str, separators=(",", ":")))
            > MAX_EVIDENCE_ROW_BYTES
        ):
            raise ValueError("evidence row exceeds size limit")
        return self


class PageSnapshot(SnapshotModel):
    """The exact page state used to answer one contextual question."""

    version: Literal["1"] = "1"
    page_kind: Literal[
        "network", "vulnerability", "patch", "incident", "governance", "resource"
    ]
    page_id: str = Field(min_length=1, max_length=128)
    selected_resources: list[SelectedResource] = Field(
        default_factory=list, max_length=MAX_SELECTED_RESOURCES
    )
    filters: dict[str, list[str]] = Field(default_factory=dict)
    freshness: list[FreshnessRecord] = Field(default_factory=list, max_length=32)
    scope: ScopeAuthorization = Field(default_factory=ScopeAuthorization)
    evidence: list[EvidenceRow] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_ROWS
    )
    question: str = Field(min_length=1, max_length=1024)
    rechecks: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_snapshot(self) -> PageSnapshot:
        if len(self.model_dump_json()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("page snapshot exceeds size limit")
        ids = {row.evidence_id for row in self.evidence}
        for resource in self.selected_resources:
            if resource.resource_id.startswith(
                "http://"
            ) or resource.resource_id.startswith("https://"):
                raise ValueError("resource identifiers must not be URLs")
        for check in self.rechecks:
            if check not in ids:
                raise ValueError(f"recheck {check!r} is not a named evidence row")
        return self

    def validate_effective_scope(self, effective: Scope) -> None:
        declared = Scope.from_mapping(self.scope.declared)
        if not effective.is_unrestricted():
            for dimension, values in declared.dimensions.items():
                allowed = effective.values(dimension)
                if not allowed or not values <= allowed:
                    raise ValueError(
                        "snapshot scope is wider than the effective read scope"
                    )
        if not self.scope.authorized:
            raise ValueError("snapshot scope authorization is not valid")
        for resource in self.selected_resources:
            identity = _canonical_resource_attributes(resource.resource_id)
            if any(
                resource.attributes.get(dimension)
                and str(resource.attributes[dimension]).strip().casefold() != value
                for dimension, value in identity.items()
            ):
                raise ValueError("selected resource attributes disagree with its ID")
            if not effective.matches(identity):
                raise ValueError(
                    "selected resource is outside the effective read scope"
                )
        for row in self.evidence:
            if not row.resource_id:
                continue
            identity = _canonical_resource_attributes(row.resource_id)
            if not effective.matches(identity):
                raise ValueError(
                    "evidence resource is outside the effective read scope"
                )

    def snapshot_hash(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


def deterministic_network_findings(snapshot: PageSnapshot) -> list[dict[str, Any]]:
    """Evaluate known Network checks without rehydrating provider state."""
    findings: list[dict[str, Any]] = []
    degraded_freshness = any(
        item.status in {"stale", "partial", "unavailable"}
        for item in snapshot.freshness
    )
    freshness_uncertainty = [
        f"source freshness is {item.status}: {item.source}"
        for item in snapshot.freshness
        if item.status in {"stale", "partial", "unavailable"}
    ]
    for row in snapshot.evidence:
        if row.section not in {"network", "topology", "nsg", "route", "firewall"}:
            continue
        data = row.data
        kind = str(data.get("check") or data.get("category") or row.section).casefold()
        issue = str(data.get("issue") or data.get("finding") or "").strip()
        if not issue and data.get("compliant") is not True:
            issue = f"{row.section} evidence requires review"
        if not issue:
            continue
        check_id = {
            "nsg": "NET-NSG-001",
            "route": "NET-ROUTE-001",
            "firewall": "NET-FW-001",
            "segmentation": "NET-SEG-001",
            "blast-radius": "NET-BLAST-001",
        }.get(kind, f"NET-{row.section.upper()}-001")
        status = row.status
        verified = status == "ok" and bool(
            data.get("compliant") is False or data.get("finding")
        )
        affected_by_freshness = degraded_freshness or status != "ok"
        finding_status = (
            "verified" if verified else ("hypothesis" if status == "ok" else status)
        )
        uncertainty = [] if verified else ["evidence does not prove the conclusion"]
        if affected_by_freshness and verified:
            finding_status = "hypothesis"
            uncertainty = list(freshness_uncertainty) or [
                "source status does not prove the conclusion"
            ]
        confidence = (
            "high"
            if verified and not affected_by_freshness
            else ("medium" if verified else "low")
        )
        findings.append(
            {
                "finding_id": f"{check_id}:{row.evidence_id}",
                "resource_ids": [row.resource_id] if row.resource_id else [],
                "check_id": check_id,
                "policy_id": check_id,
                "source_status": status,
                "status": finding_status,
                "summary": issue,
                "evidence_refs": [row.evidence_id],
                "confidence": confidence,
                "uncertainty": uncertainty,
                "stale": status == "unavailable" or degraded_freshness,
                "next_check": f"Recheck {row.evidence_id} through an allowlisted Network provider",
                "actionable": verified and not affected_by_freshness,
            }
        )
    deduplicated: list[dict[str, Any]] = []
    seen: dict[tuple[tuple[str, ...], str, str], dict[str, Any]] = {}
    for finding in findings:
        key = (
            tuple(sorted(str(value).casefold() for value in finding["resource_ids"])),
            str(finding["check_id"]).casefold(),
            " ".join(str(finding["summary"]).casefold().split()),
        )
        existing = seen.get(key)
        if existing is None:
            seen[key] = finding
            deduplicated.append(finding)
            continue
        existing["evidence_refs"] = list(
            dict.fromkeys([*existing["evidence_refs"], *finding["evidence_refs"]])
        )
    return deduplicated
