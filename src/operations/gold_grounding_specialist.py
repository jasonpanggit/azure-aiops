"""Gold-grounding pre-stage for specialist narration calls."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fabric.gold_grounding_client import GoldGroundingUnavailable, query_gold_grounding
from fabric_pipelines.gold_grounding_contract import (
    GoldGroundedFinding,
    parse_gold_grounded_findings,
)
from operations.foundry_agent import (
    AgentAnswer,
    FoundryAgentError,
    MicrosoftAgentFrameworkFoundryAgent,
    _MAX_CONTEXT_CHARS,
    parse_specialist_findings,
)
from operations.gold_grounding_metrics import GoldGroundingMetrics

_DEFAULT_GOLD_TOOL_NAME = "DataAgent_gold_grounding_agent"
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
    workspace_id, data_agent_id, _tool_name, token = _resolve_gold_grounding_config(scope)
    return bool(workspace_id and data_agent_id and token)


async def answer_with_gold_grounding(
    *,
    question: str,
    ontology_context: dict[str, Any],
    scope: Any,
    agent: Any,
    metrics: GoldGroundingMetrics | None = None,
) -> AgentAnswer:
    """Merge Gold-grounding evidence into the existing specialist context."""

    metrics = metrics or GoldGroundingMetrics()
    started = time.monotonic()
    gold_evidence: dict[str, Any] | None = None
    degraded_reason = ""

    workspace_id, data_agent_id, tool_name, delegated_token = _resolve_gold_grounding_config(
        scope
    )
    if workspace_id and data_agent_id and delegated_token:
        try:
            result = query_gold_grounding(
                workspace_id=workspace_id,
                data_agent_id=data_agent_id,
                tool_name=tool_name,
                question=question,
                token=delegated_token,
            )
            findings = _parse_gold_findings(result)
            degraded_reason = _degraded_reason_from_findings(findings)
            gold_evidence = {"findings": [finding.model_dump(mode="json") for finding in findings]}
        except GoldGroundingUnavailable as exc:
            degraded_reason = str(exc)
    else:
        degraded_reason = "gold grounding not configured"

    gold_evidence = _truncate_gold_evidence(
        ontology_context=ontology_context,
        gold_evidence=gold_evidence,
        degraded_reason=degraded_reason,
    )

    merged_context: dict[str, Any] = {
        **ontology_context,
        "gold_grounding": gold_evidence,
        "gold_grounding_degraded": degraded_reason or None,
    }

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
    tool_name = _scope_or_env(
        scope,
        "gold_grounding_tool_name",
        "FABRIC_GOLD_GROUNDING_TOOL_NAME",
    ) or _DEFAULT_GOLD_TOOL_NAME
    delegated_token = _scope_or_env(
        scope,
        "fabric_delegated_token",
        "FABRIC_DELEGATED_TOKEN",
    )
    return workspace_id, data_agent_id, tool_name, delegated_token


def _scope_or_env(scope: Any, scope_attr: str, env_name: str) -> str:
    scoped = str(getattr(scope, scope_attr, "") or "").strip()
    if scoped:
        return scoped
    return os.environ.get(env_name, "").strip()


def _parse_gold_findings(result: dict[str, Any]) -> list[GoldGroundedFinding]:
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
    return parse_gold_grounded_findings("\n".join(lines), tool_call_id="gold-grounding")


def _degraded_reason_from_findings(findings: list[GoldGroundedFinding]) -> str:
    for finding in findings:
        if finding.degraded:
            return finding.degraded_reason or "unparseable Gold evidence"
    return ""


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

    trimmed_findings = [_ranked_finding(dict(finding)) for finding in findings if isinstance(finding, dict)]
    while True:
        candidate = {"findings": trimmed_findings}
        merged = {
            **ontology_context,
            "gold_grounding": candidate,
            "gold_grounding_degraded": degraded_reason or None,
        }
        merged_size = len(json.dumps(merged, default=str, ensure_ascii=False))
        gold_size = len(json.dumps(candidate, default=str, ensure_ascii=False))
        if merged_size <= _MAX_CONTEXT_CHARS and gold_size <= _GOLD_CONTEXT_BUDGET_CHARS:
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
        raise FoundryAgentError("Microsoft Agent Framework agent returned an empty answer")
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
