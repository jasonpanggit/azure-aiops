"""Personal exact-scope navigation preferences; never provider reads or approvals."""

from fastapi import APIRouter

from operations.saved_views import SavedViewStore, ViewUpdate
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope

router = APIRouter(prefix="/api/v1/saved-views", tags=["saved-views"])


def _store(context: Context) -> SavedViewStore:
    if context.saved_view_store is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Durable saved views are unavailable")
    return context.saved_view_store


def _response(data: dict, scope: ReadScope) -> dict:
    return envelope(
        data, scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="operations.saved_views", source_table="state/saved-views",
            timestamp=data["updated_at"], confidence="unknown",
        ),
        warnings=["Personal navigation preferences only. Restoring reacquires current authorized evidence; it restores no results, access grant, SLA, approval or execution authority."],
    )


@router.get("")
def saved_views(context: Context, principal: CurrentPrincipal, scope: ReadScope) -> dict:
    """Read the subject's exact-effective-scope preference collection without providers."""
    try:
        data = _store(context).read(principal.subject, scope.to_dict())
    except (OSError, RuntimeError) as exc:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Saved views could not be read") from exc
    return _response(data, scope)


@router.put("")
def replace_saved_views(
    payload: ViewUpdate, context: Context, principal: CurrentPrincipal, scope: ReadScope,
) -> dict:
    """Conditionally replace personal preferences, not business or execution state."""
    try:
        data = _store(context).replace(principal.subject, scope.to_dict(), payload)
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Saved views update was not confirmed; reload before retrying") from exc
    return _response(data, scope)
