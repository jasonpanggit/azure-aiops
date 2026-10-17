"""Access-controlled navigation revisions; no provider reads or execution authority."""

from typing import Annotated

from fastapi import APIRouter, Path, Query

from operations.investigation_workspaces import (
    MAX_REVISIONS,
    WORKSPACE_ID,
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
                "Workspace navigation and operator membership only, not retained provider evidence, "
                "platform access grants, approvals or execution authority. Restoring reacquires current authorized evidence. "
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
