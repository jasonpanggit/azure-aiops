"""Revisioned team navigation, operator annotations and immutable source-receipt links."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from operations.investigation_evidence import (
    CAPTURE_ID,
    MAX_CAPTURE_BYTES,
    CapturedSource,
    evidence_tools,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_REVISIONS = 40
MAX_BYTES = 256 * 1024
WORKSPACE_ID = r"^wrk-[0-9a-f]{32}$"
HYPOTHESIS_ID = r"^hyp-[0-9a-f]{32}$"
Subject = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00-\x1f\x7f]+$")]
EntryType = Literal[
    "BusinessService", "Application", "Environment", "SubscriptionConnection",
    "Incident", "CVE", "NetworkGap", "RemediationPlan",
]


class WorkspaceView(BaseModel):
    """Navigation settings only; restoring them must reacquire current evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    entry_type: EntryType
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


class HypothesisReference(BaseModel):
    """Operator-declared reference text, never dereferenced or treated as verified evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    source: str = Field(min_length=1, max_length=128)
    reference: str = Field(min_length=1, max_length=512)
    declared_version: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=512)


class HypothesisDraft(BaseModel):
    """Visible operator explanations and disposition, not hidden model reasoning."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    explanation: str = Field(min_length=1, max_length=2000)
    supporting: list[HypothesisReference] = Field(default_factory=list, max_length=6)
    contradicting: list[HypothesisReference] = Field(default_factory=list, max_length=6)
    unknowns: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(default_factory=list, max_length=8)
    disposition: Literal["proposed", "investigating", "supported", "contradicted", "inconclusive", "dismissed"] = "proposed"
    rationale: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def disposition_context(self):
        """A disposition beyond proposal needs the operator's explicit rationale."""
        if self.disposition != "proposed" and not self.rationale:
            raise ValueError("A non-proposed hypothesis disposition requires an operator rationale")
        return self


class HypothesisUpdate(BaseModel):
    """One explicit annotation change against the reviewed latest workspace revision."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1, le=MAX_REVISIONS)
    hypothesis: HypothesisDraft


class WorkspaceHypothesis(HypothesisDraft):
    """Server-attributed annotation with an immutable original saved-subject anchor."""

    hypothesis_id: str = Field(pattern=HYPOTHESIS_ID)
    entry_type: EntryType
    subject: str = Field(max_length=512)
    created_revision: int = Field(ge=2, le=MAX_REVISIONS)
    updated_revision: int = Field(ge=2, le=MAX_REVISIONS)
    actor: Subject
    recorded_at: str


class EvidenceCaptureRequest(BaseModel):
    """A browser-known receipt identity and reviewed latest workspace revision only."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1, le=MAX_REVISIONS)
    capture_id: str = Field(pattern=CAPTURE_ID)


class EvidenceCompareRequest(BaseModel):
    """Explicit read-only current acquisition against a reviewed retained workspace version."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1, le=MAX_REVISIONS)
    reviewed_revision: int = Field(ge=1, le=MAX_REVISIONS)


class InvestigationCapture(BaseModel):
    """Immutable, server-acquired source projections, bound to one workspace/view/scope."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    contract: Literal["investigation-tools-v1"] = "investigation-tools-v1"
    workspace_id: str = Field(pattern=WORKSPACE_ID)
    capture_id: str = Field(pattern=CAPTURE_ID)
    scope: dict[str, list[str]]
    actor: Subject
    recorded_at: str
    workspace_revision: int = Field(ge=2, le=MAX_REVISIONS)
    view: WorkspaceView
    sources: list[CapturedSource] = Field(min_length=5, max_length=8)

    @model_validator(mode="after")
    def valid_sources(self):
        """Pin the capture contract and retain source clocks without recomputing freshness."""
        recorded = datetime.fromisoformat(self.recorded_at)
        if recorded.tzinfo is None:
            raise ValueError("Capture time must be timezone-aware")
        if [row.tool for row in self.sources] != [name for name, _ in evidence_tools(self.view.entry_type, self.view.subject)]:
            raise ValueError("Capture sources differ from the saved-view projection contract")
        if any(datetime.fromisoformat(row.finished_at) > recorded for row in self.sources):
            raise ValueError("Capture cannot predate source collection")
        return self


class EvidenceCaptureReference(BaseModel):
    """CAS-linked immutable receipt digest; an unlinked receipt is never readable."""

    model_config = ConfigDict(extra="forbid", strict=True)
    capture_id: str = Field(pattern=CAPTURE_ID)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_revision: int = Field(ge=2, le=MAX_REVISIONS)
    actor: Subject
    recorded_at: str


class WorkspaceRevision(BaseModel):
    """Immutable server-attributed navigation, annotation, membership and receipt-link revision."""

    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1, le=MAX_REVISIONS)
    actor: Subject
    recorded_at: str
    change: Literal["created", "view_updated", "access_updated", "hypothesis_updated", "evidence_captured"]
    view: WorkspaceView
    readers: list[Subject] = Field(max_length=20)
    editors: list[Subject] = Field(max_length=20)
    hypotheses: list[WorkspaceHypothesis] = Field(default_factory=list, max_length=20)
    capture_id: str | None = Field(default=None, pattern=CAPTURE_ID)

    @model_validator(mode="after")
    def valid_metadata(self):
        """Stored timestamps and memberships must remain valid on every read."""
        if datetime.fromisoformat(self.recorded_at).tzinfo is None:
            raise ValueError("Workspace revision time must be timezone-aware")
        WorkspaceAccess(expected_revision=self.revision, readers=self.readers, editors=self.editors)
        if len({row.hypothesis_id for row in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("Workspace hypothesis identities must be unique")
        return self


class WorkspaceState(BaseModel):
    """One CAS document contains a complete bounded immutable revision sequence."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    workspace_id: str = Field(pattern=WORKSPACE_ID)
    owner: Subject
    scope: dict[str, list[str]]
    revisions: list[WorkspaceRevision] = Field(min_length=1, max_length=MAX_REVISIONS)
    captures: list[EvidenceCaptureReference] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def coherent_history(self):
        """Fail closed on corrupt revision, ownership, change or timestamp history."""
        previous: WorkspaceRevision | None = None
        captures = {row.capture_id: row for row in self.captures}
        linked: list[str] = []
        if len(captures) != len(self.captures):
            raise ValueError("Workspace capture identities must be unique")
        for index, revision in enumerate(self.revisions, 1):
            if revision.revision != index or self.owner in revision.readers + revision.editors:
                raise ValueError("Workspace revision sequence or ownership is invalid")
            if previous is None:
                if (
                    revision.actor != self.owner or revision.change != "created"
                    or revision.readers or revision.editors or revision.hypotheses or revision.capture_id
                ):
                    raise ValueError("Workspace creation attribution is invalid")
            else:
                if datetime.fromisoformat(revision.recorded_at) < datetime.fromisoformat(previous.recorded_at):
                    raise ValueError("Workspace revision times are out of order")
                if revision.change != "evidence_captured" and revision.capture_id != previous.capture_id:
                    raise ValueError("Only an evidence capture can change the retained receipt")
                if revision.change == "access_updated":
                    if (
                        revision.actor != self.owner or revision.view != previous.view
                        or revision.hypotheses != previous.hypotheses
                    ):
                        raise ValueError("Workspace access change attribution is invalid")
                elif revision.change == "view_updated":
                    if (
                        revision.actor not in [self.owner, *previous.editors]
                        or revision.readers != previous.readers or revision.editors != previous.editors
                        or revision.hypotheses != previous.hypotheses
                    ):
                        raise ValueError("Workspace view change attribution is invalid")
                elif revision.change == "hypothesis_updated":
                    if (
                        revision.actor not in [self.owner, *previous.editors]
                        or revision.readers != previous.readers or revision.editors != previous.editors
                        or revision.view != previous.view
                    ):
                        raise ValueError("Workspace hypothesis change attribution is invalid")
                    before = {row.hypothesis_id: row for row in previous.hypotheses}
                    after = {row.hypothesis_id: row for row in revision.hypotheses}
                    changed = [row for key, row in after.items() if before.get(key) != row]
                    if not before.keys() <= after.keys() or len(changed) != 1:
                        raise ValueError("Workspace hypothesis updates must preserve every other entry")
                    row = changed[0]
                    original = before.get(row.hypothesis_id)
                    anchor = (
                        (original.entry_type, original.subject, original.created_revision)
                        if original else (previous.view.entry_type, previous.view.subject, index)
                    )
                    if (
                        (row.entry_type, row.subject, row.created_revision) != anchor
                        or row.updated_revision != index or row.actor != revision.actor
                        or row.recorded_at != revision.recorded_at
                    ):
                        raise ValueError("Workspace hypothesis attribution or original subject is invalid")
                elif revision.change == "evidence_captured":
                    ref = captures.get(revision.capture_id)
                    if (
                        not ref or ref.capture_id in linked or ref.workspace_revision != index
                        or ref.actor != revision.actor or ref.recorded_at != revision.recorded_at
                        or revision.actor not in [self.owner, *previous.editors]
                        or revision.view != previous.view or revision.hypotheses != previous.hypotheses
                        or revision.readers != previous.readers or revision.editors != previous.editors
                    ):
                        raise ValueError("Workspace evidence capture attribution is invalid")
                    linked.append(ref.capture_id)
                else:
                    raise ValueError("Only the first workspace revision can be creation")
            previous = revision
        if linked != [row.capture_id for row in self.captures]:
            raise ValueError("Workspace contains unlinked or reordered capture references")
        return self


class WorkspaceNotFoundError(LookupError):
    """Missing, unshared, inaccessible-scope and unavailable-revision identities."""


class WorkspacePermissionError(PermissionError):
    """An authorized member lacks the requested workspace editing permission."""


class InvestigationWorkspaceStore:
    """Persist exact-scope team revisions and immutable evidence with local/OneLake CAS parity."""

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
            "captures": [row.model_dump() for row in state.captures if row.workspace_revision <= selected],
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

    def _append(
        self, snapshot, state: WorkspaceState, actor: str, expected_revision: int,
        changes: dict, *, recorded_at: str | None = None, capture: EvidenceCaptureReference | None = None,
    ) -> dict:
        latest = state.revisions[-1]
        if latest.revision != expected_revision:
            raise DocumentConflictError("Workspace changed; reload the latest revision before saving")
        if len(state.revisions) >= MAX_REVISIONS:
            raise ValueError("Workspace reached 40 revisions; administrative archival is required")
        row = WorkspaceRevision.model_validate({
            **latest.model_dump(), **changes, "revision": latest.revision + 1,
            "actor": actor, "recorded_at": recorded_at or datetime.now(UTC).isoformat(),
        })
        updated = WorkspaceState.model_validate({
            **state.model_dump(), "revisions": [*state.revisions, row],
            "captures": [*state.captures, capture] if capture else state.captures,
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

    def update_hypothesis(
        self, workspace_id: str, hypothesis_id: str, actor: str,
        scope: dict[str, list[str]], change: HypothesisUpdate,
    ) -> dict:
        """Append one attributed annotation; membership, subject anchor and other entries stay intact."""
        if not re.fullmatch(HYPOTHESIS_ID, hypothesis_id):
            raise ValueError("Hypothesis identity is invalid")
        snapshot, state = self._read(workspace_id, actor, scope)
        latest = state.revisions[-1]
        if actor not in [state.owner, *latest.editors]:
            raise WorkspacePermissionError("Hypothesis editing requires the workspace owner or an explicit editor")
        if latest.revision != change.expected_revision:
            raise DocumentConflictError("Workspace changed; reload before editing a hypothesis")
        existing = next((row for row in latest.hypotheses if row.hypothesis_id == hypothesis_id), None)
        if not existing and len(latest.hypotheses) >= 20:
            raise ValueError("Workspace reached 20 hypotheses; dismiss existing entries without deleting history")
        if existing and existing.model_dump(include=set(HypothesisDraft.model_fields)) == change.hypothesis.model_dump():
            raise ValueError("The hypothesis has no changes to save")
        recorded_at = datetime.now(UTC).isoformat()
        row = WorkspaceHypothesis(
            **change.hypothesis.model_dump(), hypothesis_id=hypothesis_id,
            entry_type=existing.entry_type if existing else latest.view.entry_type,
            subject=existing.subject if existing else latest.view.subject,
            created_revision=existing.created_revision if existing else latest.revision + 1,
            updated_revision=latest.revision + 1, actor=actor, recorded_at=recorded_at,
        )
        hypotheses = [
            row if item.hypothesis_id == hypothesis_id else item for item in latest.hypotheses
        ] if existing else [*latest.hypotheses, row]
        return self._append(snapshot, state, actor, change.expected_revision, {
            "change": "hypothesis_updated", "hypotheses": hypotheses,
        }, recorded_at=recorded_at)

    @staticmethod
    def _capture_name(workspace_id: str, capture_id: str) -> str:
        if not re.fullmatch(WORKSPACE_ID, workspace_id) or not re.fullmatch(CAPTURE_ID, capture_id):
            raise ValueError("Workspace or capture identity is invalid")
        return f"state/investigation-evidence/{workspace_id}/{capture_id}.json"

    @staticmethod
    def _capture_digest(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def retain_capture(
        self, workspace_id: str, actor: str, scope: dict[str, list[str]],
        request: EvidenceCaptureRequest, sources: list[CapturedSource],
    ) -> dict:
        """Create one receipt, then CAS-link it; a racing unlinked document grants no access."""
        snapshot, state = self._read(workspace_id, actor, scope)
        latest = state.revisions[-1]
        if actor not in [state.owner, *latest.editors]:
            raise WorkspacePermissionError("Retaining evidence requires the workspace owner or an explicit editor")
        if latest.revision != request.expected_revision:
            raise DocumentConflictError("Workspace changed during evidence acquisition; no capture was linked")
        if len(state.captures) >= 5 or latest.revision >= MAX_REVISIONS:
            raise ValueError("Workspace capture/revision capacity reached; administrative archival is required")
        recorded_at = datetime.now(UTC).isoformat()
        try:
            receipt = InvestigationCapture(
                workspace_id=workspace_id, capture_id=request.capture_id, scope=scope,
                actor=actor, recorded_at=recorded_at, workspace_revision=latest.revision + 1,
                view=latest.view, sources=sources,
            )
        except ValueError as exc:
            raise RuntimeError("Server evidence acquisition does not satisfy the retained projection contract") from exc
        payload = receipt.model_dump()
        if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_CAPTURE_BYTES:
            raise ValueError("Retained projection exceeds its 160 KiB receipt limit")
        reference = EvidenceCaptureReference(
            capture_id=request.capture_id, digest=self._capture_digest(payload),
            workspace_revision=receipt.workspace_revision, actor=actor, recorded_at=recorded_at,
        )
        self.documents.create_only(self._capture_name(workspace_id, request.capture_id), payload)
        return self._append(snapshot, state, actor, request.expected_revision, {
            "change": "evidence_captured", "capture_id": request.capture_id,
        }, recorded_at=recorded_at, capture=reference)

    def prepare_capture(
        self, workspace_id: str, actor: str, scope: dict[str, list[str]], request: EvidenceCaptureRequest,
    ) -> WorkspaceView:
        """Authorize identity, latest revision and capacity before any source acquisition."""
        _, state = self._read(workspace_id, actor, scope)
        if actor not in [state.owner, *state.revisions[-1].editors]:
            raise WorkspacePermissionError("Retaining evidence requires the workspace owner or an explicit editor")
        if state.revisions[-1].revision != request.expected_revision:
            raise DocumentConflictError("Workspace changed; open the latest revision before retaining evidence")
        if len(state.captures) >= 5 or request.expected_revision >= MAX_REVISIONS:
            raise ValueError("Workspace capture/revision capacity reached; administrative archival is required")
        if self.documents.read_snapshot(self._capture_name(workspace_id, request.capture_id)).exists:
            raise DocumentConflictError("Capture identity already exists; inspect the latest workspace before retrying")
        return state.revisions[-1].view

    def read_capture(
        self, workspace_id: str, capture_id: str, actor: str, scope: dict[str, list[str]], revision: int,
    ) -> dict:
        """Read only a linked receipt under current membership/scope without source acquisition."""
        _, state = self._read(workspace_id, actor, scope)
        if not 1 <= revision <= state.revisions[-1].revision:
            raise WorkspaceNotFoundError("Retained evidence unavailable")
        reference = next((row for row in state.captures if row.capture_id == capture_id and row.workspace_revision <= revision), None)
        if reference is None:
            raise WorkspaceNotFoundError("Retained evidence unavailable")
        snapshot = self.documents.read_snapshot(self._capture_name(workspace_id, capture_id))
        if not snapshot.exists:
            raise RuntimeError("Linked investigation evidence is missing")
        payload = snapshot.payload
        try:
            if len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()) > MAX_CAPTURE_BYTES:
                raise ValueError("Capture exceeds retention bound")
            receipt = InvestigationCapture.model_validate(payload)
            if (
                self._capture_digest(payload) != reference.digest or receipt.workspace_id != workspace_id
                or receipt.scope != scope or receipt.capture_id != capture_id
                or receipt.actor != reference.actor or receipt.recorded_at != reference.recorded_at
                or receipt.workspace_revision != reference.workspace_revision
                or receipt.view != state.revisions[reference.workspace_revision - 1].view
            ):
                raise ValueError("Capture identity, digest or saved view is invalid")
        except ValueError as exc:
            raise RuntimeError("Stored investigation evidence is invalid") from exc
        return receipt.model_dump()
