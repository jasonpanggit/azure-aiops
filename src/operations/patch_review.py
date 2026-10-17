"""Immutable personal patch-review batches, not executable remediation plans."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_BYTES = 256 * 1024


class PatchReviewFilters(BaseModel):
    """Allowlisted query selectors resolved again under current API authorization."""

    model_config = ConfigDict(extra="forbid", strict=True)
    severity: str | None = Field(default=None, max_length=128)
    target_kind: Literal["server", "container_image"] | None = None
    source_family: str | None = Field(default=None, max_length=128)
    current_state: str | None = Field(default=None, max_length=128)
    sla_state: str | None = Field(default=None, max_length=128)
    completeness: str | None = Field(default=None, max_length=128)
    active: bool | None = None
    sla_overdue: bool | None = None
    weakness_id: str | None = Field(default=None, max_length=256)
    search: str | None = Field(default=None, max_length=256)


class CreatePatchReview(BaseModel):
    """Browser supplies identities/query position, never source counts or rows."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=20)
    generation: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:-]+$")
    cursor: str | None = Field(default=None, max_length=8192)
    page_size: int = Field(ge=1, le=100)
    sort_by: Literal["priority_score", "severity", "target_id", "weakness_id"] = "priority_score"
    sort_direction: Literal["asc", "desc"] = "desc"
    filters: PatchReviewFilters
    exposure_ids: list[str] = Field(min_length=1, max_length=25)
    owner: str = Field(max_length=160)
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def nonblank(cls, value: str) -> str:
        """Require deliberate review context."""
        if not value.strip():
            raise ValueError("A review explanation is required")
        return value

    @field_validator("exposure_ids")
    @classmethod
    def identities(cls, values: list[str]) -> list[str]:
        """Reject ambiguous, empty or unbounded selections."""
        if len(set(values)) != len(values) or any(not value.strip() or len(value) > 1024 for value in values):
            raise ValueError("Review selections must have unique bounded identities")
        return values


class PatchReviewFinding(BaseModel):
    """Allowlisted server-read projection, without execution payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)
    exposure_id: str = Field(min_length=1, max_length=1024)
    target_id: str = Field(min_length=1, max_length=2048)
    weakness_id: str = Field(min_length=1, max_length=256)
    target_kind: Literal["server", "container_image"]
    severity: str = Field(max_length=128)
    completeness: str = Field(max_length=128)
    sla_state: str = Field(max_length=128)


class PatchReviewBatch(BaseModel):
    """Server-attributed snapshot; owner and note remain operator declarations."""

    model_config = ConfigDict(extra="forbid", strict=True)
    batch_id: str = Field(pattern=r"^prb-[a-f0-9]{32}$")
    captured_at: str
    generation: str = Field(min_length=1, max_length=256)
    owner: str = Field(max_length=160)
    note: str = Field(min_length=1, max_length=1000)
    findings: list[PatchReviewFinding] = Field(min_length=1, max_length=25)
    source_observed_at: str
    source_completeness: str

    @model_validator(mode="after")
    def coherent(self) -> PatchReviewBatch:
        """Validate server clock and immutable selection identities."""
        if datetime.fromisoformat(self.captured_at).tzinfo is None or not self.note.strip():
            raise ValueError("Invalid patch review capture attribution")
        ids = [row.exposure_id for row in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate patch review findings")
        return self


class PatchReviewHistory(BaseModel):
    """One exact-principal/scope bounded append-only batch history."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=20)
    batches: list[PatchReviewBatch] = Field(max_length=20)

    @model_validator(mode="after")
    def coherent(self) -> PatchReviewHistory:
        """Reject missing or duplicated persisted revisions."""
        if self.revision != len(self.batches) or len({row.batch_id for row in self.batches}) != self.revision:
            raise ValueError("Patch review history revision does not agree")
        return self


class PatchReviewStore:
    """Atomic private review snapshots using the existing durable document root."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/patch-review/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bounded(payload: dict) -> None:
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("Patch review history exceeds 256 KiB")

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists:
            self._bounded(snapshot.payload)
            history = PatchReviewHistory.model_validate(snapshot.payload)
        else:
            history = PatchReviewHistory(actor=actor, scope=scope, revision=0, batches=[])
        if history.actor != actor or history.scope != scope:
            raise ValueError("Patch review history identity does not agree")
        return name, snapshot, history

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Read saved batches without refreshing findings or dispatching providers."""
        return self._read(actor, scope)[2].model_dump()

    def append(self, actor: str, scope: dict[str, list[str]], request: CreatePatchReview, page: dict) -> dict:
        """Retain only selected rows reacquired by the authorized server query."""
        name, snapshot, history = self._read(actor, scope)
        if history.revision != request.expected_revision or history.revision >= 20:
            raise DocumentConflictError("Patch review history changed or reached 20 batches; reload. No batches were evicted")
        if page["scope"] != scope or page["generation"] != request.generation:
            raise ValueError("Patch review source scope or generation changed")
        by_id = {row["exposure_id"]: row for row in page["items"]}
        if len(by_id) != len(page["items"]) or not set(request.exposure_ids).issubset(by_id):
            raise DocumentConflictError("Selected findings no longer match the reviewed query page")
        findings = []
        for identity in request.exposure_ids:
            row = by_id[identity]
            if row.get("read_model_generation_id") not in {None, request.generation}:
                raise ValueError("Patch review finding generation changed")
            findings.append(PatchReviewFinding(
                exposure_id=identity, target_id=row["target_id"], weakness_id=row["weakness_id"], target_kind=row["target_kind"],
                severity=row.get("severity") or "unknown", completeness=row.get("completeness") or "unknown",
                sla_state=row.get("sla_state") or "unknown",
            ))
        batch = PatchReviewBatch(
            batch_id=f"prb-{uuid4().hex}", captured_at=datetime.now(UTC).isoformat(), generation=request.generation,
            owner=request.owner, note=request.note, findings=findings,
            source_observed_at=page["freshness"].get("as_of") or "", source_completeness=page["completeness"]["state"],
        )
        stored = PatchReviewHistory(actor=actor, scope=scope, revision=history.revision + 1, batches=[*history.batches, batch]).model_dump()
        self._bounded(stored)
        if snapshot.exists:
            self.documents.replace_if_match(name, stored, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, stored)
        return stored
