"""Retain explicit server-composed Overview observations, never submitted metrics."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from operations.overview_history import (
    HistoryCapture,
    OverviewHistoryStore,
    OverviewSource,
)
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, CurrentPrincipal, Pagination, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope
from .network import network_summary
from .situations import list_situations
from .vulnerability import vulnerability_summary

router = APIRouter(prefix="/api/v1/overview", tags=["overview"])


def _store(context: Context) -> OverviewHistoryStore:
    if context.overview_history_store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE, "Durable Overview history is unavailable"
        )
    return context.overview_history_store


def _response(data: dict[str, Any], scope: ReadScope) -> dict[str, Any]:
    observations = data["observations"]
    return envelope(
        data,
        scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="overview.retained_observations",
            source_table="state/overview-history",
            timestamp=observations[-1]["captured_at"] if observations else "",
            confidence="unknown",
        ),
        warnings=[
            "Explicit captures only; collection times are not source observation times. No automatic cadence or causal attribution."
        ],
    )


@router.get("/history")
def history(
    context: Context, principal: CurrentPrincipal, scope: ReadScope
) -> dict[str, Any]:
    """Reauthorize exact owner/scope; no active provider is needed for recovery."""
    return _response(_store(context).read(principal.subject, scope.to_dict()), scope)


@router.post("/history", status_code=201)
def capture(
    payload: HistoryCapture,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
) -> dict[str, Any]:
    """Read each authorized source on the server; persist nothing if a read fails."""
    store = _store(context)
    if (
        store.read(principal.subject, scope.to_dict())["revision"]
        != payload.expected_revision
    ):
        raise ApiError(
            ErrorCode.CONFLICT, "Overview history changed; reload before capturing"
        )
    sources = []
    values = {}
    for source_id, read in (
        (
            "situations",
            lambda: list_situations(
                context,
                scope,
                Pagination(offset=0, limit=100),
                q="",
                priority="",
                assigned_owner="",
                lifecycle_state="",
                older_than_hours=None,
                sort="default",
            ),
        ),
        ("network", lambda: network_summary(context, scope)),
        ("exposure", lambda: vulnerability_summary(context, scope)),
    ):
        started = datetime.now(UTC).isoformat()
        result = read()
        finished = datetime.now(UTC).isoformat()
        values[source_id] = result["data"]
        pagination = result.get("pagination") or {}
        rows = result["data"]
        loaded = len(rows) if isinstance(rows, list) else None
        sources.append(
            OverviewSource(
                id=source_id,
                started_at=started,
                finished_at=finished,
                observed_at=sorted(
                    {
                        str(row["timestamp"])
                        for row in result.get("evidence", [])
                        if row.get("timestamp")
                    }
                ),
                source_tables=sorted(
                    {
                        str(row["source_table"])
                        for row in result.get("evidence", [])
                        if row.get("source_table")
                    }
                ),
                knowledge_version=str(result.get("knowledge_version") or ""),
                loaded=loaded,
                total=pagination.get("total"),
                partial=bool(pagination.get("next_offset") is not None),
                warning_count=len(result.get("warnings") or []),
            )
        )
    try:
        data = store.append(
            principal.subject,
            scope.to_dict(),
            payload.expected_revision,
            critical_situations=sum(
                row.get("priority") == "P1" for row in values["situations"]
            ),
            exposed_findings=values["exposure"]["internet_exposed_count"],
            network_gaps=values["network"]["gap_count"],
            sources=sources,
        )
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc)) from exc
    return _response(data, scope)
