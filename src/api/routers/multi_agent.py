"""Multi-agent autonomous investigation routes."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
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
from operations.orchestration_service import execute_from_question

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


def _create_investigation_canonical(
    payload: InvestigationCreateRequest,
    *,
    context: Any,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Route POST /agents/investigations through the canonical service.

    Translates objective/scope/principal into a canonical request, invokes
    ``OrchestrationService.execute`` via the shared adapter, and projects the
    result into the legacy ledger shape for response compatibility and
    persistence.  Principal scope, audit actions, and deterministic rollback
    are preserved by the canonical service's policy and thread model.
    """
    objective = payload.objective.strip()
    result = execute_from_question(
        objective,
        scope=scope,
        context=context,
        principal_subject=principal.subject,
    )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    ledger: dict[str, Any] = {
        "contract_version": result.contract_version,
        "ledger_id": f"mai-{_uuid.uuid4().hex[:12]}",
        "objective": objective,
        "scope": scope.to_dict(),
        "created_by": principal.subject,
        "created_at": now,
        "updated_at": now,
        "status": (
            "synthesized" if result.status in ("ok", "empty") else result.status
        ),
        "orchestration": {
            "runtime": "canonical",
            "strategy": "canonical_service",
            "selected_ids": result.selected_specialists,
        },
        "selected_agents": [],
        "agent_runs": [],
        "reconciliation": {
            "evidence_count": len(result.citations),
            "reconciled_confidence": "medium",
        },
        "synthesis": {"mode": "canonical", "narration": ""},
        "human_controls": {
            "available_actions": [
                "request_more_evidence",
                "accept_finding",
                "reject_finding",
                "assign_owner",
                "approve_plan",
                "stop_investigation",
            ]
        },
        "decisions": [],
        "approvals": [],
        "outcome": "",
        "stop_reason": "",
        "evaluation": {},
        "tool_calls": [
            {
                "tool": tr["tool"],
                "status": tr["status"],
                "warning": tr.get("warning", ""),
                "operation": "delegate",
            }
            for tr in result.tool_results
        ],
        "findings": [],
        "warnings": list(result.uncertainty),
        "thread_id": result.thread_id,
    }
    ledger_store().add(ledger)
    return _respond(ledger, scope)


@router.post("/investigations", summary="Run autonomous multi-agent investigation")
def create_investigation(
    payload: InvestigationCreateRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    if canonical_orchestration_enabled():
        return _create_investigation_canonical(
            payload, context=context, scope=scope, principal=principal,
        )

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
