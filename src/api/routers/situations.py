"""Authorization-scoped durable situation and evidence reads."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..dependencies import Context, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope

router = APIRouter(prefix="/api/v1", tags=["situations"])


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
) -> dict[str, Any]:
    provider = _provider(context)
    if provider is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Situation provider is unavailable")
    rows = provider.list(scope, query=q, priority=priority)
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
