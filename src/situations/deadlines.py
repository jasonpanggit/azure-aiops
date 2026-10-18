"""Explicit response-review commitments; never inferred contractual SLA compliance."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_INT = 9_007_199_254_740_991
MAX_BYTES = 512 * 1024


def aware(value: str) -> datetime:
    """Require an explicit timezone instead of assuming the server's local zone."""
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Response deadline must include a timezone")
    try:
        return result.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("Response deadline is outside the supported UTC range") from exc


class DeadlineChange(BaseModel):
    """Set/clear one declared deadline at a reviewed scope revision and evidence run."""

    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0, lt=MAX_INT)
    evidence_run_id: str = Field(min_length=1, max_length=256)
    due_at: str | None = Field(max_length=40)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("due_at")
    @classmethod
    def valid_time(cls, value):
        """Null explicitly clears; non-null values must be aware ISO timestamps."""
        if value is not None:
            aware(value)
        return value


class DeclaredDeadline(BaseModel):
    """Last attributed declaration for one evidence run, not a response-completed event."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    situation_id: str = Field(min_length=1, max_length=2048)
    evidence_run_id: str = Field(min_length=1, max_length=256)
    due_at: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=1000)
    actor: str = Field(min_length=1, max_length=4096)
    declared_at: str = Field(min_length=1, max_length=40)
    revision: int = Field(ge=1, le=MAX_INT)

    @model_validator(mode="after")
    def timestamps(self):
        """Reject naive/malformed declarations at recovery as well as write time."""
        aware(self.due_at); aware(self.declared_at)
        return self


class DeadlineState(BaseModel):
    """Bounded exact-scope collection without silent eviction or inherited policy."""

    model_config = ConfigDict(strict=True, extra="forbid")
    schema_version: int = Field(ge=1, le=1)
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_INT)
    updated_at: str = Field(max_length=40)
    updated_by: str = Field(max_length=4096)
    declarations: list[DeclaredDeadline] = Field(max_length=200)

    @model_validator(mode="after")
    def coherence(self):
        """Reject impossible versions, identity ambiguity and actual serialized overflow."""
        if len({row.situation_id for row in self.declarations}) != len(self.declarations):
            raise ValueError("Response deadline identities must be unique")
        if any(row.revision > self.revision for row in self.declarations):
            raise ValueError("Response deadline exceeds collection revision")
        if not self.revision:
            if self.declarations or self.updated_at or self.updated_by:
                raise ValueError("Unsaved response deadline collection must be empty")
        else:
            aware(self.updated_at)
            if not self.updated_by.strip():
                raise ValueError("Response deadline editor is required")
        if len((json.dumps(self.model_dump(), indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("Response deadlines exceed 512 KiB; explicitly remove declarations")
        return self


class SituationDeadlineStore:
    """Share explicit case commitments only within one exact authorized effective scope."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(scope: dict) -> str:
        digest = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return f"state/situation-deadlines/{digest}.json"

    def _read(self, scope: dict):
        name = self._name(scope)
        try:
            snapshot = self.documents.read_snapshot(name)
            state = DeadlineState.model_validate(snapshot.payload) if snapshot.exists else DeadlineState(
                schema_version=1, scope=scope, revision=0, updated_at="", updated_by="", declarations=[],
            )
        except (ValueError, ValidationError, TypeError, RecursionError) as exc:
            raise RuntimeError("Stored response deadlines could not be confirmed") from exc
        if state.scope != scope:
            raise RuntimeError("Stored response deadline scope is invalid")
        return name, snapshot, state

    def read(self, scope: dict) -> DeadlineState:
        """Recover strict declarations without silently replacing corrupt state."""
        return self._read(scope)[2]

    def change(self, scope: dict, situation_id: str, actor: str, change: DeadlineChange) -> DeadlineState:
        """Atomically replace/remove one run-bound declaration at the reviewed revision."""
        name, snapshot, state = self._read(scope)
        if state.revision != change.expected_revision or state.revision >= MAX_INT:
            raise DocumentConflictError("Response deadlines changed; reload before retrying")
        rows = [row for row in state.declarations if row.situation_id != situation_id]
        if change.due_at is None and len(rows) == len(state.declarations):
            raise KeyError("No declared response deadline")
        now = datetime.now(UTC).isoformat()
        if change.due_at is not None:
            rows.append(DeclaredDeadline(
                situation_id=situation_id, evidence_run_id=change.evidence_run_id,
                due_at=aware(change.due_at).isoformat(), reason=change.reason, actor=actor,
                declared_at=now, revision=state.revision + 1,
            ))
        if len(rows) > 200:
            raise ValueError("At most 200 response deadlines; explicitly remove a declaration")
        updated = DeadlineState(
            schema_version=1, scope=scope, revision=state.revision + 1,
            updated_at=now, updated_by=actor, declarations=sorted(rows, key=lambda row: row.situation_id),
        )
        payload = updated.model_dump()
        if snapshot.exists:
            self.documents.replace_if_match(name, payload, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, payload)
        return updated


def project_deadline(row: dict, state: DeadlineState | None, now: datetime) -> dict:
    """Report due/overdue only for a matching run in a known active lifecycle."""
    declaration = next((item for item in state.declarations if item.situation_id == row["situation_id"]), None) if state else None
    status = "unknown"
    reason = "No declared response deadline in this exact scope" if state else "Response deadline storage is unavailable"
    if declaration:
        lifecycle = str(row.get("lifecycle_state") or "").casefold()
        if declaration.evidence_run_id != row.get("run_id"):
            reason = "Evidence run changed; explicitly review and replace the declaration"
        elif lifecycle in {"closed", "resolved"}:
            status, reason = "closed", "Closed source state; response completion and historical attainment are unverified"
        elif lifecycle in {"open", "active", "new", "investigating", "acknowledged", "triaged"}:
            status = "overdue" if now >= aware(declaration.due_at) else "due"
            reason = "Current time compared with an administrator-declared response-review deadline"
        else:
            reason = "Unknown lifecycle semantics; no overdue or attainment claim"
    return {
        "state": status, "reason": reason, "evaluated_at": now.isoformat(),
        "policy_revision": state.revision if state else None,
        "declaration": declaration.model_dump() if declaration else None,
        "authority": "none", "interpretation": "Declared response-review commitment, not contractual SLA, response completion or execution approval.",
    }
