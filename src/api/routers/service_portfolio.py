"""Authorized service portfolio capture and retained recovery; no submitted metrics."""

from datetime import UTC, datetime

from fastapi import APIRouter

from operations.overview_history import HistoryCapture
from operations.service_portfolio import (
    PortfolioSource,
    ServicePortfolioStore,
    build_portfolio,
)
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, CurrentPrincipal, Pagination, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope
from .connections import list_connections
from .operations import list_incidents

router = APIRouter(prefix="/api/v1/service-portfolio", tags=["services"])


def _store(context: Context) -> ServicePortfolioStore:
    if context.service_portfolio_store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE, "Durable service portfolio is unavailable"
        )
    return context.service_portfolio_store


def _response(data: dict, scope: ReadScope) -> dict:
    return envelope(
        data,
        scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="services.retained_portfolio",
            source_table="state/service-portfolio",
            timestamp=data["observations"][-1]["captured_at"]
            if data["observations"]
            else "",
            confidence="unknown",
        ),
        warnings=[
            "Explicit independent source collections, not service reliability telemetry, continuous history or causal evidence."
        ],
    )


@router.get("/history")
def history(context: Context, principal: CurrentPrincipal, scope: ReadScope) -> dict:
    """Reauthorize the exact caller/scope and recover without active providers."""
    return _response(_store(context).read(principal.subject, scope.to_dict()), scope)


@router.post("/history", status_code=201)
def capture(
    payload: HistoryCapture,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
) -> dict:
    """Acquire registry and incident evidence server-side; fail without retaining partial state."""
    store = _store(context)
    if (
        store.read(principal.subject, scope.to_dict())["revision"]
        != payload.expected_revision
    ):
        raise ApiError(
            ErrorCode.CONFLICT, "Service portfolio changed; reload before capturing"
        )
    values = {}
    sources = []
    for source_id, read in (
        (
            "connections",
            lambda: list_connections(
                context, scope, Pagination(0, 10_000), include_disabled=True
            ),
        ),
        ("incidents", lambda: list_incidents(context, scope, Pagination(0, 100))),
    ):
        started = datetime.now(UTC).isoformat()
        result = read()
        finished = datetime.now(UTC).isoformat()
        values[source_id] = (
            result["data"]
            if source_id == "connections"
            else result["data"]["incidents"]
        )
        rows = values[source_id]
        pagination = result["pagination"]
        if source_id == "connections" and pagination["total"] > len(rows):
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                "Portfolio capture requires a complete registry of at most 10,000 accessible connections",
            )
        sources.append(
            PortfolioSource(
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
                reported_freshness=sorted(
                    {
                        str(row["freshness"])
                        for row in result.get("evidence", [])
                        if row.get("freshness")
                    }
                ),
                loaded=len(rows),
                total=pagination["total"],
                partial=len(rows) < pagination["total"],
                warning_count=len(result.get("warnings") or []),
            )
        )
    try:
        data = store.append(
            principal.subject,
            scope.to_dict(),
            payload.expected_revision,
            services=build_portfolio(values["connections"], values["incidents"]),
            sources=sources,
        )
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    return _response(data, scope)
