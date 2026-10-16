"""Multi-agent autonomous investigation routes."""

from __future__ import annotations

import os
import time
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from operations.autonomous_investigation import (
    agent_catalog,
    ledger_store,
    project_legacy_ledger,
    run_autonomous_investigation,
)
from operations.foundry_agent import SPECIALIST_IDS
from operations.investigation_thread_store import (
    ThreadRevisionConflict,
    ThreadStoreUnavailable,
)
from operations.maf_orchestrator import (
    CopilotRolloutDecision,
    canonical_orchestration_enabled,
    copilot_rollout_decision,
)
from operations.orchestration_service import execute_from_question

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope

router = APIRouter(prefix="/api/v1/agents", tags=["multi-agent-investigation"])


class InvestigationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: str = Field(min_length=1, max_length=1024)
    timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0, strict=True)


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


def _project_deterministic_activation(
    ledger: dict[str, Any],
    *,
    context: Any,
) -> dict[str, Any]:
    """Expose deterministic execution without implying Foundry agents ran."""

    projected = project_legacy_ledger(ledger)
    catalog_by_id = {
        str(agent.get("id") or ""): agent
        for agent in agent_catalog()
    }
    selected_ids = [
        str(agent.get("id") or "")
        for agent in projected.get("selected_agents") or []
    ]
    projected["selected_agents"] = [
        catalog_by_id.get(agent_id, {"id": agent_id})
        for agent_id in selected_ids
    ]
    foundry_ready = sum(
        bool(agent.get("foundry", {}).get("configured"))
        for agent in projected["selected_agents"]
    )
    activation_source = (
        os.environ.get("AIOPS_SPECIALIST_ACTIVATION_SOURCE", "").strip()
        or "unconfigured"
    )
    version_pinning_required = (
        os.environ.get(
            "AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED",
            "",
        ).strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    synthesis = projected.get("synthesis") or {}
    narrator_name = str(synthesis.get("narrated_by") or "")
    coordinator = {
        "status": "executed" if synthesis.get("llm_calls") else "unavailable",
        "name": narrator_name,
        "version": "",
    }
    if synthesis.get("llm_calls"):
        provider = getattr(context, "foundry_agent", None)
        try:
            narrator = provider() if callable(provider) else None
        except (ApiError, ConnectionError, RuntimeError, TimeoutError, ValueError):
            narrator = None
        if narrator is not None:
            coordinator["name"] = str(
                getattr(narrator, "agent_name", "") or narrator_name
            )
            coordinator["version"] = str(
                getattr(narrator, "agent_version", "") or ""
            )
    activation = {
        "mode": "deterministic_degraded",
        "source": activation_source,
        "foundry_ready": foundry_ready,
        "selected_specialists": len(selected_ids),
        "version_pinning_required": version_pinning_required,
        "coordinator": coordinator,
    }
    projected["activation"] = activation
    existing_orchestration = projected.get("orchestration") or {}
    projected["orchestration"] = {
        **existing_orchestration,
        "runtime": existing_orchestration.get(
            "runtime",
            "legacy_deterministic",
        ),
        "strategy": existing_orchestration.get(
            "strategy",
            "local_specialist_definitions",
        ),
        "selected_ids": existing_orchestration.get(
            "selected_ids",
            selected_ids,
        ),
        "activation_mode": activation["mode"],
    }

    citations: list[dict[str, Any]] = list(
        projected.get("citations") or []
    )
    all_citation_ids: list[str] = [
        str(citation.get("citation_id") or "")
        for citation in citations
        if citation.get("citation_id")
    ]
    canonical_citations = bool(citations)
    for run in projected.get("agent_runs") or []:
        agent_id = str(run.get("agent_id") or "")
        run["activation"] = catalog_by_id.get(
            agent_id,
            {},
        ).get("foundry", {"status": "unavailable", "configured": False})
        run["execution_mode"] = "deterministic_local"
        run["mutation_authorized"] = False
        tool_refs: dict[str, list[str]] = {}
        for call_index, call in enumerate(run.get("tool_calls") or []):
            call["mutation_authorized"] = False
            if canonical_citations:
                refs = [
                    citation_id
                    for citation_id in all_citation_ids
                    if citation_id.startswith(
                        f"tool:{call.get('call_id', '')}:"
                    )
                ]
            else:
                evidence = (
                    call.get("evidence")
                    or (call.get("result") or {}).get("evidence")
                    or []
                )
                refs = []
                for evidence_index, item in enumerate(evidence):
                    citation_id = (
                        f"legacy:{projected['ledger_id']}:{agent_id}:"
                        f"{call_index}:{evidence_index}"
                    )
                    refs.append(citation_id)
                    citations.append(
                        {
                            "citation_id": citation_id,
                            "source": (
                                f"{item.get('source_engine', '')}:"
                                f"{item.get('source_table', '')}"
                            ).strip(":"),
                            "status": call.get("status", "unknown"),
                            "observed_at": item.get("timestamp", ""),
                            "resource_id": item.get("resource_id", ""),
                        }
                    )
            call["evidence_refs"] = refs
            all_citation_ids.extend(refs)
            tool_refs.setdefault(str(call.get("tool") or ""), []).extend(refs)
        for finding in run.get("findings") or []:
            finding_id = str(finding.get("finding_id") or "")
            refs = next(
                (
                    values
                    for tool, values in tool_refs.items()
                    if f":{tool}:" in finding_id
                ),
                [],
            )
            finding["citation_ids"] = list(
                finding.get("citation_ids") or refs
            )
            finding["mutation_authorized"] = False

    for run in projected.get("agent_runs") or []:
        if run.get("agent_id") == "executive_summary":
            for finding in run.get("findings") or []:
                finding["citation_ids"] = list(dict.fromkeys(all_citation_ids))
    projected["findings"] = [
        finding
        for run in projected.get("agent_runs") or []
        for finding in run.get("findings") or []
    ]
    projected["citations"] = citations
    synthesis["citation_ids"] = list(dict.fromkeys(all_citation_ids))
    synthesis["mutation_authorized"] = False
    projected["synthesis"] = synthesis
    evaluation = projected.get("evaluation") or {}
    grounded_findings = sum(
        bool(finding.get("citation_ids"))
        for finding in projected["findings"]
    )
    evaluation["groundedness"] = round(
        grounded_findings / max(1, len(projected["findings"])),
        3,
    )
    evaluation["groundedness_status"] = (
        "measured" if projected["findings"] else "unavailable"
    )
    evaluation["groundedness_reason"] = (
        "Fraction of findings with retained citations."
        if projected["findings"]
        else "No cited findings were retained for measurement."
    )
    projected["evaluation"] = evaluation
    projected["mutation_authorized"] = False
    return projected


@router.get("/catalog", summary="Specialized autonomous investigation agents")
def catalog(context: Context, scope: ReadScope) -> dict[str, Any]:
    return envelope({"agents": agent_catalog()}, evidence=_evidence(), scope=scope.to_dict())


@router.get("/runtime-readiness", summary="Cached investigation provider observations")
def runtime_readiness(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Read cached process state without acquiring providers or probing agents."""
    if context.provider_runtime is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Cached agent runtime observations are not configured",
        )
    health = context.provider_runtime.health(refresh=False)
    names = (
        "copilot", "semantic", "network", "exposure_query", "incidents",
        "remediation", "governance", "inventory", "fabric_iq",
        *(f"{specialist}_agent" for specialist in SPECIALIST_IDS),
    )
    fields = (
        "state", "configured", "loaded", "freshness", "ontology_version",
        "loaded_at", "last_attempt_at", "last_success_at", "degraded_reason",
        "cache_key_stale",
    )
    providers = health["providers"]
    return envelope(
        {
            "source": "api.ProviderRuntime",
            "report_kind": "cached_process_state",
            "reported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "providers": {
                name: {field: providers[name].get(field) for field in fields}
                if name in providers else None
                for name in names
            },
        },
        evidence=Evidence(
            source_engine="api.ProviderRuntime",
            source_table="cached_provider_states",
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        warnings=[
            (
                "Process-local cached observations, not a live Foundry, APIM or MCP "
                "probe, estate coverage, tool execution or operational authorization. "
                "Report time is not provider observation time."
            )
        ],
    )


def _create_investigation_canonical(
    payload: InvestigationCreateRequest,
    *,
    context: Any,
    scope: ReadScope,
    principal: CurrentPrincipal,
    rollout_decision: CopilotRolloutDecision,
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
            rollout_decision=rollout_decision,
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
    foundry_ready = sum(
        bool(agent.get("foundry", {}).get("configured"))
        for agent in selected_agents
    )
    activation_source = (
        os.environ.get("AIOPS_SPECIALIST_ACTIVATION_SOURCE", "").strip()
        or "unconfigured"
    )
    version_pinning_required = (
        os.environ.get(
            "AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED",
            "",
        ).strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    activation = {
        "mode": "deterministic_degraded",
        "source": activation_source,
        "foundry_ready": foundry_ready,
        "selected_specialists": len(selected_agents),
        "version_pinning_required": version_pinning_required,
    }
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
            "mutation_authorized": False,
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
            "mutation_authorized": False,
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
            "activation": catalog_by_id.get(
                specialist_id,
                {},
            ).get("foundry", {"status": "unavailable", "configured": False}),
            "execution_mode": (
                "foundry"
                if catalog_by_id.get(specialist_id, {})
                .get("foundry", {})
                .get("configured")
                else "deterministic_local"
            ),
            "mutation_authorized": False,
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
            "activation_mode": activation["mode"],
        },
        "activation": activation,
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
            "groundedness_status": (
                "measured" if findings else "unavailable"
            ),
            "groundedness_reason": (
                ""
                if findings
                else "No cited findings were retained for measurement."
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
        "mutation_authorized": False,
    }
    ledger = _project_deterministic_activation(ledger, context=context)
    ledger_store().add(ledger)
    return _respond(ledger, scope)


@router.post("/investigations", summary="Run autonomous multi-agent investigation")
def create_investigation(
    payload: InvestigationCreateRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    rollout = copilot_rollout_decision(stable_key=principal.subject)
    if canonical_orchestration_enabled(
        stable_key=principal.subject,
        decision=rollout,
    ):
        return _create_investigation_canonical(
            payload,
            context=context,
            scope=scope,
            principal=principal,
            rollout_decision=rollout,
        )
    ledger = run_autonomous_investigation(
        payload.objective.strip(),
        context=context,
        scope=scope,
        principal_subject=principal.subject,
        timeout_seconds=payload.timeout_seconds,
    )
    ledger = _project_deterministic_activation(ledger, context=context)
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
    if payload.action in {"accept_finding", "reject_finding"}:
        finding_id = payload.payload.get("finding_id")
        reason = payload.payload.get("reason")
        findings = [
            finding
            for run in ledger.get("agent_runs") or []
            for finding in run.get("findings") or []
        ] + list(ledger.get("findings") or [])
        if (
            not isinstance(finding_id, str)
            or not any(finding.get("finding_id") == finding_id for finding in findings)
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 1000
        ):
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                "Select a finding in this ledger and provide a reason of 1 to 1000 characters",
            )
    ledger = ledger_store().record_decision(
        ledger_id, principal.subject, payload.action, payload.payload
    )
    if ledger is None:
        raise _not_found(ledger_id)
    if canonical_orchestration_enabled(stable_key=principal.subject):
        ledger = project_legacy_ledger(ledger)
    return _respond(ledger, scope)
