"""Personal navigation preferences, never saved evidence or authorization."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_VIEWS = 20
MAX_BYTES = 64 * 1024
MAX_INT = 9_007_199_254_740_991


class ViewIdentity(BaseModel):
    """Stable personal view identity and a display label, not a destination URL."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    view_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=80)


class SearchView(ViewIdentity):
    """Only supported Search query and facet settings; always restore the first page."""

    kind: Literal["search"]
    query: str = Field(min_length=1, max_length=512)
    entity_type: str = Field(default="", max_length=128)
    source: str = Field(default="", max_length=256)


class SituationView(ViewIdentity):
    """Queue filters, not incident mutation, SLA declarations or handoff selections."""

    kind: Literal["situations"]
    query: str = Field(default="", max_length=256)
    priority: Literal["all", "P1", "P2", "P3"] = "all"
    assigned_owner: str = Field(default="", max_length=256)
    lifecycle_state: str = Field(default="", max_length=64)
    older_than_hours: Literal[24, 168, 720] | None = None
    sort: Literal["default", "oldest", "newest"] = "default"
    response_deadline: Literal["", "due", "overdue", "unknown", "closed"] = ""

    @field_validator("older_than_hours", mode="before")
    @classmethod
    def integer_age(cls, value: object) -> object:
        """Prevent numeric Literal equality from silently coercing a float."""
        if value is not None and not isinstance(value, int):
            raise ValueError("Observed age must be an integer preset or null")
        return value


SavedView = Annotated[SearchView | SituationView, Field(discriminator="kind")]


class ViewUpdate(BaseModel):
    """Replace the full reviewed collection, including explicit removal."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=MAX_INT - 1)
    views: list[SavedView] = Field(max_length=MAX_VIEWS)

    @model_validator(mode="after")
    def unique_views(self):
        """Reject duplicate identities instead of ambiguously restoring a view."""
        if len({view.view_id for view in self.views}) != len(self.views):
            raise ValueError("Saved view identities must be unique")
        return self


class ViewCollection(BaseModel):
    """Strict exact-principal/effective-scope state with server-issued revision/time."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(ge=1, le=1)
    actor: str
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_INT)
    updated_at: str = Field(max_length=40)
    views: list[SavedView] = Field(max_length=MAX_VIEWS)

    @model_validator(mode="after")
    def coherent_collection(self):
        """Validate identities and distinguish unsaved state from a saved empty list."""
        if len({view.view_id for view in self.views}) != len(self.views):
            raise ValueError("Saved view identities must be unique")
        if self.revision == 0:
            if self.views or self.updated_at:
                raise ValueError("Unsaved view collection must be empty")
        elif not self.updated_at or datetime.fromisoformat(self.updated_at).tzinfo is None:
            raise ValueError("Saved view collection requires an aware update time")
        return self


class SavedViewStore:
    """Persist personal navigation preferences using existing local/OneLake CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/saved-views/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    @staticmethod
    def _bytes(payload: dict) -> int:
        return len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists and self._bytes(snapshot.payload) > MAX_BYTES:
            raise RuntimeError("Stored saved views exceed their document limit")
        try:
            state = (
                ViewCollection.model_validate(snapshot.payload)
                if snapshot.exists
                else ViewCollection(
                    schema_version=1, actor=actor, scope=scope,
                    revision=0, updated_at="", views=[],
                )
            )
        except ValidationError as exc:
            raise RuntimeError("Stored saved views schema is invalid") from exc
        if (state.actor, state.scope) != (actor, scope):
            raise RuntimeError("Stored saved views identity is invalid")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Recover only the caller's exact-scope preferences without source providers."""
        return self._read(actor, scope)[2].model_dump()

    def replace(self, actor: str, scope: dict[str, list[str]], update: ViewUpdate) -> dict:
        """Replace all views only if the document and reviewed revision still match."""
        name, snapshot, state = self._read(actor, scope)
        if state.revision != update.expected_revision:
            raise DocumentConflictError("Saved views changed; reload before continuing")
        updated = ViewCollection(
            schema_version=1, actor=actor, scope=scope,
            revision=state.revision + 1, updated_at=datetime.now(UTC).isoformat(),
            views=update.views,
        ).model_dump()
        if self._bytes(updated) > MAX_BYTES:
            raise ValueError("Saved views exceed the 64 KiB document limit")
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated
