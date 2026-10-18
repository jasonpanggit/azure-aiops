"""Personal review declarations anchored to retained server exposure observations."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from operations.exposure_history import (
    FACETS,
    ExposureHistoryStore,
    ExposureObservation,
)
from storage.onelake_documents import DocumentConflictError

Reason = Literal["source_evidence", "connection_coverage", "freshness", "classification", "sla_unknown"]
Disposition = Literal["queued", "in_review", "review_closed"]
MAX_EVENTS = 100
MAX_BYTES = 256 * 1024


def recovery_reasons(row: ExposureObservation) -> dict[str, str]:
    """Explain only recorded gaps; do not infer current state or repair success."""
    reasons = {}
    if row.completeness_state not in {"complete", "healthy-empty"} or (row.excluded_count or 0) > 0:
        reasons["source_evidence"] = f"Recorded evidence is {row.completeness_state}; excluded findings: {row.excluded_count if row.excluded_count is not None else 'unknown'}."
    if row.represented_connections is None or row.expected_connections is None or row.represented_connections != row.expected_connections:
        reasons["connection_coverage"] = f"Recorded connection coverage: {row.represented_connections if row.represented_connections is not None else 'unknown'} / {row.expected_connections if row.expected_connections is not None else 'unknown'}."
    if not row.source_observed_at or row.freshness_state not in {"reported", "current", "fresh"}:
        reasons["freshness"] = f"Recorded freshness is {row.freshness_state}; source observation time: {row.source_observed_at or 'unreported'}."
    missing = [name for name in FACETS if name not in row.facets or sum(item.count for item in row.facets[name]) < row.total_count]
    if missing:
        reasons["classification"] = f"Facet groups absent or not covering every returned finding: {', '.join(missing)}."
    sla = row.facets.get("sla_state")
    if sla is None or sum(item.count for item in sla if item.value.casefold() in {"overdue", "within_sla"}) < row.total_count:
        reasons["sla_unknown"] = "SLA classifications are absent or contain unclassified findings; do not infer compliance."
    return reasons


class RecoveryReview(BaseModel):
    """Operator-authored workflow annotations, never execution or provider evidence."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=MAX_EVENTS)
    observation_id: str = Field(pattern=r"^exo-[a-f0-9]{32}$")
    reason: Reason
    disposition: Disposition
    owner: str = Field(max_length=160)
    target_date: str = Field(max_length=10)
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def nonblank(cls, value: str) -> str:
        """Require a deliberate review explanation."""
        if not value.strip():
            raise ValueError("A review explanation is required")
        return value

    @field_validator("target_date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        """Optional explicit calendar target, not an inferred provider SLA."""
        if value and (len(value) != 10 or date.fromisoformat(value).isoformat() != value):
            raise ValueError("Review target date must use YYYY-MM-DD")
        return value


class RecoveryEvent(RecoveryReview):
    """Immutable server-attributed revision event."""

    event_id: str = Field(pattern=r"^exr-[a-f0-9]{32}$")
    recorded_at: str = Field(max_length=40)
    actor: str = Field(min_length=1)

    @field_validator("recorded_at")
    @classmethod
    def timestamp(cls, value: str) -> str:
        """Require timezone-aware event attribution."""
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Review timestamp requires a timezone")
        return value


class RecoveryState(BaseModel):
    """Bounded append-only events for the exact caller and scope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_EVENTS)
    events: list[RecoveryEvent] = Field(max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def coherent(self) -> RecoveryState:
        """Reject duplicate, missing, foreign or out-of-order event revisions."""
        if len(self.events) != self.revision or len({row.event_id for row in self.events}) != self.revision:
            raise ValueError("Recovery events do not agree with revision")
        seen = set()
        for index, row in enumerate(self.events):
            key = (row.observation_id, row.reason)
            if row.expected_revision != index or row.actor != self.actor or (key not in seen and row.disposition != "queued"):
                raise ValueError("Recovery event attribution or transition is invalid")
            seen.add(key)
        return self


class ExposureRecoveryStore:
    """Use the existing history document root; never acquire provider data."""

    def __init__(self, history: ExposureHistoryStore):
        self.history = history
        self.documents = history.documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/exposure-recovery/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bounded(payload: dict) -> None:
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("Exposure recovery exceeds its 256 KiB limit")

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists:
            self._bounded(snapshot.payload)
            state = RecoveryState.model_validate(snapshot.payload)
        else:
            state = RecoveryState(actor=actor, scope=scope, revision=0, events=[])
        if state.actor != actor or state.scope != scope:
            raise ValueError("Recovery queue identity does not agree")
        retained = self.history.read(actor, scope)
        candidates = []
        for payload in retained["observations"]:
            row = ExposureObservation.model_validate(payload)
            for reason, explanation in recovery_reasons(row).items():
                candidates.append({
                    "observation_id": row.observation_id, "reason": reason,
                    "explanation": explanation, "generation": row.generation,
                    "captured_at": row.captured_at,
                })
        keys = {(row["observation_id"], row["reason"]) for row in candidates}
        if any((event.observation_id, event.reason) not in keys for event in state.events):
            raise ValueError("Recovery event no longer matches retained evidence")
        return name, snapshot, state, candidates

    @staticmethod
    def _project(state: RecoveryState, candidates: list[dict]) -> dict:
        latest = {(event.observation_id, event.reason): event for event in state.events}
        return {
            **state.model_dump(),
            "candidates": [
                {**row, "review": latest[(row["observation_id"], row["reason"])].model_dump()
                 if (row["observation_id"], row["reason"]) in latest else None}
                for row in candidates
            ],
        }

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Read candidates and retained workflow history without live acquisition."""
        _, _, state, candidates = self._read(actor, scope)
        return self._project(state, candidates)

    def review(self, actor: str, scope: dict[str, list[str]], payload: RecoveryReview) -> dict:
        """Append one explicit revision-bound declaration, not a source correction."""
        name, snapshot, state, candidates = self._read(actor, scope)
        if state.revision != payload.expected_revision:
            raise DocumentConflictError("Recovery queue changed; reload before reviewing")
        if state.revision >= MAX_EVENTS:
            raise DocumentConflictError("Recovery queue holds 100 events; no events were evicted")
        key = (payload.observation_id, payload.reason)
        if not any((row["observation_id"], row["reason"]) == key for row in candidates):
            raise LookupError("Retained recovery candidate was not found")
        if not any((event.observation_id, event.reason) == key for event in state.events) and payload.disposition != "queued":
            raise DocumentConflictError("A recovery candidate must first be explicitly queued")
        event = RecoveryEvent(
            **payload.model_dump(), event_id=f"exr-{uuid4().hex}",
            recorded_at=datetime.now(UTC).isoformat(), actor=actor,
        )
        state = RecoveryState(actor=actor, scope=scope, revision=state.revision + 1, events=[*state.events, event])
        stored = state.model_dump()
        self._bounded(stored)
        if snapshot.exists:
            self.documents.replace_if_match(name, stored, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, stored)
        return self._project(state, candidates)
