"""Private KB maintenance-review declarations, never scheduling or execution."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_BYTES = 256 * 1024


def canonical_kb(value: str) -> str:
    """Require a canonical, bounded KB selector."""
    if not re.fullmatch(r"KB[0-9]{4,20}", value):
        raise ValueError("An exact uppercase KB identifier is required")
    return value


class KbReviewRequest(BaseModel):
    """Operator declarations tied to an expected current Silver generation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=20)
    generation: str = Field(min_length=1, max_length=256)
    owner: str = Field(min_length=1, max_length=160)
    window_start: str = Field(max_length=64)
    window_end: str = Field(max_length=64)
    dependency_kbs: list[str] = Field(max_length=20)
    disposition: Literal["needs_review", "deferred", "reviewed"]
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("owner", "note")
    @classmethod
    def nonblank(cls, value: str) -> str:
        """Reject blank review attribution."""
        if not value.strip():
            raise ValueError("Owner and review explanation must not be blank")
        return value

    @field_validator("dependency_kbs")
    @classmethod
    def dependencies(cls, values: list[str]) -> list[str]:
        """References are unique KB identities, not validated dependencies."""
        if len(set(values)) != len(values):
            raise ValueError("Dependency references must be unique")
        return [canonical_kb(value) for value in values]

    @model_validator(mode="after")
    def window(self) -> KbReviewRequest:
        """A proposed window requires two offset-aware, ordered instants."""
        start, end = datetime.fromisoformat(self.window_start), datetime.fromisoformat(self.window_end)
        if start.utcoffset() is None or end.utcoffset() is None or end <= start:
            raise ValueError("Proposed window must have time zones and end after start")
        return self


class KbReviewRecord(KbReviewRequest):
    """Server attribution and minimal source binding for one retained declaration."""

    review_id: str = Field(pattern=r"^kbr-[a-f0-9]{32}$")
    recorded_at: str
    source_observed_at: str = Field(max_length=128)
    source_completeness: str = Field(max_length=128)
    source_freshness: str = Field(max_length=128)

    @field_validator("recorded_at")
    @classmethod
    def clock(cls, value: str) -> str:
        """Retained attribution must carry a server time zone."""
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("Review clock requires a time zone")
        return value


class KbReviewHistory(BaseModel):
    """Bounded append-only history for one principal, exact scope and KB."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    actor: str = Field(min_length=1)
    scope: dict[str, list[str]]
    kb_id: str
    revision: int = Field(ge=0, le=20)
    reviews: list[KbReviewRecord] = Field(max_length=20)

    @model_validator(mode="after")
    def coherent(self) -> KbReviewHistory:
        """Reject corrupt identity, clocks or revision chains."""
        canonical_kb(self.kb_id)
        if self.revision != len(self.reviews) or len({row.review_id for row in self.reviews}) != self.revision:
            raise ValueError("KB review revision chain is inconsistent")
        if any(row.expected_revision != index or self.kb_id in row.dependency_kbs for index, row in enumerate(self.reviews)):
            raise ValueError("KB review predecessor or dependency identity is inconsistent")
        return self


class KbReviewStore:
    """Atomic review-only declarations under the existing durable document root."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]], kb_id: str) -> str:
        identity = json.dumps([actor, scope, canonical_kb(kb_id)], sort_keys=True, separators=(",", ":"))
        return f"state/kb-review/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bounded(payload: dict) -> None:
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("KB review history exceeds 256 KiB; no reviews were evicted")

    def _read(self, actor: str, scope: dict[str, list[str]], kb_id: str):
        name = self._name(actor, scope, kb_id)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists:
            self._bounded(snapshot.payload)
            history = KbReviewHistory.model_validate(snapshot.payload)
        else:
            history = KbReviewHistory(actor=actor, scope=scope, kb_id=kb_id, revision=0, reviews=[])
        if history.actor != actor or history.scope != scope or history.kb_id != kb_id:
            raise ValueError("KB review identity does not agree")
        return name, snapshot, history

    def read(self, actor: str, scope: dict[str, list[str]], kb_id: str) -> dict:
        """Read retained declarations without source acquisition."""
        return self._read(actor, scope, kb_id)[2].model_dump()

    def append(self, actor: str, scope: dict[str, list[str]], kb_id: str, request: KbReviewRequest, source: dict) -> dict:
        """Bind a declaration to server-read metadata; never accept browser evidence."""
        name, snapshot, history = self._read(actor, scope, kb_id)
        if history.revision != request.expected_revision or history.revision >= 20:
            raise DocumentConflictError("KB reviews changed or reached 20 records; reload. No reviews were evicted")
        if kb_id in request.dependency_kbs:
            raise ValueError("An update cannot reference itself as a dependency")
        detail = source["data"]
        if source["scope"] != scope or detail["kb_id"] != kb_id:
            raise ValueError("KB review source identity does not agree")
        if detail["generation"] != request.generation:
            raise DocumentConflictError("Latest KB snapshot changed; refresh metadata before reviewing")
        state = detail["snapshot"]
        record = KbReviewRecord(
            **request.model_dump(), review_id=f"kbr-{uuid4().hex}", recorded_at=datetime.now(UTC).isoformat(),
            source_observed_at=state["as_of"], source_completeness=state["completeness"], source_freshness=state["freshness"],
        )
        stored = KbReviewHistory(
            actor=actor, scope=scope, kb_id=kb_id, revision=history.revision + 1, reviews=[*history.reviews, record],
        ).model_dump()
        self._bounded(stored)
        if snapshot.exists:
            self.documents.replace_if_match(name, stored, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, stored)
        return stored
