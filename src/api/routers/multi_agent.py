"""Multi-agent autonomous investigation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from operations.autonomous_investigation import (
    agent_catalog,
    ledger_store,
    project_legacy_ledger,
    run_autonomous_investigation,
)
from operations.maf_orchestrator import canonical_orchestration_enabled

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope

router = APIRouter(prefix="/api/v1/agents", tags=["multi-agent-investigation"])


class InvestigationCreateRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=1024)
    timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)


class LedgerActionRequest(BaseModel):
    action: str = Field(
        pattern="^(request_more_evidence|accept_finding|reject_finding|assign_owner|approve_plan|stop_investigation)$"
    )
    payload: dict[str, Any] = Field(default_factory=dict)


def _evidence(resource_id: str = "") -> Evidence:
    return Evidence(
        source_engine="operations.MultiAgentInvestigationOrchestrator",
        source_table="investigation_ledger",
        resource_id=resource_id,
        confidence=CONFIDENCE_MEDIUM,
    )


def _respond(data: dict[str, Any], scope: ReadScope) -> dict[str, Any]:
    return envelope(
        data,
        evidence=_evidence(str(data.get("ledger_id") or "")),
        scope=scope.to_dict(),
        warnings=list(data.get("warnings") or ()),
    )


@router.get("/catalog", summary="Specialized autonomous investigation agents")
def catalog(context: Context, scope: ReadScope) -> dict[str, Any]:
    return envelope({"agents": agent_catalog()}, evidence=_evidence(), scope=scope.to_dict())


@router.post("/investigations", summary="Run autonomous multi-agent investigation")
def create_investigation(
    payload: InvestigationCreateRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    ledger = run_autonomous_investigation(
        payload.objective.strip(),
        context=context,
        scope=scope,
        principal_subject=principal.subject,
        timeout_seconds=payload.timeout_seconds,
    )
    ledger_store().add(ledger)
    return _respond(ledger, scope)


@router.get("/investigations/{ledger_id}", summary="Read an investigation ledger")
def get_investigation(
    ledger_id: str,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    ledger = ledger_store().get(ledger_id, principal.subject)
    if ledger is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Investigation ledger not found", details={"ledger_id": ledger_id})
    if canonical_orchestration_enabled():
        ledger = project_legacy_ledger(ledger)
    return _respond(ledger, scope)


@router.post("/investigations/{ledger_id}/actions", summary="Record human investigation decision")
def apply_action(
    ledger_id: str,
    payload: LedgerActionRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    ledger = ledger_store().record_decision(
        ledger_id,
        principal.subject,
        payload.action,
        payload.payload,
    )
    if ledger is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Investigation ledger not found", details={"ledger_id": ledger_id})
    if canonical_orchestration_enabled():
        ledger = project_legacy_ledger(ledger)
    return _respond(ledger, scope)
