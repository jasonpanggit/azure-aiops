"""Scope-exact handover annotations; never provider facts or execution authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore


class NoteAppend(BaseModel):
    """Append one operator annotation against a reviewed revision and evidence run."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    evidence_run_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=2000)


class HandoverNote(BaseModel):
    """Immutable, server-attributed annotation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    note_id: str
    revision: int = Field(ge=1)
    evidence_run_id: str
    text: str
    actor: str
    created_at: str


class SituationNotesState(BaseModel):
    """An exact-scope append-only annotation history with bounded retention."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    situation_id: str
    scope: dict[str, list[str]]
    revision: int = Field(ge=0)
    notes: list[HandoverNote] = Field(max_length=200)


class SituationNotesStore:
    """Persist annotation histories with local/OneLake compare-and-swap parity."""

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        self.documents = documents

    @staticmethod
    def _name(situation_id: str, scope: dict[str, list[str]]) -> str:
        key = json.dumps([situation_id, scope], sort_keys=True, separators=(",", ":")).encode()
        return f"state/situation-notes/{hashlib.sha256(key).hexdigest()}.json"

    @staticmethod
    def _state(payload: dict[str, Any], situation_id: str, scope: dict[str, list[str]]) -> SituationNotesState:
        try:
            state = SituationNotesState.model_validate(payload)
        except ValidationError as exc:
            raise RuntimeError("Stored Situation handover history is invalid") from exc
        if state.situation_id != situation_id or state.scope != scope or state.revision != len(state.notes):
            raise RuntimeError("Stored Situation handover identity or revision is invalid")
        if any(note.revision != index for index, note in enumerate(state.notes, 1)):
            raise RuntimeError("Stored Situation handover revision sequence is invalid")
        return state

    def read(self, situation_id: str, scope: dict[str, list[str]]) -> dict[str, Any]:
        """Read only this exact Situation and scope; corrupt state never resets."""
        snapshot = self.documents.read_snapshot(self._name(situation_id, scope))
        return (
            self._state(snapshot.payload, situation_id, scope)
            if snapshot.exists else SituationNotesState(situation_id=situation_id, scope=scope, revision=0, notes=[])
        ).model_dump()

    def append(self, situation_id: str, scope: dict[str, list[str]], change: NoteAppend, actor: str) -> dict[str, Any]:
        """Append atomically; stale revisions or full histories require explicit recovery."""
        name = self._name(situation_id, scope)
        snapshot = self.documents.read_snapshot(name)
        state = (
            self._state(snapshot.payload, situation_id, scope)
            if snapshot.exists else SituationNotesState(situation_id=situation_id, scope=scope, revision=0, notes=[])
        )
        if state.revision != change.expected_revision:
            raise DocumentConflictError("Handover notes changed; reload before appending")
        if len(state.notes) >= 200:
            raise ValueError("Handover history reached 200 entries; administrative archival is required")
        state.revision += 1
        state.notes.append(HandoverNote(
            note_id=str(uuid4()), revision=state.revision, evidence_run_id=change.evidence_run_id,
            text=change.text, actor=actor, created_at=datetime.now(UTC).isoformat(),
        ))
        payload = state.model_dump()
        if snapshot.exists:
            self.documents.replace_if_match(name, payload, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, payload)
        return payload
