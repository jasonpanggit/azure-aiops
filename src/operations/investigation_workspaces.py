"""Revisioned team navigation workspaces, never retained provider evidence."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_REVISIONS = 40
MAX_BYTES = 256 * 1024
WORKSPACE_ID = r"^wrk-[0-9a-f]{32}$"
Subject = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00-\x1f\x7f]+$")]


class WorkspaceView(BaseModel):
    """Navigation settings only; restoring them must reacquire current evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    entry_type: Literal[
        "BusinessService", "Application", "Environment", "SubscriptionConnection",
        "Incident", "CVE", "NetworkGap", "RemediationPlan",
    ]
    subject: str = Field(max_length=512, pattern=r"^[^\x00\r\n]*$")
    mode: Literal["executive", "engineer"]


class WorkspaceCreate(BaseModel):
    """A caller-known create-only identity permits inspection after a lost reply."""

    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: str = Field(pattern=WORKSPACE_ID)
    view: WorkspaceView


class WorkspaceUpdate(BaseModel):
    """Replace only the navigation settings against the reviewed latest revision."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1, le=MAX_REVISIONS)
    view: WorkspaceView


class WorkspaceAccess(BaseModel):
    """Owner-reviewed explicit principal memberships, not platform permission grants."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    expected_revision: int = Field(ge=1, le=MAX_REVISIONS)
    readers: list[Subject] = Field(max_length=20)
    editors: list[Subject] = Field(max_length=20)

    @model_validator(mode="after")
    def distinct_memberships(self):
        """Reject duplicate or overlapping identities instead of resolving precedence."""
        if len(set(self.readers + self.editors)) != len(self.readers) + len(self.editors):
            raise ValueError("Workspace readers and editors must be distinct")
        return self


class WorkspaceRevision(BaseModel):
    """Immutable server-attributed navigation and membership revision."""

    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1, le=MAX_REVISIONS)
    actor: Subject
    recorded_at: str
    change: Literal["created", "view_updated", "access_updated"]
    view: WorkspaceView
    readers: list[Subject] = Field(max_length=20)
    editors: list[Subject] = Field(max_length=20)

    @model_validator(mode="after")
    def valid_metadata(self):
        """Stored timestamps and memberships must remain valid on every read."""
        if datetime.fromisoformat(self.recorded_at).tzinfo is None:
            raise ValueError("Workspace revision time must be timezone-aware")
        WorkspaceAccess(expected_revision=self.revision, readers=self.readers, editors=self.editors)
        return self


class WorkspaceState(BaseModel):
    """One CAS document contains a complete bounded immutable revision sequence."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    workspace_id: str = Field(pattern=WORKSPACE_ID)
    owner: Subject
    scope: dict[str, list[str]]
    revisions: list[WorkspaceRevision] = Field(min_length=1, max_length=MAX_REVISIONS)

    @model_validator(mode="after")
    def coherent_history(self):
        """Fail closed on corrupt revision, ownership, change or timestamp history."""
        previous: WorkspaceRevision | None = None
        for index, revision in enumerate(self.revisions, 1):
            if revision.revision != index or self.owner in revision.readers + revision.editors:
                raise ValueError("Workspace revision sequence or ownership is invalid")
            if previous is None:
                if (
                    revision.actor != self.owner or revision.change != "created"
                    or revision.readers or revision.editors
                ):
                    raise ValueError("Workspace creation attribution is invalid")
            else:
                if datetime.fromisoformat(revision.recorded_at) < datetime.fromisoformat(previous.recorded_at):
                    raise ValueError("Workspace revision times are out of order")
                if revision.change == "access_updated":
                    if revision.actor != self.owner or revision.view != previous.view:
                        raise ValueError("Workspace access change attribution is invalid")
                elif revision.change == "view_updated":
                    if (
                        revision.actor not in [self.owner, *previous.editors]
                        or revision.readers != previous.readers or revision.editors != previous.editors
                    ):
                        raise ValueError("Workspace view change attribution is invalid")
                else:
                    raise ValueError("Only the first workspace revision can be creation")
            previous = revision
        return self


class WorkspaceNotFoundError(LookupError):
    """Missing, unshared, inaccessible-scope and unavailable-revision identities."""


class WorkspacePermissionError(PermissionError):
    """An authorized member lacks the requested workspace editing permission."""


class InvestigationWorkspaceStore:
    """Persist exact-scope team navigation revisions with local/OneLake CAS parity."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(workspace_id: str) -> str:
        if not re.fullmatch(WORKSPACE_ID, workspace_id):
            raise ValueError("Workspace identity is invalid")
        return f"state/investigation-workspaces/{workspace_id}.json"

    @staticmethod
    def _bounded(payload: dict) -> None:
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_BYTES:
            raise ValueError("Workspace reached the 256 KiB retention limit; administrative archival is required")

    def _read(self, workspace_id: str, actor: str, scope: dict[str, list[str]]):
        snapshot = self.documents.read_snapshot(self._name(workspace_id))
        if not snapshot.exists:
            raise WorkspaceNotFoundError("Workspace unavailable")
        try:
            self._bounded(snapshot.payload)
            state = WorkspaceState.model_validate(snapshot.payload)
        except ValueError as exc:
            raise RuntimeError("Stored investigation workspace is invalid") from exc
        if state.workspace_id != workspace_id:
            raise RuntimeError("Stored investigation workspace identity is invalid")
        latest = state.revisions[-1]
        if state.scope != scope or actor not in [state.owner, *latest.readers, *latest.editors]:
            raise WorkspaceNotFoundError("Workspace unavailable")
        return snapshot, state

    @staticmethod
    def _present(state: WorkspaceState, actor: str, revision: int | None = None) -> dict:
        latest = state.revisions[-1]
        selected = revision if revision is not None else latest.revision
        if not 1 <= selected <= latest.revision:
            raise WorkspaceNotFoundError("Workspace unavailable")
        return {
            "workspace_id": state.workspace_id, "owner": state.owner, "scope": state.scope,
            "latest_revision": latest.revision,
            "revision": state.revisions[selected - 1].model_dump(),
            "current_access": {"readers": latest.readers, "editors": latest.editors},
            "can_edit": actor in [state.owner, *latest.editors], "can_share": actor == state.owner,
            "history": [
                row.model_dump(include={"revision", "actor", "recorded_at", "change"})
                for row in state.revisions
            ],
        }

    def read(self, workspace_id: str, actor: str, scope: dict[str, list[str]], revision: int | None = None) -> dict:
        """Authorize against current membership and exact scope before any historical read."""
        return self._present(self._read(workspace_id, actor, scope)[1], actor, revision)

    def create(self, actor: str, scope: dict[str, list[str]], change: WorkspaceCreate) -> dict:
        """Create privately once; repeating an identity never overwrites its owner or scope."""
        state = WorkspaceState(
            workspace_id=change.workspace_id, owner=actor, scope=scope,
            revisions=[WorkspaceRevision(
                revision=1, actor=actor, recorded_at=datetime.now(UTC).isoformat(),
                change="created", view=change.view, readers=[], editors=[],
            )],
        )
        payload = state.model_dump()
        self._bounded(payload)
        self.documents.create_only(self._name(change.workspace_id), payload)
        return self._present(state, actor)

    def _append(self, snapshot, state: WorkspaceState, actor: str, expected_revision: int, changes: dict) -> dict:
        latest = state.revisions[-1]
        if latest.revision != expected_revision:
            raise DocumentConflictError("Workspace changed; reload the latest revision before saving")
        if len(state.revisions) >= MAX_REVISIONS:
            raise ValueError("Workspace reached 40 revisions; administrative archival is required")
        row = WorkspaceRevision.model_validate({
            **latest.model_dump(), **changes, "revision": latest.revision + 1,
            "actor": actor, "recorded_at": datetime.now(UTC).isoformat(),
        })
        updated = WorkspaceState.model_validate({
            **state.model_dump(), "revisions": [*state.revisions, row],
        })
        payload = updated.model_dump()
        self._bounded(payload)
        self.documents.replace_if_match(self._name(state.workspace_id), payload, expected_etag=snapshot.etag)
        return self._present(updated, actor)

    def replace(self, workspace_id: str, actor: str, scope: dict[str, list[str]], change: WorkspaceUpdate) -> dict:
        """Owners/editors may append a view revision but cannot edit membership."""
        snapshot, state = self._read(workspace_id, actor, scope)
        if actor not in [state.owner, *state.revisions[-1].editors]:
            raise WorkspacePermissionError("Workspace view editing requires its owner or an explicit editor")
        return self._append(snapshot, state, actor, change.expected_revision, {
            "change": "view_updated", "view": change.view.model_dump(),
        })

    def share(self, workspace_id: str, actor: str, scope: dict[str, list[str]], change: WorkspaceAccess) -> dict:
        """Only the immutable owner may replace memberships; revocation covers history."""
        snapshot, state = self._read(workspace_id, actor, scope)
        if actor != state.owner:
            raise WorkspacePermissionError("Only the workspace owner may change membership")
        if state.owner in change.readers + change.editors:
            raise ValueError("The workspace owner is implicit and must not be listed as a member")
        return self._append(snapshot, state, actor, change.expected_revision, {
            "change": "access_updated", "readers": change.readers, "editors": change.editors,
        })
