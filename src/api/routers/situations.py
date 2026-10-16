"""Authorization-scoped durable situation and evidence reads."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from situations.notes import NoteAppend, SituationNotesStore
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, CurrentPrincipal, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope

router = APIRouter(prefix="/api/v1", tags=["situations"])

class HandoffSelection(BaseModel):
    """One explicit Situation and the evidence run reviewed by the operator."""

    model_config = ConfigDict(extra="forbid", strict=True)
    situation_id: str = Field(min_length=1, max_length=2048)
    run_id: str = Field(min_length=1, max_length=256)


class HandoffRequest(BaseModel):
    """Bounded read-only handoff; never an execution or approval request."""

    model_config = ConfigDict(extra="forbid", strict=True)
    selections: list[HandoffSelection] = Field(min_length=1, max_length=25)


def _started_at(row: dict[str, Any]) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(row.get("started_at") or ""))
    except ValueError:
        return None
    return value.astimezone(UTC) if value.tzinfo else None


def _provider(context: Context) -> Any:
    return context.situation_provider() if context.situation_provider else None


def _not_found(subject: str) -> ApiError:
    return ApiError(ErrorCode.NOT_FOUND, "Situation not found", {"subject": subject})


@router.get("/situations", summary="List authorized durable situations")
def list_situations(
    context: Context,
    scope: ReadScope,
    page: Page,
    q: str = Query("", max_length=256),
    priority: str = Query("", pattern="^(|P1|P2|P3)$"),
    assigned_owner: str = Query("", max_length=256),
    lifecycle_state: str = Query("", max_length=64),
    older_than_hours: int | None = Query(None, ge=0, le=87600),
    sort: str = Query("default", pattern="^(default|oldest|newest)$"),
) -> dict[str, Any]:
    provider = _provider(context)
    if provider is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Situation provider is unavailable")
    rows = provider.list(scope, query=q, priority=priority)
    now = datetime.now(UTC)
    rows = [
        row for row in rows
        if (not assigned_owner or str(row.get("owner") or "").casefold() == assigned_owner.strip().casefold())
        and (not lifecycle_state or str(row.get("lifecycle_state") or "").casefold() == lifecycle_state.strip().casefold())
        and (older_than_hours is None or (
            (started := _started_at(row)) is not None
            and (now - started).total_seconds() >= older_than_hours * 3600
        ))
    ]
    if sort != "default":
        rows = sorted(rows, key=lambda row: (
            _started_at(row) is None,
            ((_started_at(row) or now).timestamp()) * (-1 if sort == "newest" else 1),
            str(row.get("situation_id") or ""),
        ))
    else:
        rows = sorted(rows, key=lambda row: (
            {"P1": 0, "P2": 1, "P3": 2}.get(str(row.get("priority") or ""), 3),
            _started_at(row) is None,
            -(_started_at(row) or now).timestamp(),
            str(row.get("situation_id") or ""),
        ))
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=Evidence(
            source_engine="aiops.situations",
            source_table="silver_situations",
            timestamp=max((str(row.get("last_observed_at") or "") for row in rows), default=""),
            confidence="high" if rows else "unknown",
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )

@router.post("/situations/handoff", summary="Export a bounded read-only Situation handoff")
def situation_handoff(payload: HandoffRequest, context: Context, scope: ReadScope) -> dict[str, Any]:
    """Reauthorize every selected identity and reject changed evidence versions."""
    provider = _provider(context)
    if provider is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Situation provider is unavailable")
    if len({item.situation_id for item in payload.selections}) != len(payload.selections):
        raise ApiError(ErrorCode.INVALID_REQUEST, "Duplicate Situation selection")
    rows = []
    for selection in payload.selections:
        row = provider.get(selection.situation_id, scope)
        if row is None:
            raise _not_found(selection.situation_id)
        if str(row.get("run_id") or "") != selection.run_id:
            raise ApiError(ErrorCode.CONFLICT, "Situation evidence changed; reload before exporting")
        record = {
            key: row.get(key) for key in (
                "situation_id", "title", "owner", "support_team", "priority", "lifecycle_state",
                "started_at", "last_observed_at", "run_id", "linked_evidence_ids",
                "evidence_state", "warnings", "unknowns",
            )
        }
        record["linked_evidence_ids"] = sorted({
            str(item["evidence_id"]) for item in row.get("evidence", []) if item.get("evidence_id")
        })
        rows.append(record)
    artifact = {
        "schema_version": "situation-handoff.v1",
        "scope": scope.to_dict(), "exported_at": datetime.now(UTC).isoformat(),
        "boundary": "Read-only handoff; not approval or remediation authority.",
        "situations": rows,
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    if len(canonical.encode()) > 2 * 1024 * 1024:
        raise ApiError(ErrorCode.INVALID_REQUEST, "Selected evidence exceeds the 2 MiB handoff limit; select fewer Situations")
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return envelope({
        "artifact": artifact, "sha256": digest, "count": len(rows),
        "canonicalization": "Python json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=True), UTF-8",
    }, scope=scope.to_dict())


def _notes_target(situation_id: str, context: Context, scope: ReadScope) -> tuple[dict[str, Any], SituationNotesStore]:
    provider = _provider(context)
    if provider is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Situation provider is unavailable")
    row = provider.get(situation_id, scope)
    if row is None:
        raise _not_found(situation_id)
    if context.situation_notes_store is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Durable Situation handover storage is unavailable")
    return row, context.situation_notes_store


@router.get("/situations/{situation_id:path}/notes", summary="Read exact-scope Situation handover notes")
def situation_notes(situation_id: str, context: Context, scope: ReadScope, principal: CurrentPrincipal) -> dict[str, Any]:
    """Reauthorize the Situation on every read; annotations are not source evidence."""
    _, store = _notes_target(situation_id, context, scope)
    can_append = bool(principal.grants_for("operate")) and (
        context.authorizer.effective_scope(principal, "operate", scope) == scope
    )
    return envelope({
        **store.read(situation_id, scope.to_dict()), "can_append": can_append,
    }, scope=scope.to_dict())


@router.post("/situations/{situation_id:path}/notes", summary="Append an evidence-run-bound handover note")
def append_situation_note(
    situation_id: str, context: Context, scope: ReadScope, principal: OperatePrincipal, change: NoteAppend,
) -> dict[str, Any]:
    """Require operate rights across the entire read scope and pin the observed run."""
    if context.authorizer.effective_scope(principal, "operate", scope) != scope:
        raise ApiError(ErrorCode.FORBIDDEN, "The complete handover scope must be authorized")
    row, store = _notes_target(situation_id, context, scope)
    if str(row.get("run_id") or "") != change.evidence_run_id:
        raise ApiError(ErrorCode.CONFLICT, "Situation evidence changed; reload before appending")
    try:
        state = store.append(situation_id, scope.to_dict(), change, principal.subject)
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, "Handover notes changed; reload and review before retrying") from exc
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    return envelope({**state, "can_append": True}, scope=scope.to_dict())


@router.get("/situations/{situation_id:path}/audit", summary="Read situation audit history")
def situation_audit(situation_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    provider = _provider(context)
    if provider is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Situation provider is unavailable")
    rows = provider.audit(situation_id, scope)
    if rows is None:
        raise _not_found(situation_id)
    return envelope(rows, scope=scope.to_dict())


@router.get("/situations/{situation_id:path}", summary="Read an authorized situation")
def get_situation(situation_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    provider = _provider(context)
    if provider is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Situation provider is unavailable")
    row = provider.get(situation_id, scope)
    if row is None:
        raise _not_found(situation_id)
    return envelope(
        row,
        evidence=[
            Evidence(
                source_engine="aiops.situations",
                source_table="silver_situation_evidence",
                timestamp=str(item.get("observed_at") or ""),
                resource_id=str((item.get("resource_ids") or [""])[0]),
                confidence=str(item.get("confidence") or "unknown"),
                freshness=str(item.get("freshness") or "unknown"),
            )
            for item in row.get("evidence", [])
        ],
        scope=scope.to_dict(),
        knowledge_version=str(row.get("run_id") or ""),
        warnings=row.get("warnings") or [],
    )


@router.get("/evidence/{evidence_id:path}", summary="Read authorized evidence")
def get_evidence(evidence_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    provider = _provider(context)
    if provider is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Situation provider is unavailable")
    row = provider.evidence(evidence_id, scope)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Evidence not found", {"subject": evidence_id})
    return envelope(row, scope=scope.to_dict(), knowledge_version=str(row.get("run_id") or ""))
