"""Multi-agent autonomous investigation routes."""

from __future__ import annotations

import time
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
from operations.investigation_thread_store import (
    ThreadRevisionConflict,
    ThreadStoreUnavailable,
)
from operations.maf_orchestrator import canonical_orchestration_enabled
from operations.orchestration_service import execute_from_question

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope

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


def _ledger_is_visible_in_scope(
    ledger: dict[str, Any],
    current_scope: Scope,
) -> bool:
    """Require the entire immutable ledger scope to remain authorized."""

    stored_scope = Scope.from_mapping(ledger.get("scope"))
    if current_scope.is_unrestricted():
        return True
    for dimension, allowed in current_scope.dimensions.items():
        stored_values = stored_scope.values(dimension)
        if not stored_values or not stored_values <= allowed:
            return False
    return True


def _not_found(ledger_id: str) -> ApiError:
    return ApiError(
        ErrorCode.NOT_FOUND,
        "Investigation ledger not found",
        details={"ledger_id": ledger_id},
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
    started = time.monotonic()
    try:
        result = execute_from_question(
            objective,
            scope=scope,
            context=context,
            principal_subject=principal.subject,
            max_wall_seconds=payload.timeout_seconds,
        )
    except ThreadStoreUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Investigation continuity is temporarily unavailable",
        ) from exc
    except ThreadRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Investigation thread changed; retry the request",
        ) from exc
    now = datetime.now(UTC).isoformat(timespec="seconds")
    catalog_by_id = {
        str(agent.get("id") or ""): agent
        for agent in agent_catalog()
    }
    selected_agents = [
        catalog_by_id.get(specialist_id, {"id": specialist_id})
        for specialist_id in result.selected_specialists
    ]
    citations = [
        citation.model_dump(mode="json")
        for citation in result.citations
    ]
    tool_calls = [
        {
            "call_id": tool_result.get("call_id", ""),
            "specialist_id": tool_result.get("specialist_id", ""),
            "tool": tool_result["tool"],
            "arguments": dict(tool_result.get("arguments") or {}),
            "status": tool_result["status"],
            "data": tool_result.get("data"),
            "evidence": list(tool_result.get("evidence", ())),
            "warning": tool_result.get("warning", ""),
            "attempts": 1,
            "operation": "delegate",
        }
        for tool_result in result.tool_results
    ]
    findings = [
        {
            "finding_id": tool_result.get("call_id", ""),
            "agent_id": tool_result.get("specialist_id", ""),
            "tool": tool_result["tool"],
            "summary": (
                f"{tool_result['tool']} returned {tool_result['status']}."
            ),
            "status": tool_result["status"],
            "confidence": (
                "high" if tool_result.get("evidence") else "unknown"
            ),
            "evidence_count": len(tool_result.get("evidence", ())),
            "unsupported": (
                tool_result["status"] in {"denied", "unavailable"}
                or not tool_result.get("evidence")
            ),
            "data": tool_result.get("data"),
            "citation_ids": [
                citation["citation_id"]
                for citation in citations
                if citation["citation_id"].startswith(
                    f"tool:{tool_result.get('call_id', '')}:"
                )
            ],
        }
        for tool_result in result.tool_results
        if tool_result.get("data") is not None
    ]
    agent_runs = [
        {
            "agent_id": specialist_id,
            "agent_name": str(
                catalog_by_id.get(specialist_id, {}).get("name")
                or specialist_id
            ),
            "status": (
                "not_started"
                if not any(
                    call["specialist_id"] == specialist_id
                    for call in tool_calls
                )
                else "partial"
                if any(
                    call["status"] != "ok"
                    for call in tool_calls
                    if call["specialist_id"] == specialist_id
                )
                else "ok"
            ),
            "tool_calls": [
                call
                for call in tool_calls
                if call["specialist_id"] == specialist_id
            ],
            "findings": [
                finding
                for finding in findings
                if finding["agent_id"] == specialist_id
            ],
            "evidence": [
                evidence
                for call in tool_calls
                if call["specialist_id"] == specialist_id
                for evidence in call["evidence"]
            ],
            "started_at": now,
            "completed_at": now,
            "duration_ms": 0,
            "confidence": (
                "high"
                if any(
                    call["evidence"]
                    for call in tool_calls
                    if call["specialist_id"] == specialist_id
                )
                else "unknown"
            ),
            "hidden_reasoning_exposed": False,
        }
        for specialist_id in result.selected_specialists
    ]
    missing_providers = [
        call
        for call in tool_calls
        if call["status"] in {"denied", "unavailable"}
    ]
    unsupported_conclusions = [
        finding for finding in findings if finding["unsupported"]
    ]
    evidence_count = sum(
        len(tool_result.get("evidence", ()))
        for tool_result in result.tool_results
    )
    evidence_backed_count = sum(
        finding["evidence_count"] > 0 for finding in findings
    )
    confidence = "medium" if evidence_count else "unknown"
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
            "policy_status": result.policy_status,
            "fallback_reason": result.fallback_reason,
        },
        "selected_agents": selected_agents,
        "agent_runs": agent_runs,
        "reconciliation": {
            "conflicts": [],
            "stale_evidence": [],
            "missing_providers": missing_providers,
            "unsupported_conclusions": unsupported_conclusions,
            "evidence_count": evidence_count,
            "confidence": confidence,
            "reconciled_confidence": confidence,
            "coverage": result.coverage.model_dump(mode="json"),
            "uncertainty": list(result.uncertainty),
        },
        "synthesis": {
            "mode": "canonical",
            "status": result.status,
            "policy_status": result.policy_status,
            "fallback_reason": result.fallback_reason,
            "coverage": result.coverage.model_dump(mode="json"),
            "uncertainty": list(result.uncertainty),
            "executive": result.synthesis,
            "summary": (
                f"Canonical investigation produced {evidence_backed_count} "
                "evidence-backed finding(s)."
            ),
            "recommended_plan": (
                "Review the cited findings and request more evidence before "
                "approving any operational change."
            ),
            "required_decision": (
                "Accept or reject the findings, or request more evidence."
            ),
            "unresolved_questions": list(result.uncertainty),
            "confidence": confidence,
            "narration": "",
            "narrated_by": "",
            "narration_warning": "",
            "llm_calls": 0,
        },
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
        "evaluation": {
            "groundedness": round(
                sum(finding["evidence_count"] > 0 for finding in findings)
                / max(1, len(findings)),
                3,
            ),
            "scope_isolation": (
                "enforced" if scope.to_dict() else "unrestricted_admin_scope"
            ),
            "tool_correctness": round(
                sum(call["status"] != "denied" for call in tool_calls)
                / max(1, len(tool_calls)),
                3,
            ),
            "convergence": (
                "converged_with_open_questions"
                if missing_providers or unsupported_conclusions
                else "converged"
            ),
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "cost": {
                "tool_calls": len(tool_calls),
                "agent_runs": len(agent_runs),
                "llm_calls": 0,
            },
        },
        "tool_calls": tool_calls,
        "findings": findings,
        "citations": citations,
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
    if canonical_orchestration_enabled(stable_key=principal.subject):
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
    if ledger is None or not _ledger_is_visible_in_scope(ledger, scope):
        raise _not_found(ledger_id)
    if canonical_orchestration_enabled(stable_key=principal.subject):
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
    ledger = ledger_store().get(ledger_id, principal.subject)
    if ledger is None or not _ledger_is_visible_in_scope(ledger, scope):
        raise _not_found(ledger_id)
    ledger = ledger_store().record_decision(
        ledger_id, principal.subject, payload.action, payload.payload
    )
    if ledger is None:
        raise _not_found(ledger_id)
    if canonical_orchestration_enabled(stable_key=principal.subject):
        ledger = project_legacy_ledger(ledger)
    return _respond(ledger, scope)
