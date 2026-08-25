from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FreshnessBand = Literal["fresh", "aging", "stale", "unknown"]
Availability = Literal["available", "degraded", "unavailable", "unknown"]
IngestionStatus = Literal["succeeded", "partial", "failed", "unavailable", "unknown"]
Quality = Literal["complete", "incomplete", "contradictory", "degraded", "unknown"]


class SituationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    situation_id: str
    resource_id: str
    title: str
    situation_type: str
    lifecycle_state: str = "open"
    severity: str = "medium"
    priority: str = "P3"
    scope: dict[str, list[str]] = Field(default_factory=dict)
    owner: str = ""
    support_team: str = ""
    affected_resource_ids: list[str] = Field(default_factory=list)
    linked_evidence_ids: list[str] = Field(default_factory=list)
    started_at: str
    last_observed_at: str
    evidence_state: Quality = "unknown"
    warnings: list[str] = Field(default_factory=list)
    contradiction_ids: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    run_id: str = ""

    @field_validator("situation_id", "resource_id", "title", "situation_type", "started_at", "last_observed_at")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("situation identity and timestamps are required")
        return value

    @field_validator("affected_resource_ids", "linked_evidence_ids", "warnings", "contradiction_ids", "unknowns")
    @classmethod
    def clean_lists(cls, value: list[str]) -> list[str]:
        return sorted({str(item).strip() for item in value if str(item).strip()})

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


# Public domain name used by the materializer and API; the explicit suffix
# keeps the Pydantic DTO naming convention available to callers as well.
Situation = SituationModel


class EvidenceRecord(BaseModel):
    """The common, compact evidence envelope; raw provider payloads are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    source_family: str
    source_object_id: str
    locator: str = ""
    resource_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    observed_at: str
    ingested_at: str
    watermark: str = ""
    ingestion_status: IngestionStatus = "succeeded"
    provenance: dict[str, Any] = Field(default_factory=dict)
    freshness: FreshnessBand = "unknown"
    quality: Quality = "unknown"
    availability: Availability = "available"
    confidence: str = "unknown"
    assertion: str = ""
    fingerprint: str
    situation_id: str = ""
    run_id: str = ""

    @field_validator("resource_ids", "entity_ids")
    @classmethod
    def clean_ids(cls, value: list[str]) -> list[str]:
        return sorted({str(item).strip().casefold() for item in value if str(item).strip()})

    @field_validator("evidence_id", "source_family", "source_object_id", "observed_at", "ingested_at", "fingerprint")
    @classmethod
    def required_evidence_text(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("evidence identity and timestamps are required")
        return value

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class SituationLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    link_id: str
    situation_id: str
    entity_type: str
    entity_id: str
    relation: str
    quality: Literal["resolved", "unresolved", "degraded"] = "resolved"
    provenance: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_family: str
    run_id: str
    status: IngestionStatus
    observed_at: str = ""
    ingested_at: str = ""
    watermark: str = ""
    query_version: str = ""
    requested_scope: dict[str, list[str]] = Field(default_factory=dict)
    provider_status: str = ""
    freshness: FreshnessBand = "unknown"
    availability: Availability = "unknown"
    quality: Quality = "unknown"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    actor: str
    action: str
    scope_snapshot: dict[str, list[str]] = Field(default_factory=dict)
    timestamp: str
    situation_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    run_id: str = ""

    @field_validator("event_id", "actor", "action", "timestamp")
    @classmethod
    def required_audit_text(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("audit event identity, actor, action, and timestamp are required")
        return value

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def stable_id(prefix: str, *parts: object) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}://{hashlib.sha256(canonical.encode()).hexdigest()[:32]}"
