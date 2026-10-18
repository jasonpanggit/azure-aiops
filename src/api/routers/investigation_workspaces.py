"""Team workspaces with explicit governed source retention and historical reads."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query

from operations.investigation_evidence import (
    CAPTURE_ID,
    COVERAGE,
    CapturedSource,
    collect_investigation_sources,
    compare_investigation_sources,
)
from operations.investigation_workspaces import (
    HYPOTHESIS_ID,
    MAX_REVISIONS,
    WORKSPACE_ID,
    EvidenceCaptureRequest,
    EvidenceCompareRequest,
    HypothesisUpdate,
    InvestigationWorkspaceStore,
    WorkspaceAccess,
    WorkspaceCreate,
    WorkspaceNotFoundError,
    WorkspacePermissionError,
    WorkspaceUpdate,
)
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope

router = APIRouter(prefix="/api/v1/investigation-workspaces", tags=["investigation-workspaces"])
WorkspaceId = Annotated[str, Path(pattern=WORKSPACE_ID)]
CaptureId = Annotated[str, Path(pattern=CAPTURE_ID)]


def _store(context: Context) -> InvestigationWorkspaceStore:
    if context.investigation_workspace_store is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Durable investigation workspaces are unavailable")
    return context.investigation_workspace_store


def _response(data: dict, scope: ReadScope) -> dict:
    return envelope(
        data, scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="operations.investigation_workspaces",
            source_table="state/investigation-workspaces",
            timestamp=data["revision"]["recorded_at"], confidence="unknown",
        ),
        warnings=[
            (
                "Workspace navigation, membership and operator annotations are not retained provider evidence, "
                "platform access grants, approvals or execution authority. Source receipts are separate, explicit acquisitions. Restoring navigation reacquires current authorized evidence. "
                "All history is governed by current membership and exact effective scope."
            )
        ],
    )


def _failure(exc: Exception) -> ApiError:
    if isinstance(exc, WorkspaceNotFoundError):
        return ApiError(ErrorCode.NOT_FOUND, "Investigation workspace unavailable")
    if isinstance(exc, WorkspacePermissionError):
        return ApiError(ErrorCode.FORBIDDEN, str(exc))
    if isinstance(exc, DocumentConflictError):
        return ApiError(ErrorCode.CONFLICT, "Workspace changed or its identity already exists; open the latest revision before saving")
    if isinstance(exc, ValueError):
        return ApiError(ErrorCode.INVALID_REQUEST, str(exc))
    return ApiError(
        ErrorCode.PROVIDER_UNAVAILABLE,
        "Workspace operation was not confirmed; open the known identity and latest revision before retrying",
    )


_ERRORS = (WorkspaceNotFoundError, WorkspacePermissionError, DocumentConflictError, ValueError, OSError, RuntimeError)


@router.post("", status_code=201)
def create_workspace(
    payload: WorkspaceCreate, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict:
    """Create private navigation state once at a caller-known identity."""
    try:
        data = _store(context).create(principal.subject, scope.to_dict(), payload)
    except _ERRORS as exc:
        raise _failure(exc) from exc
    return _response(data, scope)


@router.put("/{workspace_id}/hypotheses/{hypothesis_id}")
def update_hypothesis(
    workspace_id: WorkspaceId, hypothesis_id: Annotated[str, Path(pattern=HYPOTHESIS_ID)],
    payload: HypothesisUpdate, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict:
    """Append one owner/editor annotation with server attribution and revision CAS."""
    try:
        data = _store(context).update_hypothesis(
            workspace_id, hypothesis_id, principal.subject, scope.to_dict(), payload,
        )
    except _ERRORS as exc:
        raise _failure(exc) from exc
    return _response(data, scope)


@router.get("/{workspace_id}")
def read_workspace(
    workspace_id: WorkspaceId, context: Context, principal: CurrentPrincipal, scope: ReadScope,
    revision: Annotated[int | None, Query(ge=1, le=MAX_REVISIONS)] = None,
) -> dict:
    """Reauthorize current membership and scope before returning any selected revision."""
    try:
        data = _store(context).read(workspace_id, principal.subject, scope.to_dict(), revision)
    except _ERRORS as exc:
        raise _failure(exc) from exc
    return _response(data, scope)


@router.put("/{workspace_id}")
def update_workspace(
    workspace_id: WorkspaceId, payload: WorkspaceUpdate,
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict:
    """Append a reviewed owner/editor navigation revision without changing membership."""
    try:
        data = _store(context).replace(workspace_id, principal.subject, scope.to_dict(), payload)
    except _ERRORS as exc:
        raise _failure(exc) from exc
    return _response(data, scope)


@router.put("/{workspace_id}/access")
def share_workspace(
    workspace_id: WorkspaceId, payload: WorkspaceAccess,
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict:
    """Allow only the immutable owner to change explicit workspace memberships."""
    try:
        data = _store(context).share(workspace_id, principal.subject, scope.to_dict(), payload)
    except _ERRORS as exc:
        raise _failure(exc) from exc
    return _response(data, scope)


@router.post("/{workspace_id}/evidence", status_code=201)
def retain_evidence(
    workspace_id: WorkspaceId, payload: EvidenceCaptureRequest,
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict:
    """Explicitly acquire governed read projections and CAS-link one immutable receipt."""
    try:
        store = _store(context)
        view = store.prepare_capture(workspace_id, principal.subject, scope.to_dict(), payload)
        sources = collect_investigation_sources(
            context, scope, principal, entry_type=view.entry_type, subject=view.subject,
        )
        data = store.retain_capture(workspace_id, principal.subject, scope.to_dict(), payload, sources)
    except _ERRORS as exc:
        raise _failure(exc) from exc
    response = _response(data, scope)
    response["warnings"].append(COVERAGE)
    return response


def _retained_response(data: dict, scope: ReadScope) -> dict:
    return envelope(
        data, scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="operations.investigation_evidence",
            source_table="state/investigation-evidence",
            # Receipt/acquisition clocks are not a source observation or evidence of freshness.
            timestamp="", confidence="unknown",
        ),
        warnings=[
            COVERAGE,
            "Stored source freshness is as recorded, not reclassified now. Missing source timestamps/versions remain unknown.",
            "Environment, connection, network-gap and remediation-plan entries retain scope-level projections, not exact entry detail.",
        ],
    )


@router.get("/{workspace_id}/evidence/{capture_id}")
def read_retained_evidence(
    workspace_id: WorkspaceId, capture_id: CaptureId,
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
    revision: Annotated[int, Query(ge=1, le=MAX_REVISIONS)],
) -> dict:
    """Reopen a linked retained version without acquiring providers or mutating timestamps."""
    try:
        data = _store(context).read_capture(workspace_id, capture_id, principal.subject, scope.to_dict(), revision)
    except _ERRORS as exc:
        raise _failure(exc) from exc
    return _retained_response(data, scope)


@router.post("/{workspace_id}/evidence/{capture_id}/compare")
def compare_retained_evidence(
    workspace_id: WorkspaceId, capture_id: CaptureId, payload: EvidenceCompareRequest,
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict:
    """Explicitly reacquire the retained view, then reauthorize before returning an unwritten comparison."""
    try:
        store = _store(context)
        workspace = store.read(workspace_id, principal.subject, scope.to_dict(), payload.reviewed_revision)
        if workspace["latest_revision"] != payload.expected_revision:
            raise DocumentConflictError("Workspace changed; reopen before comparing")
        retained = store.read_capture(workspace_id, capture_id, principal.subject, scope.to_dict(), payload.reviewed_revision)
        started = datetime.now(UTC).isoformat()
        current = collect_investigation_sources(
            context, scope, principal, entry_type=retained["view"]["entry_type"], subject=retained["view"]["subject"],
        )
        checked = store.read(workspace_id, principal.subject, scope.to_dict(), payload.reviewed_revision)
        if checked["latest_revision"] != payload.expected_revision:
            raise DocumentConflictError("Workspace changed during comparison; reopen before comparing")
        data = {
            "workspace_id": workspace_id, "capture_id": capture_id,
            "reviewed_revision": payload.reviewed_revision, "expected_revision": payload.expected_revision,
            "retained": retained, "current": {
                "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
                "view": retained["view"], "sources": [row.model_dump() for row in current],
            },
            "differences": compare_investigation_sources(
                [CapturedSource.model_validate(row) for row in retained["sources"]], current,
            ),
            "finished_at": datetime.now(UTC).isoformat(),
        }
    except _ERRORS as exc:
        raise _failure(exc) from exc
    return _retained_response(data, scope)
