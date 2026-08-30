"""Typed, bounded page context contracts for contextual Copilot requests.

The browser is not an authority.  It submits the bounded state it rendered and
the API validates that state before any specialist is invoked.  Keeping this
contract separate from the provider models also makes a request replayable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from api.scope import Scope
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    evidence_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    resource_id: str = Field(default="", max_length=512)
    section: str = Field(min_length=1, max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "empty", "unavailable", "denied"] = "ok"
    observed_at: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def bounded_row(self) -> EvidenceRow:
        if len(json.dumps(self.data, default=str, separators=(",", ":"))) > MAX_EVIDENCE_ROW_BYTES:
            raise ValueError("evidence row exceeds size limit")
        return self


class PageSnapshot(SnapshotModel):
    """The exact page state used to answer one contextual question."""

    version: Literal["1"] = "1"
    page_kind: Literal["network", "vulnerability", "patch", "incident", "governance", "resource"]
    page_id: str = Field(min_length=1, max_length=128)
    selected_resources: list[SelectedResource] = Field(default_factory=list, max_length=MAX_SELECTED_RESOURCES)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    freshness: list[FreshnessRecord] = Field(default_factory=list, max_length=32)
    scope: ScopeAuthorization = Field(default_factory=ScopeAuthorization)
    evidence: list[EvidenceRow] = Field(default_factory=list, max_length=MAX_EVIDENCE_ROWS)
    question: str = Field(min_length=1, max_length=1024)
    rechecks: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_snapshot(self) -> PageSnapshot:
        if len(self.model_dump_json()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("page snapshot exceeds size limit")
        ids = {row.evidence_id for row in self.evidence}
        for resource in self.selected_resources:
            if resource.resource_id.startswith("http://") or resource.resource_id.startswith("https://"):
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
                    raise ValueError("snapshot scope is wider than the effective read scope")
        if not self.scope.authorized:
            raise ValueError("snapshot scope authorization is not valid")
        for resource in self.selected_resources:
            identity = _canonical_resource_attributes(resource.resource_id)
            if any(
                resource.attributes.get(dimension)
                and str(resource.attributes[dimension]).strip().casefold()
                != value
                for dimension, value in identity.items()
            ):
                raise ValueError("selected resource attributes disagree with its ID")
            if not effective.matches(identity):
                raise ValueError("selected resource is outside the effective read scope")
        for row in self.evidence:
            if not row.resource_id:
                continue
            identity = _canonical_resource_attributes(row.resource_id)
            if not effective.matches(identity):
                raise ValueError("evidence resource is outside the effective read scope")

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
        verified = status == "ok" and bool(data.get("compliant") is False or data.get("finding"))
        affected_by_freshness = degraded_freshness or status != "ok"
        finding_status = "verified" if verified else ("hypothesis" if status == "ok" else status)
        uncertainty = [] if verified else ["evidence does not prove the conclusion"]
        if affected_by_freshness and verified:
            finding_status = "hypothesis"
            uncertainty = list(freshness_uncertainty) or [
                "source status does not prove the conclusion"
            ]
        confidence = "high" if verified and not affected_by_freshness else (
            "medium" if verified else "low"
        )
        findings.append({
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
        })
    return findings
