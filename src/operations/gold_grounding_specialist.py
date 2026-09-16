"""Gold-grounding pre-stage for specialist narration calls."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fabric.gold_grounding_client import query_gold_grounding
from fabric_pipelines.gold_grounding_contract import (
    GoldGroundingStatus,
    parse_gold_grounded_findings,
)
from operations.foundry_agent import (
    _MAX_CONTEXT_CHARS,
    AgentAnswer,
    FoundryAgentError,
    MicrosoftAgentFrameworkFoundryAgent,
    parse_specialist_findings,
)
from operations.gold_grounding_metrics import GoldGroundingMetrics

_DEFAULT_GOLD_TOOL_NAME = "DataAgent_AI_Ops_Data_Agent"
_GOLD_CONTEXT_BUDGET_CHARS = 6_000


@dataclass(frozen=True)
class GoldGroundingScope:
    fabric_workspace_id: str
    gold_grounding_agent_id: str
    gold_grounding_tool_name: str
    fabric_delegated_token: str
    evidence_refs: set[str]
    resource_ids: set[str]


def gold_grounding_configured(scope: Any) -> bool:
    workspace_id, data_agent_id, _tool_name, token = _resolve_gold_grounding_config(
        scope
    )
    return bool(workspace_id and data_agent_id and token)


async def answer_with_gold_grounding(
    *,
    question: str,
    ontology_context: dict[str, Any],
    scope: Any,
    agent: Any,
    provider_context: Any | None = None,
    effective_scope: Any | None = None,
    metrics: GoldGroundingMetrics | None = None,
) -> AgentAnswer:
    """Merge Gold-grounding evidence into the existing specialist context."""

    metrics = metrics or GoldGroundingMetrics()
    started = time.monotonic()
    gold_evidence: dict[str, Any] | None = None
    degraded_reason = ""
    status = GoldGroundingStatus.UNAVAILABLE
    generation_id = _pinned_generation_id(ontology_context)

    workspace_id, data_agent_id, tool_name, delegated_token = (
        _resolve_gold_grounding_config(scope)
    )
    if not generation_id:
        degraded_reason = "ontology generation is not pinned"
    elif workspace_id and data_agent_id and delegated_token:
        result = await query_gold_grounding(
            workspace_id=workspace_id,
            data_agent_id=data_agent_id,
            tool_name=tool_name,
            question=_grounding_question(
                question=question,
                generation_id=generation_id,
                scope=scope,
                effective_scope=effective_scope,
            ),
            token=delegated_token,
        )
        status = result.status
        if result.status == GoldGroundingStatus.SUCCESS:
            parsed = _parse_gold_findings(
                result.payload or {},
                generation_id,
                empty_manifest=_empty_manifest(ontology_context),
            )
            status = parsed.status
            degraded_reason = parsed.reason
            gold_evidence = {
                "status": parsed.status.value,
                "generation_id": generation_id,
                "findings": [
                    _safe_finding_payload(finding) for finding in parsed.findings
                ],
                "empty_proof": (
                    parsed.empty_proof.model_dump(mode="json")
                    if parsed.empty_proof is not None
                    else None
                ),
            }
        else:
            degraded_reason = result.reason or result.status.value
            gold_evidence = {
                "status": result.status.value,
                "generation_id": generation_id,
                "findings": [],
            }
    else:
        degraded_reason = "gold grounding not configured"
    if gold_evidence is None:
        gold_evidence = {
            "status": status.value,
            "generation_id": generation_id,
            "findings": [],
        }

    gold_evidence = _truncate_gold_evidence(
        ontology_context=ontology_context,
        gold_evidence=gold_evidence,
        degraded_reason=degraded_reason,
    )
    inventory_conflicts = _collect_inventory_conflicts(
        gold_evidence=gold_evidence,
        provider_context=provider_context,
        effective_scope=effective_scope,
        scope=scope,
        metrics=metrics,
    )
    safe_conflicts: list[dict[str, str]] = []
    if inventory_conflicts:
        reasons = sorted(
            {
                str(conflict.get("reason") or "inventory_conflict")
                for conflict in inventory_conflicts
            }
        )
        status = (
            GoldGroundingStatus.DENIED
            if "outside_authorized_scope" in reasons
            else GoldGroundingStatus.UNAVAILABLE
        )
        degraded_reason = "Gold evidence withheld: " + ", ".join(reasons)
        gold_evidence = {
            "status": status.value,
            "generation_id": generation_id,
            "findings": [],
        }
        safe_conflicts = [{"reason": reason} for reason in reasons]

    merged_context: dict[str, Any] = {
        **ontology_context,
        "gold_grounding": gold_evidence,
        "gold_grounding_degraded": degraded_reason or None,
    }
    if safe_conflicts:
        merged_context["gold_grounding_inventory_conflicts"] = safe_conflicts
        merged_context["gold_grounding_inventory_conflict_notice"] = (
            "Inventory is authoritative for resource identity and lifecycle; "
            "conflicting Gold evidence was withheld from narration."
        )

    evidence_refs = set(getattr(scope, "evidence_refs", set()) or set())
    if gold_evidence and (gold_evidence.get("findings") or []):
        evidence_refs.add("gold_grounding")
    resource_ids = set(getattr(scope, "resource_ids", set()) or set()) or None

    answer = await _answer_findings_async(
        agent=agent,
        question=question,
        merged_context=merged_context,
        evidence_refs=evidence_refs,
        resource_ids=resource_ids,
        max_output_tokens=800,
    )

    metrics.record_query(
        degraded=bool(degraded_reason),
        degraded_reason=degraded_reason,
        citation_count=_citation_count(gold_evidence),
        duration_ms=(time.monotonic() - started) * 1000.0,
    )
    return answer


def _resolve_gold_grounding_config(scope: Any) -> tuple[str, str, str, str]:
    workspace_id = _scope_or_env(scope, "fabric_workspace_id", "FABRIC_WORKSPACE_ID")
    data_agent_id = _scope_or_env(
        scope,
        "gold_grounding_agent_id",
        "FABRIC_GOLD_GROUNDING_AGENT_ID",
    )
    tool_name = (
        _scope_or_env(
            scope,
            "gold_grounding_tool_name",
            "FABRIC_GOLD_GROUNDING_TOOL_NAME",
        )
        or _DEFAULT_GOLD_TOOL_NAME
    )
    delegated_token = str(getattr(scope, "fabric_delegated_token", "") or "").strip()
    return workspace_id, data_agent_id, tool_name, delegated_token


def _scope_or_env(scope: Any, scope_attr: str, env_name: str) -> str:
    scoped = str(getattr(scope, scope_attr, "") or "").strip()
    if scoped:
        return scoped
    return os.environ.get(env_name, "").strip()


def _pinned_generation_id(ontology_context: dict[str, Any]) -> str:
    for key in ("generation_id", "source_generation_id", "ontology_generation_id"):
        value = str(ontology_context.get(key) or "").strip()
        if value:
            return value
    generation = ontology_context.get("generation")
    if isinstance(generation, dict):
        return str(
            generation.get("generation_id") or generation.get("active_generation") or ""
        ).strip()
    return ""


def _grounding_question(
    *,
    question: str,
    generation_id: str,
    scope: Any,
    effective_scope: Any | None,
) -> str:
    """Bind an operator question to one generation and authorized scope."""
    scoped = effective_scope if effective_scope is not None else scope
    to_dict = getattr(scoped, "to_dict", None)
    scope_payload = to_dict() if callable(to_dict) else {}
    resource_ids = sorted(
        {
            str(resource_id).strip()
            for resource_id in (getattr(scope, "resource_ids", set()) or set())
            if str(resource_id).strip()
        }
    )
    return "\n".join(
        (
            f"PINNED_GENERATION_ID={generation_id}",
            "AUTHORIZED_SCOPE="
            + json.dumps(scope_payload, sort_keys=True, separators=(",", ":")),
            "AUTHORIZED_RESOURCE_IDS="
            + json.dumps(resource_ids, sort_keys=True, separators=(",", ":")),
            f"QUESTION={question}",
        )
    )


def _empty_manifest(ontology_context: dict[str, Any]) -> dict[str, Any] | None:
    value = ontology_context.get("gold_empty_manifest")
    return dict(value) if isinstance(value, dict) else None


def _parse_gold_findings(
    result: dict[str, Any],
    generation_id: str,
    *,
    empty_manifest: dict[str, Any] | None = None,
):
    content = result.get("content") if isinstance(result, dict) else None
    lines: list[str] = []
    if isinstance(content, list):
        for row in content:
            if isinstance(row, dict):
                text = row.get("text")
                if isinstance(text, str) and text.strip():
                    lines.append(text)
            elif isinstance(row, str) and row.strip():
                lines.append(row)
    response_text = "\n".join(lines)
    return parse_gold_grounded_findings(
        response_text,
        expected_generation_id=generation_id,
        empty_manifest=empty_manifest,
        tool_call_id="gold-grounding",
    )


def _citation_count(gold_evidence: dict[str, Any] | None) -> int:
    if not isinstance(gold_evidence, dict):
        return 0
    total = 0
    for finding in gold_evidence.get("findings") or []:
        if isinstance(finding, dict):
            citations = finding.get("citations") or []
            if isinstance(citations, list):
                total += len(citations)
    return total


def _safe_finding_payload(finding: Any) -> dict[str, Any]:
    """Remove model-authored narrative while retaining validated citations."""
    payload = finding.model_dump(mode="json")
    citation_count = len(payload.get("citations") or ())
    payload["summary"] = (
        f"{citation_count} scoped Gold citation"
        f"{'s' if citation_count != 1 else ''} available for deterministic review."
    )
    return payload


def _truncate_gold_evidence(
    *,
    ontology_context: dict[str, Any],
    gold_evidence: dict[str, Any] | None,
    degraded_reason: str,
) -> dict[str, Any] | None:
    if not isinstance(gold_evidence, dict):
        return gold_evidence
    findings = gold_evidence.get("findings")
    if not isinstance(findings, list) or not findings:
        return gold_evidence
    merged = {
        **ontology_context,
        "gold_grounding": gold_evidence,
        "gold_grounding_degraded": degraded_reason or None,
    }
    if len(json.dumps(merged, default=str, ensure_ascii=False)) <= _MAX_CONTEXT_CHARS:
        return gold_evidence

    trimmed_findings = [
        _ranked_finding(dict(finding))
        for finding in findings
        if isinstance(finding, dict)
    ]
    while True:
        candidate = {
            "status": gold_evidence.get("status"),
            "generation_id": gold_evidence.get("generation_id"),
            "findings": trimmed_findings,
        }
        merged = {
            **ontology_context,
            "gold_grounding": candidate,
            "gold_grounding_degraded": degraded_reason or None,
        }
        merged_size = len(json.dumps(merged, default=str, ensure_ascii=False))
        gold_size = len(json.dumps(candidate, default=str, ensure_ascii=False))
        if (
            merged_size <= _MAX_CONTEXT_CHARS
            and gold_size <= _GOLD_CONTEXT_BUDGET_CHARS
        ):
            return candidate
        if not _drop_lowest_ranked_citation(trimmed_findings):
            return candidate


def _ranked_finding(finding: dict[str, Any]) -> dict[str, Any]:
    citations = finding.get("citations") or []
    if not isinstance(citations, list):
        finding["citations"] = []
        return finding
    finding["citations"] = sorted(citations, key=_citation_rank_key, reverse=True)
    return finding


def _citation_rank_key(citation: Any) -> tuple[float, float]:
    if not isinstance(citation, dict):
        return (0.0, 0.0)
    confidence = float(citation.get("confidence") or 0.0)
    as_of_raw = str(citation.get("as_of") or "").strip()
    as_of_epoch = 0.0
    if as_of_raw:
        try:
            normalized = as_of_raw.replace("Z", "+00:00")
            as_of_epoch = datetime.fromisoformat(normalized).astimezone(UTC).timestamp()
        except ValueError:
            as_of_epoch = 0.0
    return confidence, as_of_epoch


def _drop_lowest_ranked_citation(findings: list[dict[str, Any]]) -> bool:
    tails: list[tuple[tuple[float, float], int]] = []
    for index, finding in enumerate(findings):
        citations = finding.get("citations") or []
        if citations:
            tails.append((_citation_rank_key(citations[-1]), index))
    if not tails:
        return False
    _worst_rank, worst_index = min(tails, key=lambda item: item[0])
    worst_finding = findings[worst_index]
    citations = worst_finding.get("citations") or []
    citations.pop()
    if not citations:
        findings.pop(worst_index)
    return True


def _collect_inventory_conflicts(
    *,
    gold_evidence: dict[str, Any] | None,
    provider_context: Any | None,
    effective_scope: Any | None,
    scope: Any,
    metrics: GoldGroundingMetrics,
) -> list[dict[str, Any]]:
    findings = (
        (gold_evidence or {}).get("findings")
        if isinstance(gold_evidence, dict)
        else None
    )
    if not isinstance(findings, list) or not findings:
        return []
    inventory_port = (
        _resolve_inventory_port(provider_context)
        if provider_context is not None
        else None
    )

    inventory_scope = _resolve_inventory_scope(
        effective_scope=effective_scope, scope=scope
    )
    if inventory_scope is None or inventory_port is None:
        conflicts: list[dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            for citation in _citations(finding):
                conflict = {
                    "reason": (
                        "inventory_scope_missing"
                        if inventory_scope is None
                        else "inventory_provider_missing"
                    ),
                    "resource_id": citation.get("resource_id"),
                    "citation": citation,
                    "inventory": None,
                }
                conflicts.append(conflict)
                _record_inventory_conflict(metrics)
        return conflicts

    conflicts: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        citations = _citations(finding)
        if not citations:
            continue
        allowed_resource_ids = {
            str(value).casefold()
            for value in (getattr(scope, "resource_ids", set()) or set())
            if str(value).strip()
        }
        for citation in citations:
            resource_id = str(citation.get("resource_id") or "").strip()
            if (
                allowed_resource_ids
                and resource_id.casefold() not in allowed_resource_ids
            ):
                conflicts.append(
                    {
                        "reason": "outside_authorized_scope",
                        "resource_id": resource_id,
                        "citation": citation,
                        "inventory": None,
                    }
                )
                _record_inventory_conflict(metrics)
                continue
            inventory = inventory_port.get_resource(inventory_scope, resource_id)
            conflict = _inventory_conflict_for(
                resource_id=resource_id,
                inventory=inventory,
                citation=citation,
            )
            if conflict is None:
                continue
            conflicts.append(conflict)
            _record_inventory_conflict(metrics)
    return conflicts


def _resolve_inventory_port(provider_context: Any) -> Any | None:
    resolver = getattr(provider_context, "resolve_provider", None)
    if not callable(resolver):
        return None
    try:
        return resolver("inventory_read_port")
    except (LookupError, RuntimeError, TypeError, ValueError):
        return None


def _resolve_inventory_scope(*, effective_scope: Any | None, scope: Any) -> Any | None:
    if (
        effective_scope is not None
        and hasattr(effective_scope, "matches")
        and hasattr(effective_scope, "to_dict")
    ):
        return effective_scope
    if hasattr(scope, "matches") and hasattr(scope, "to_dict"):
        return scope
    return None


def _citations(finding: dict[str, Any]) -> list[dict[str, Any]]:
    citations_raw = finding.get("citations") or []
    citations: list[dict[str, Any]] = []
    for citation in citations_raw:
        if isinstance(citation, dict):
            citations.append(citation)
    return citations


def _inventory_conflict_for(
    *,
    resource_id: str,
    inventory: dict[str, Any] | None,
    citation: dict[str, Any],
) -> dict[str, Any] | None:
    if inventory is None:
        return {
            "reason": "resource_not_found",
            "resource_id": resource_id,
            "citation": citation,
            "inventory": None,
        }

    expected_subscription, expected_resource_group = _parse_resource_identity(
        resource_id
    )
    inventory_subscription = str(inventory.get("subscription_id") or "").strip()
    inventory_resource_group = str(inventory.get("resource_group") or "").strip()
    subscription_mismatch = bool(expected_subscription) and (
        inventory_subscription.casefold() != expected_subscription.casefold()
    )
    resource_group_mismatch = bool(expected_resource_group) and (
        inventory_resource_group.casefold() != expected_resource_group.casefold()
    )
    if subscription_mismatch or resource_group_mismatch:
        return {
            "reason": "subscription_mismatch",
            "resource_id": resource_id,
            "citation": citation,
            "inventory": {
                "resource_id": inventory.get("resource_id"),
                "subscription_id": inventory.get("subscription_id"),
                "resource_group": inventory.get("resource_group"),
                "lifecycle_status": inventory.get("lifecycle_status"),
            },
        }

    lifecycle = str(inventory.get("lifecycle_status") or "").strip().casefold()
    if lifecycle in {"retired", "deleted", "deleting", "decommissioned", "terminated"}:
        return {
            "reason": "lifecycle_mismatch",
            "resource_id": resource_id,
            "citation": citation,
            "inventory": {
                "resource_id": inventory.get("resource_id"),
                "subscription_id": inventory.get("subscription_id"),
                "resource_group": inventory.get("resource_group"),
                "lifecycle_status": inventory.get("lifecycle_status"),
            },
        }

    return None


def _parse_resource_identity(resource_id: str) -> tuple[str, str]:
    parts = [part for part in str(resource_id).strip("/").split("/") if part]
    expected_subscription = ""
    expected_resource_group = ""
    for index, part in enumerate(parts):
        lowered = part.casefold()
        if lowered == "subscriptions" and index + 1 < len(parts):
            expected_subscription = parts[index + 1]
        if lowered == "resourcegroups" and index + 1 < len(parts):
            expected_resource_group = parts[index + 1]
    return expected_subscription, expected_resource_group


def _record_inventory_conflict(metrics: GoldGroundingMetrics) -> None:
    recorder = getattr(metrics, "record_inventory_conflict", None)
    if callable(recorder):
        recorder()
        return
    counter = getattr(metrics, "inventory_conflict", None)
    add = getattr(counter, "add", None)
    if callable(add):
        add(1)


async def _answer_findings_async(
    *,
    agent: Any,
    question: str,
    merged_context: dict[str, Any],
    evidence_refs: set[str],
    resource_ids: set[str] | None,
    max_output_tokens: int,
) -> AgentAnswer:
    if isinstance(agent, MicrosoftAgentFrameworkFoundryAgent):
        return await _answer_maf_findings_async(
            agent=agent,
            question=question,
            merged_context=merged_context,
            evidence_refs=evidence_refs,
            resource_ids=resource_ids,
            max_output_tokens=max_output_tokens,
        )

    answer = agent.answer_findings(
        question=question,
        context=merged_context,
        evidence_refs=evidence_refs,
        resource_ids=resource_ids,
        max_output_tokens=max_output_tokens,
    )
    if asyncio.iscoroutine(answer):
        answer = await answer
    return answer


async def _answer_maf_findings_async(
    *,
    agent: MicrosoftAgentFrameworkFoundryAgent,
    question: str,
    merged_context: dict[str, Any],
    evidence_refs: set[str],
    resource_ids: set[str] | None,
    max_output_tokens: int,
) -> AgentAnswer:
    prompt = agent.build_prompt(question, merged_context)
    try:
        response = await agent._run_agent(prompt, max_output_tokens=max_output_tokens)
    except Exception as exc:
        raise FoundryAgentError(
            "Microsoft Agent Framework Foundry agent request failed"
        ) from exc
    text = str(getattr(response, "text", "") or "").strip()
    if not text:
        raise FoundryAgentError(
            "Microsoft Agent Framework agent returned an empty answer"
        )
    parse_specialist_findings(
        text,
        evidence_refs=evidence_refs,
        resource_ids=resource_ids,
        agent_id=agent.specialist_id,
    )
    return AgentAnswer(
        text=text,
        agent_name=agent.agent_name,
        model="microsoft-agent-framework",
        grounded=True,
        agent_version=agent.agent_version,
    )


__all__ = [
    "GoldGroundingScope",
    "answer_with_gold_grounding",
    "gold_grounding_configured",
]
