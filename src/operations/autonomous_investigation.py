"""Autonomous multi-agent operational investigation orchestration.

This layer coordinates specialized, deterministic agents over the governed tool
registry. Agents never access providers directly and never expose hidden
chain-of-thought; they publish tool calls, evidence, findings, disagreements,
human decisions, and evaluation metrics into an auditable task ledger.
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from api.scope import Scope
from operations.foundry_agent import SPECIALIST_CONTRACT_VERSION, specialist_catalog
from operations.maf_orchestrator import maf_mode_enabled, select_specialists_for_turn
from operations.page_context import PageSnapshot, deterministic_network_findings
from operations.tools import (
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    call_tool,
)

_LOGGER = logging.getLogger(__name__)

AGENT_TIMEOUT_SECONDS = 8.0
MAX_RETRIES = 1
MAX_LEDGER_ENTRIES = 1_000
MAX_CONTEXT_STEPS = 5
MAX_CONTEXT_SPECIALISTS = 3
MAX_CONTEXT_TOOL_CALLS = 8


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    role: str
    tools: tuple[str, ...]
    keywords: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    contract_version: str = SPECIALIST_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "tools": list(self.tools),
            "keywords": list(self.keywords),
            "depends_on": list(self.depends_on),
            "contract_version": self.contract_version,
        }


AGENTS: tuple[AgentDefinition, ...] = (
    AgentDefinition("network", "Network Agent", "Investigates topology, traffic paths, firewall/NSG gaps, and blast radius.", ("network_topology", "firewall_nsg_gaps"), ("network", "traffic", "firewall", "nsg", "route", "blast", "hub", "vnet", "subnet", "peering", "topology", "depend", "dependency", "dependencies")),
    AgentDefinition("vulnerability", "Vulnerability Agent", "Investigates CVE exposure, reachability, exploitability, and affected services.", ("cve_exposure", "risk_context"), ("cve", "vulnerab", "exploit", "exposure", "risk")),
    AgentDefinition("patch", "Patch Agent", "Investigates patch priorities, KB remediation, and validation expectations.", ("cve_exposure", "remediation_plans"), ("patch", "kb", "update", "sla")),
    AgentDefinition("incident", "Incident Agent", "Investigates incident timeline, root-cause candidates, unknowns, and validation steps.", ("incidents",), ("incident", "outage", "alert", "root cause", "timeline")),
    AgentDefinition("change", "Change Agent", "Investigates recent changes and correlates them to operational symptoms.", ("incidents", "search"), ("change", "changed", "deployment", "configuration")),
    AgentDefinition("governance", "Governance Agent", "Investigates owners, scope, approvals, exceptions, and policy/accountability context.", ("business_service_context", "application_context", "risk_context"), ("owner", "owned", "approval", "approver", "governance", "policy", "scope", "exception")),
    AgentDefinition("remediation", "Remediation Agent", "Investigates safe remediation options, rollback, validation, and governed handoff.", ("remediation_opportunities", "remediation_plans"), ("remediat", "fix", "mitigat", "rollback", "plan")),
    AgentDefinition("executive_summary", "Executive Summary Agent", "Synthesizes grounded findings into business impact, decisions, and recommended plan.", (), ("executive", "summary", "decision"), ("network", "vulnerability", "patch", "incident", "change", "governance", "remediation")),
)


def agent_catalog() -> list[dict[str, Any]]:
    configured = {item["id"]: item for item in specialist_catalog()}
    return [
        {
            **agent.to_dict(),
            "foundry": configured.get(agent.id, {"status": "unavailable"}),
        }
        for agent in AGENTS
    ]


def _extract_subject(objective: str) -> str:
    import re

    quoted = re.findall(r"[\"“]([^\"”]{2,100})[\"”]", objective)
    if quoted:
        return quoted[0].strip()
    candidates = re.findall(r"\b([A-Z][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*)*)\b", objective)
    stop = {"what", "which", "how", "why", "who", "when", "where", "cve", "kb", "prod", "uat"}
    candidates = [item for item in candidates if item.casefold() not in stop and not any(part.casefold() in stop for part in item.split())]
    return max(candidates, key=len) if candidates else ""


def _select_agents(objective: str) -> list[AgentDefinition]:
    lowered = objective.casefold()
    selected = [agent for agent in AGENTS if agent.id != "executive_summary" and any(marker in lowered for marker in agent.keywords)]
    if not selected:
        selected = [agent for agent in AGENTS if agent.id in {"network", "vulnerability", "incident", "remediation", "governance"}]
    executive = next(agent for agent in AGENTS if agent.id == "executive_summary")
    return selected + [executive]


def _select_context_specialists(
    *,
    page_kind: str,
    question: str,
    page_specialists: Mapping[str, tuple[str, ...]],
) -> list[str]:
    """Choose specialists for one page question: page anchor first, then topic.

    The page's own specialists always lead, so the drawer keeps answering as
    the specialist for the page the operator is looking at. Specialists whose
    keywords match the question are appended after them, because operators
    routinely ask cross-cutting questions without changing page -- "what
    changed recently?" asked on the Network page is a change question, and
    previously only the network specialist ever ran.

    Selection stays deterministic keyword matching over the fixed catalog: no
    model output chooses a specialist, the result is capped at
    MAX_CONTEXT_SPECIALISTS, and each specialist's tools remain scope-filtered,
    so this widens topical relevance without widening data access.

    ``executive_summary`` is excluded: it is a synthesis agent with no tools of
    its own and depends on every other specialist, so admitting it here would
    spend the budget without gathering evidence.
    """
    ordered: list[str] = []
    for specialist_id in page_specialists.get(page_kind, ()):
        if specialist_id not in ordered:
            ordered.append(specialist_id)

    lowered = question.casefold()
    for agent in AGENTS:
        if len(ordered) >= MAX_CONTEXT_SPECIALISTS:
            break
        if agent.id in ordered or agent.id == "executive_summary":
            continue
        if any(marker in lowered for marker in agent.keywords):
            ordered.append(agent.id)

    return ordered[:MAX_CONTEXT_SPECIALISTS]


def _tool_args(tool: str, objective: str, subject: str) -> dict[str, Any]:
    if tool in {"business_service_context", "application_context"}:
        return {"name": subject} if subject else {}
    if tool in {"risk_context", "impact_context"}:
        return {"subject": subject} if subject else {}
    if tool == "cve_exposure":
        return {"business_service": subject} if subject else {}
    if tool == "search":
        return {"query": objective}
    return {}


def _rows(data: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of record rows from a tool payload."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("gaps", "rule_findings", "exposures", "incidents", "plans", "opportunities", "results", "items"):
            value = data.get(key)
            if isinstance(value, list):
                rows = [row for row in value if isinstance(row, dict)]
                if rows:
                    return rows
    return []


def _label(row: Mapping[str, Any]) -> str:
    for key in ("cve_id", "kb_id", "incident_id", "title", "name", "finding_id", "gap_id", "plan_id", "id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _severity_breakdown(rows: list[dict[str, Any]]) -> str:
    """Count rows by severity so the finding states risk, not just volume."""
    counts: dict[str, int] = {}
    for row in rows:
        for key in ("severity", "priority", "risk_level", "status"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                counts[value.strip().casefold()] = counts.get(value.strip().casefold(), 0) + 1
                break
    if not counts:
        return ""
    order = {"critical": 0, "high": 1, "error": 1, "medium": 2, "warning": 2, "low": 3, "info": 4}
    ranked = sorted(counts.items(), key=lambda item: (order.get(item[0], 5), -item[1]))
    return ", ".join(f"{count} {name}" for name, count in ranked[:4])


def _examples(rows: list[dict[str, Any]], limit: int = 3) -> str:
    labels: list[str] = []
    for row in rows:
        label = _label(row)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    if not labels:
        return ""
    suffix = f" (+{len(rows) - len(labels)} more)" if len(rows) > len(labels) else ""
    return ", ".join(labels) + suffix


def _summarize_tool(tool: str, result: Any) -> str:
    """Describe what a tool actually observed, not merely how many rows it returned.

    Findings name the affected subjects and their severity mix so an operator can
    judge risk without opening the raw ledger.
    """
    if result.status != STATUS_OK:
        return result.warning or f"{tool} status: {result.status}"

    data = result.data
    rows = _rows(data)
    if not rows:
        if isinstance(data, dict) and data:
            summary = data.get("summary")
            if isinstance(summary, Mapping) and summary:
                detail = ", ".join(f"{key}={value}" for key, value in list(summary.items())[:4])
                return f"{tool}: {detail}"
            return f"{tool} returned scoped context ({len(data)} fields) with no enumerable records"
        return f"{tool} observed no scoped records"

    parts = [f"{tool}: {len(rows)} scoped record{'s' if len(rows) != 1 else ''}"]
    severity = _severity_breakdown(rows)
    if severity:
        parts.append(f"severity {severity}")
    examples = _examples(rows)
    if examples:
        parts.append(f"including {examples}")
    return " — ".join(parts)


def _snapshot_observations(snapshot: PageSnapshot) -> list[dict[str, Any]]:
    """Summarize visible page evidence for Foundry contextual narration."""
    observations: list[dict[str, Any]] = []
    for row in snapshot.evidence:
        if row.section == "source":
            continue
        data = row.data
        label = _label(data)
        summary = (
            str(
                data.get("finding")
                or data.get("issue")
                or data.get("title")
                or data.get("summary")
                or label
            ).strip()
            if isinstance(data, Mapping)
            else ""
        )
        if not summary:
            summary = f"{row.section} evidence submitted"
        observations.append(
            {
                "finding_id": f"SNAPSHOT-{row.section.upper()}:{row.evidence_id}",
                "resource_ids": [row.resource_id] if row.resource_id else [],
                "check_id": str(data.get("check") or row.section) if isinstance(data, Mapping) else row.section,
                "policy_id": str(data.get("rule_id") or data.get("policy_id") or row.section) if isinstance(data, Mapping) else row.section,
                "source_status": row.status,
                "status": "observed" if row.status == STATUS_OK else row.status,
                "summary": summary,
                "evidence_refs": [row.evidence_id],
                "confidence": str(data.get("confidence") or data.get("severity") or "medium") if isinstance(data, Mapping) else "medium",
                "uncertainty": [] if row.status == STATUS_OK else ["source did not return confirmed records"],
                "stale": row.status == STATUS_UNAVAILABLE,
                "next_check": "",
                "actionable": row.status == STATUS_OK,
                "page_kind": snapshot.page_kind,
                "details": data,
            }
        )
    return observations[:MAX_CONTEXT_TOOL_CALLS]


def _agent_run(agent: AgentDefinition, objective: str, *, context: Any, scope: Scope) -> dict[str, Any]:
    started = time.monotonic()
    subject = _extract_subject(objective)
    calls: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    status = STATUS_EMPTY

    if agent.id == "executive_summary":
        return {
            "agent_id": agent.id,
            "agent_name": agent.name,
            "status": "waiting_for_inputs",
            "started_at": _now(),
            "completed_at": _now(),
            "duration_ms": 0,
            "tool_calls": [],
            "findings": [],
            "evidence": [],
            "confidence": "medium",
            "hidden_reasoning_exposed": False,
        }

    for tool in agent.tools:
        args = _tool_args(tool, objective, subject)
        result = call_tool(tool, args, context=context, scope=scope)
        attempts = 1
        if result.status == STATUS_UNAVAILABLE:
            for _ in range(MAX_RETRIES):
                retry = call_tool(tool, args, context=context, scope=scope)
                attempts += 1
                if retry.status != STATUS_UNAVAILABLE:
                    result = retry
                    break
        call = {
            "tool": tool, "arguments": args, "status": result.status,
            "warning": result.warning, "attempts": attempts,
            "result": result.to_dict(),
        }
        calls.append(call)
        evidence.extend(item.to_dict() for item in result.evidence)
        findings.append(
            {
                "finding_id": f"{agent.id}:{tool}:{len(findings) + 1}",
                "agent_id": agent.id,
                "summary": _summarize_tool(tool, result),
                "status": result.status,
                "confidence": "high" if result.status == STATUS_OK and result.evidence else "medium" if result.status == STATUS_OK else "unknown",
                "evidence_count": len(result.evidence),
                "unsupported": result.status == STATUS_OK and not result.evidence,
            }
        )
        if result.status == STATUS_OK:
            status = STATUS_OK
        elif status != STATUS_OK and result.status in {STATUS_UNAVAILABLE, STATUS_DENIED}:
            status = "partial"

    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "status": status,
        "started_at": _now(),
        "completed_at": _now(),
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "tool_calls": calls,
        "findings": findings,
        "evidence": evidence,
        "confidence": _agent_confidence(findings),
        "hidden_reasoning_exposed": False,
    }


def _agent_confidence(findings: list[dict[str, Any]]) -> str:
    if any(item["confidence"] == "high" for item in findings):
        return "high"
    if any(item["confidence"] == "medium" for item in findings):
        return "medium"
    return "unknown"


def _reconcile(agent_runs: list[dict[str, Any]]) -> dict[str, Any]:
    findings = [finding for run in agent_runs for finding in run.get("findings", [])]
    evidence = [item for run in agent_runs for item in run.get("evidence", [])]
    missing = [call for run in agent_runs for call in run.get("tool_calls", []) if call.get("status") == STATUS_UNAVAILABLE]
    stale = [item for item in evidence if item.get("freshness") == "stale"]
    unsupported = [finding for finding in findings if finding.get("unsupported")]
    statuses = {finding.get("status") for finding in findings}
    disagreements = []
    if STATUS_OK in statuses and (STATUS_UNAVAILABLE in statuses or STATUS_DENIED in statuses):
        disagreements.append("Some agents reached evidence-backed findings while others could not access required providers.")
    if STATUS_EMPTY in statuses and STATUS_OK in statuses:
        disagreements.append("At least one agent found no scoped records while another found operational evidence.")
    return {
        "conflicts": disagreements,
        "stale_evidence": stale,
        "missing_providers": missing,
        "unsupported_conclusions": unsupported,
        "evidence_count": len(evidence),
        "reconciled_confidence": "high" if evidence and not missing and not unsupported else "medium" if evidence else "unknown",
    }


def _deterministic_plan(agent_runs: list[dict[str, Any]], reconciliation: dict[str, Any]) -> str:
    """Derive next actions from what the agents actually observed."""
    steps: list[str] = []
    missing = {str(call.get("tool")) for call in reconciliation.get("missing_providers", []) if call.get("tool")}
    if missing:
        steps.append(f"Restore or re-authorize {', '.join(sorted(missing))} before relying on this synthesis")
    if reconciliation.get("unsupported_conclusions"):
        steps.append(f"Reject or re-evidence {len(reconciliation['unsupported_conclusions'])} unsupported finding(s)")
    if reconciliation.get("stale_evidence"):
        steps.append(f"Refresh {len(reconciliation['stale_evidence'])} stale evidence item(s)")

    by_agent = {run.get("agent_id"): run for run in agent_runs}
    if (run := by_agent.get("vulnerability")) and run.get("status") == STATUS_OK:
        steps.append("Triage CVE exposure by severity and confirm reachability before patching")
    if (run := by_agent.get("network")) and run.get("status") == STATUS_OK:
        steps.append("Close firewall/NSG gaps that widen blast radius")
    if (run := by_agent.get("incident")) and run.get("status") == STATUS_OK:
        steps.append("Correlate the incident timeline against recent changes to isolate root cause")
    if (run := by_agent.get("remediation")) and run.get("status") == STATUS_OK:
        steps.append("Validate the proposed remediation plan and its rollback path")

    steps.append("Assign an accountable owner, then approve governed remediation only after validation")
    return " ".join(f"{index}. {step}." for index, step in enumerate(steps, start=1))


def _synthesis(
    objective: str,
    agent_runs: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    *,
    foundry_agent: Any = None,
) -> dict[str, Any]:
    """Build the operator-facing conclusion.

    The deterministic synthesis is always produced so the ledger stays complete
    and auditable. When a Foundry prompt agent is configured it narrates the
    already-collected, already-scoped evidence; narration never invents facts
    and never fails the investigation.
    """
    evidence_backed = [
        finding
        for run in agent_runs
        for finding in run.get("findings", [])
        if finding.get("status") == STATUS_OK and finding.get("evidence_count", 0) > 0
    ]
    unknowns = [call.get("tool") for run in agent_runs for call in run.get("tool_calls", []) if call.get("status") in {STATUS_UNAVAILABLE, STATUS_DENIED}]
    headlines = [finding.get("summary", "") for finding in evidence_backed[:6] if finding.get("summary")]

    summary = f"{len(evidence_backed)} evidence-backed findings were produced for: {objective}"
    if headlines:
        summary = f"{summary}. Key observations: " + "; ".join(headlines)

    synthesis: dict[str, Any] = {
        "summary": summary,
        "recommended_plan": _deterministic_plan(agent_runs, reconciliation),
        "required_decision": "Accept the synthesis, reject unsupported findings, or request more evidence before approving remediation.",
        "unresolved_questions": sorted({item for item in unknowns if item}),
        "confidence": reconciliation["reconciled_confidence"],
        "narration": "",
        "narrated_by": "",
        "llm_calls": 0,
    }

    if foundry_agent is None:
        return synthesis

    grounding = {
        "objective": objective,
        "findings": headlines,
        "reconciliation": {
            "conflicts": reconciliation.get("conflicts", []),
            "evidence_count": reconciliation.get("evidence_count", 0),
            "missing_providers": [call.get("tool") for call in reconciliation.get("missing_providers", [])],
            "unsupported_conclusions": len(reconciliation.get("unsupported_conclusions", [])),
        },
        "deterministic_plan": synthesis["recommended_plan"],
    }
    try:
        answer = foundry_agent.answer(
            question=(
                "Write a short operator-facing narrative (2-4 plain sentences, no "
                "bullet list, no field-name citations, no 'OBSERVED FACT/DERIVED "
                "INFERENCE/UNKNOWN' labels) that tells a service owner what this "
                "investigation found and why it matters. The findings, plan, and "
                "unresolved questions are already listed separately below your "
                "narrative, so do not restate them one-by-one -- synthesize the "
                "business impact and the single most important next action. Use "
                "only the supplied findings. Do not invent resources, CVEs, or "
                "owners."
            ),
            context=grounding,
        )
    except Exception as exc:
        _LOGGER.warning("foundry_synthesis_failed error=%s", exc, exc_info=True)
        synthesis["narration_warning"] = (
            "Foundry narration unavailable; deterministic findings returned"
        )
        return synthesis

    text = getattr(answer, "text", "") or ""
    if text.strip():
        synthesis["narration"] = text.strip()
        synthesis["narrated_by"] = getattr(answer, "agent_name", "") or "foundry"
        synthesis["llm_calls"] = 1
    return synthesis


def _quality_metrics(
    agent_runs: list[dict[str, Any]], tool_calls: list[dict[str, Any]]
) -> dict[str, Any]:
    """Score answer quality over the specialists' own findings.

    ``groundedness`` is the fraction of specialist findings backed by at least
    one piece of evidence; ``tool_correctness`` is the fraction of tool calls
    that were not denied by scope.

    Both report ``None`` rather than 0.0 when there is nothing to score. A run
    that produced no findings has not been shown to be ungrounded -- it has
    not been measured at all -- and collapsing those two cases to the same
    number would make an unmeasured run look like a failing one, which is
    exactly the kind of misreading these metrics exist to prevent.
    """
    findings = [finding for run in agent_runs for finding in run.get("findings", [])]
    grounded = [f for f in findings if f.get("evidence_count", 0) > 0]
    undenied = [c for c in tool_calls if c.get("status") != STATUS_DENIED]
    return {
        "groundedness": round(len(grounded) / len(findings), 3) if findings else None,
        "tool_correctness": (
            round(len(undenied) / len(tool_calls), 3) if tool_calls else None
        ),
        "findings_scored": len(findings),
    }


def _evaluate(started: float, agent_runs: list[dict[str, Any]], reconciliation: dict[str, Any], scope: Scope, llm_calls: int = 0) -> dict[str, Any]:
    tool_calls = [call for run in agent_runs for call in run.get("tool_calls", [])]
    grounded = [finding for run in agent_runs for finding in run.get("findings", []) if finding.get("evidence_count", 0) > 0]
    return {
        "groundedness": round(len(grounded) / max(1, sum(len(run.get("findings", [])) for run in agent_runs)), 3),
        "scope_isolation": "enforced" if scope.to_dict() else "unrestricted_admin_scope",
        "tool_correctness": round(sum(call.get("status") != STATUS_DENIED for call in tool_calls) / max(1, len(tool_calls)), 3),
        "convergence": "converged_with_open_questions" if reconciliation["missing_providers"] else "converged",
        "latency_ms": round((time.monotonic() - started) * 1000, 2),
        "cost": {"tool_calls": len(tool_calls), "agent_runs": len(agent_runs), "llm_calls": llm_calls},
    }


def _resolve_foundry_agent(context: Any, specialist_id: str | None = None) -> Any:
    """Return the configured Foundry prompt agent, or ``None`` when unavailable.

    Narration is optional: a missing or misconfigured agent must degrade to the
    deterministic synthesis rather than fail the investigation.
    """
    if specialist_id:
        specialist_provider = getattr(context, "specialist_agent", None)
        if callable(specialist_provider):
            try:
                specialist = specialist_provider(specialist_id)
            except Exception as exc:
                _LOGGER.warning(
                    "foundry_specialist_resolve_failed specialist=%s error=%s",
                    specialist_id,
                    exc,
                    exc_info=True,
                )
            else:
                if specialist is not None:
                    return specialist
    provider = getattr(context, "foundry_agent", None)
    if not callable(provider):
        return None
    try:
        return provider()
    except Exception:  # noqa: BLE001 - degrade to deterministic synthesis.
        return None


def _resolve_context_narrator(
    context: Any, selected_ids: list[str], *, prefer_copilot: bool
) -> tuple[Any | None, str]:
    """Resolve the narrator for a contextual turn.

    In MAF mode, Operations Copilot is the coordinator and the current page is
    only a context source, so prefer the generic orchestrator when present and
    otherwise use the first available selected specialist. In the legacy mode,
    preserve the page-anchored behavior exactly.
    """

    if prefer_copilot:
        agent = _resolve_foundry_agent(context)
        if agent is not None:
            return agent, "operations-copilot"
        for specialist_id in selected_ids:
            agent = _resolve_foundry_agent(context, specialist_id)
            if agent is not None:
                return agent, specialist_id
        return None, ""

    specialist_id = selected_ids[0] if selected_ids else None
    return _resolve_foundry_agent(context, specialist_id), specialist_id or ""


def run_autonomous_investigation(
    objective: str,
    *,
    context: Any,
    scope: Scope,
    principal_subject: str,
    timeout_seconds: float = AGENT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    started = time.monotonic()
    selected = _select_agents(objective)
    independent = [agent for agent in selected if not agent.depends_on and agent.id != "executive_summary"]
    agent_runs: list[dict[str, Any]] = []
    stop_reason = ""

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(independent))))
    futures = {
        executor.submit(_agent_run, agent, objective, context=context, scope=scope): agent
        for agent in independent
    }
    try:
        try:
            completed = list(concurrent.futures.as_completed(futures, timeout=timeout_seconds))
        except TimeoutError:
            completed = [future for future in futures if future.done()]
        for future in completed:
            try:
                agent_runs.append(future.result(timeout=0))
            except Exception as exc:
                agent = futures[future]
                _LOGGER.exception("agent %s failed during investigation", agent.id)
                agent_runs.append(_failed_run(agent, f"failed: {exc.__class__.__name__}: {exc}"))
        unfinished = [agent for future, agent in futures.items() if not future.done()]
        if unfinished:
            stop_reason = f"timeout after {timeout_seconds}s; unfinished agents: {', '.join(agent.id for agent in unfinished)}"
            for future in futures:
                future.cancel()
            for agent in unfinished:
                agent_runs.append(_failed_run(agent, "timed out before completing"))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    agent_runs.sort(key=lambda row: row["agent_id"])
    reconciliation = _reconcile(agent_runs)
    executive = next(agent for agent in selected if agent.id == "executive_summary")
    executive_run = _agent_run(executive, objective, context=context, scope=scope)

    # Synthesis is computed once: it may issue a Foundry narration call, and the
    # executive run must publish exactly the same conclusion the ledger reports.
    synthesis = _synthesis(objective, agent_runs, reconciliation, foundry_agent=_resolve_foundry_agent(context))
    executive_run = {
        **executive_run,
        "status": STATUS_OK,
        "findings": [
            {
                "finding_id": "executive_summary:synthesis",
                "agent_id": executive.id,
                "summary": synthesis["summary"],
                "status": STATUS_OK,
                "confidence": reconciliation["reconciled_confidence"],
                "evidence_count": reconciliation["evidence_count"],
            }
        ],
    }
    agent_runs.append(executive_run)
    ledger_id = f"mai-{uuid.uuid4().hex[:12]}"
    return {
        "ledger_id": ledger_id,
        "objective": objective,
        "scope": scope.to_dict(),
        "created_by": principal_subject,
        "created_at": _now(),
        "updated_at": _now(),
        "status": "needs_human_review" if reconciliation["missing_providers"] or reconciliation["unsupported_conclusions"] else "synthesized",
        "selected_agents": [agent.to_dict() for agent in selected],
        "agent_runs": agent_runs,
        "reconciliation": reconciliation,
        "synthesis": synthesis,
        "human_controls": {"available_actions": ["request_more_evidence", "accept_finding", "reject_finding", "assign_owner", "approve_plan", "stop_investigation"]},
        "decisions": [],
        "approvals": [],
        "outcome": "",
        "stop_reason": stop_reason,
        "evaluation": _evaluate(started, agent_runs, reconciliation, scope, int(synthesis.get("llm_calls", 0))),
    }


def run_context_investigation(
    snapshot: PageSnapshot,
    *,
    context: Any,
    scope: Scope,
    principal_subject: str,
    timeout_seconds: float = AGENT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run a bounded, deterministic-first contextual investigation loop.

    The browser snapshot is the observation.  Delegation is nevertheless real:
    selected specialists invoke only their catalogued tools, and named evidence
    requests are mapped to a small allowlist of scope-bound Network tools.
    """
    started = time.monotonic()
    findings = (
        deterministic_network_findings(snapshot)
        if snapshot.page_kind in ("network", "network_page")
        else _snapshot_observations(snapshot)
    )
    stages = ["plan", "observe"]
    tool_calls: list[dict[str, Any]] = []
    agent_runs: list[dict[str, Any]] = []
    stop_reason = "reassessed"
    warnings: list[str] = [
        f"Source {record.source} is {record.status}; findings are uncertainty-qualified"
        for record in snapshot.freshness
        if record.status != "fresh"
    ]
    # Contextual selection is anchored to the page: the page's own specialist
    # always runs first, so a Network page never stops answering as the
    # network specialist. The operator's question may then pull in additional
    # specialists, because a question asked on one page routinely spans
    # another ("what changed?" on the Network page is a change question).
    # Model output still never chooses; matching is deterministic keyword
    # matching over the same catalog, and every specialist remains bounded by
    # MAX_CONTEXT_SPECIALISTS and scope-filtered tool access.
    page_specialists = {
        # Direct page_kind → specialist mappings (preferred for Phase 09-09 expansion)
        "network_page": ("network",),
        "vulnerability_page": ("vulnerability",),
        "patch_page": ("patch",),
        "incident_page": ("incident",),
        "change_page": ("change",),
        "governance_page": ("governance",),
        "remediation_page": ("remediation",),
        "executive_summary_page": ("executive_summary",),
        # Legacy mappings (preserved for backward compatibility)
        "network": ("network",),
        "vulnerability": ("vulnerability", "patch"),
        "compliance": ("governance", "remediation"),
        "remediation": ("remediation", "governance"),
        "patch": ("patch",),
        "incident": ("incident", "change"),
        "governance": ("governance",),
        "resource": ("governance",),
    }
    selected_ids = _select_context_specialists(
        page_kind=snapshot.page_kind,
        question=snapshot.question,
        page_specialists=page_specialists,
    )
    orchestration = {
        "selected_ids": selected_ids,
        "strategy": "page_anchor_then_question",
        "runtime": "deterministic",
        "reason": "legacy page-anchored specialist selection",
    }
    if maf_mode_enabled():
        decision = select_specialists_for_turn(
            page_kind=snapshot.page_kind,
            question=snapshot.question,
            page_specialists=page_specialists,
            catalog=AGENTS,
            limit=MAX_CONTEXT_SPECIALISTS,
        )
        selected_ids = list(decision.selected_ids)
        orchestration = decision.to_dict()
    selected = [agent for agent in AGENTS if agent.id in selected_ids]
    selected.sort(key=lambda agent: selected_ids.index(agent.id))
    stages.append("delegate")
    remaining_tools = MAX_CONTEXT_TOOL_CALLS
    delegated_agent_ids: list[str] = []
    for agent in selected:
        if time.monotonic() - started >= timeout_seconds:
            stop_reason = "wall_clock_timeout"
            warnings.append("context investigation wall-clock budget exhausted")
            break
        allowed = tuple(tool for tool in agent.tools if remaining_tools)
        bounded_agent = AgentDefinition(
            agent.id, agent.name, agent.role, allowed[:remaining_tools],
            agent.keywords, agent.depends_on,
        )
        run = _agent_run(bounded_agent, snapshot.question, context=context, scope=scope)
        catalog = next((item for item in specialist_catalog() if item["id"] == agent.id), {})
        run["specialist"] = {
            "id": agent.id,
            "name": catalog.get("name") or agent.name,
            "version": catalog.get("version") or "deterministic",
            "contract_version": agent.contract_version,
        }
        agent_runs.append(run)
        tool_calls.extend({**call, "specialist": agent.id, "operation": "delegate"} for call in run["tool_calls"])
        remaining_tools -= len(run["tool_calls"])
        delegated_agent_ids.append(agent.id)

    if (
        "network" in delegated_agent_ids
        and remaining_tools
        and time.monotonic() - started < timeout_seconds
    ):
        # Fabric IQ is enrichment only, so it runs after every selected
        # specialist has had its first pass. It must never consume the bounded
        # context budget before a question-selected specialist can answer.
        subject = next(
            (resource.resource_id for resource in snapshot.selected_resources), ""
        )
        for iq_tool in (
            "fabric_iq_relationships",
            "fabric_iq_topology",
            "fabric_iq_policy_context",
        )[:remaining_tools]:
            if time.monotonic() - started >= timeout_seconds:
                break
            result = call_tool(
                iq_tool, {"subject": subject}, context=context, scope=scope
            )
            tool_calls.append({
                "tool": iq_tool,
                "arguments": {"subject": subject},
                "status": result.status,
                "warning": result.warning,
                "attempts": 1,
                "result": result.to_dict(),
                "specialist": "network",
                "operation": "enrichment",
            })
            remaining_tools -= 1

    if snapshot.rechecks and time.monotonic() - started < timeout_seconds and remaining_tools:
        stages.append("request-evidence")
        recheck_tools = {
            "network": "network_topology",
            "topology": "network_topology",
            "route": "network_topology",
            "nsg": "firewall_nsg_gaps",
            "firewall": "firewall_nsg_gaps",
        }
        for evidence_id in snapshot.rechecks[:remaining_tools]:
            if time.monotonic() - started >= timeout_seconds:
                stop_reason = "wall_clock_timeout"
                warnings.append("context investigation wall-clock budget exhausted")
                break
            row = next(row for row in snapshot.evidence if row.evidence_id == evidence_id)
            tool = recheck_tools.get(row.section.casefold())
            if tool is None:
                result = None
                status = STATUS_DENIED
                warning = "Evidence request is not allowlisted"
            else:
                result = call_tool(tool, {}, context=context, scope=scope)
                status = result.status
                warning = result.warning
            call = {
                "tool": tool or "evidence_request",
                "arguments": {"evidence_id": evidence_id},
                "status": status,
                "warning": warning,
                "attempts": 1,
                "operation": "request-evidence",
                "evidence_refs": [evidence_id],
            }
            if result is not None:
                call["result"] = result.to_dict()
            tool_calls.append(call)
            remaining_tools -= 1
    elif snapshot.rechecks:
        stop_reason = "budget_exhausted"
        warnings.append("context investigation budget exhausted before evidence requests")

    stages.append("reassess")
    if len(delegated_agent_ids) < len(selected) and time.monotonic() - started >= timeout_seconds:
        stop_reason = "wall_clock_timeout"
        warnings.append("context investigation wall-clock budget exhausted")
    # Reassessment is a fresh deterministic evaluation of the submitted state;
    # provider results remain visible as observations and never become an
    # alternate inventory identity source.
    findings = (
        deterministic_network_findings(snapshot)
        if snapshot.page_kind in ("network", "network_page")
        else _snapshot_observations(snapshot)
    )
    agent, narrator_id = _resolve_context_narrator(
        context, selected_ids, prefer_copilot=orchestration["runtime"] != "deterministic"
    )
    synthesis_mode = "deterministic"
    narration = ""
    if agent is not None:
        try:
            grounding = {
                "page_kind": snapshot.page_kind,
                "orchestration": orchestration,
                "delegated_specialists": selected_ids,
                "findings": findings,
                "tool_results": [
                    call.get("result") for call in tool_calls if call.get("result")
                ][:MAX_CONTEXT_TOOL_CALLS],
                "fabric_iq": [
                    call.get("result") for call in tool_calls
                    if str(call.get("tool", "")).startswith("fabric_iq_")
                ][:3],
            }
            answer = agent.answer(question=snapshot.question, context=grounding)
            narration = str(getattr(answer, "text", "") or "").strip()
            if narration:
                synthesis_mode = "foundry"
        except Exception as exc:
            _LOGGER.warning(
                "foundry_context_narration_failed specialist=%s error=%s",
                narrator_id,
                exc,
                exc_info=True,
            )
            warnings.append(
                "Foundry narration unavailable; deterministic findings returned"
            )
    if synthesis_mode == "deterministic" and agent is None:
        warnings.append("Foundry narration unavailable; deterministic findings returned")
    ledger_id = f"ctx-{uuid.uuid4().hex[:12]}"
    ledger = {
        "ledger_id": ledger_id,
        "objective": snapshot.question,
        "scope": scope.to_dict(),
        "created_by": principal_subject,
        "created_at": _now(),
        "updated_at": _now(),
        "status": "synthesized",
        "snapshot_hash": snapshot.snapshot_hash(),
        "snapshot_version": snapshot.version,
        "page_kind": snapshot.page_kind,
        "selected_agents": [agent.to_dict() for agent in selected],
        "stages": stages[:MAX_CONTEXT_STEPS],
        "orchestration": orchestration,
        "tool_calls": tool_calls,
        "agent_runs": agent_runs,
        "findings": findings,
        "synthesis": {
            "mode": synthesis_mode,
            "narration": narration,
            "specialist_contract_version": "",
            "warning": warnings[-1] if warnings and "Foundry" in warnings[-1] else "",
        },
        "warnings": warnings,
        "stop_reason": stop_reason,
        "human_controls": {"available_actions": ["request_more_evidence", "approve_plan", "stop_investigation"]},
        "decisions": [],
        "approvals": [],
        "evaluation": {
            "step_count": len(stages[:MAX_CONTEXT_STEPS]),
            "tool_calls": len(tool_calls),
            "specialists": len(agent_runs),
            "wall_clock_ms": round((time.monotonic() - started) * 1000, 2),
            "hidden_reasoning_exposed": False,
            "orchestration_runtime": orchestration["runtime"],
            "orchestration_strategy": orchestration["strategy"],
            # Groundedness and tool correctness were computed for autonomous
            # investigations but not for contextual ones, so the path that
            # actually serves the page drawer could not be scored -- quality
            # there could only be asserted, never measured. Same definitions
            # as `_evaluate` so the two paths stay comparable.
            #
            # Scored over the specialists' findings, not the top-level
            # `findings`: those are derived from the submitted page snapshot,
            # so a caller that posts no evidence rows would score 0.0 while
            # the specialists were in fact returning fully evidence-backed
            # answers. That measures the caller, not the agent.
            **_quality_metrics(agent_runs, tool_calls),
        },
    }
    return ledger


def _failed_run(agent: AgentDefinition, reason: str) -> dict[str, Any]:
    return {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "status": STATUS_UNAVAILABLE,
        "started_at": _now(),
        "completed_at": _now(),
        "duration_ms": 0,
        "tool_calls": [],
        "findings": [
            {
                "finding_id": f"{agent.id}:failure",
                "agent_id": agent.id,
                "summary": f"{agent.name} {reason}",
                "status": STATUS_UNAVAILABLE,
                "confidence": "unknown",
                "evidence_count": 0,
            }
        ],
        "evidence": [],
        "confidence": "unknown",
        "hidden_reasoning_exposed": False,
    }


class LedgerDocumentStore(Protocol):
    """The subset of ``OneLakeDocumentStore`` the ledger needs.

    Declared structurally so tests can substitute a dictionary-backed double
    without importing the storage layer.
    """

    def read(self, name: str) -> dict[str, Any]: ...

    def put(self, name: str, payload: dict[str, Any]) -> None: ...


def _ledger_document_name(ledger_id: str) -> str:
    """Map a ledger id to its document path.

    One document per ledger rather than a single collection document. A ledger
    carries full tool-call payloads and findings, so a combined document would
    force a read-modify-write of the entire audit history on every
    investigation and put every replica in compare-and-swap contention. Ledger
    ids are server-generated (``mai-<uuid12>``), so writes never collide and
    ``put`` is safe: two writers cannot target the same document.
    """
    return f"ledgers/{ledger_id}.json"


@dataclass
class InvestigationLedgerStore:
    """Principal-scoped ledger store for autonomous investigations.

    Ledgers are the audit trail for operator decisions taken against
    production infrastructure, so they are retained indefinitely and are never
    evicted. When a ``documents`` store is supplied every ledger is persisted
    as its own OneLake document and survives replica restarts; the in-memory
    map is then a read-through cache. Without one -- local development and
    most tests -- behaviour falls back to the previous bounded in-memory store
    so nothing grows without limit in a process that has no durable home.
    """

    max_entries: int = MAX_LEDGER_ENTRIES
    ledgers: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)
    documents: LedgerDocumentStore | None = None

    @property
    def is_durable(self) -> bool:
        return self.documents is not None

    def _persist(self, ledger: dict[str, Any]) -> None:
        """Write the ledger through to durable storage, best-effort.

        A storage outage must not fail the investigation the operator is
        running, so persistence failures are logged and the in-memory copy is
        still served. The warning is the signal that the audit trail has a
        hole in it.
        """
        if self.documents is None:
            return
        try:
            self.documents.put(_ledger_document_name(ledger["ledger_id"]), ledger)
        except Exception:
            _LOGGER.warning(
                "failed to persist investigation ledger %s; it exists only in memory",
                ledger["ledger_id"],
                exc_info=True,
            )

    def add(self, ledger: dict[str, Any]) -> dict[str, Any]:
        self.ledgers[ledger["ledger_id"]] = ledger
        self.ledgers.move_to_end(ledger["ledger_id"])
        # Eviction bounds memory only. A durable store keeps every ledger, so
        # evicting here costs nothing: `get` re-reads it on demand.
        while len(self.ledgers) > self.max_entries:
            self.ledgers.popitem(last=False)
        self._persist(ledger)
        return ledger

    def get(self, ledger_id: str, principal_subject: str) -> dict[str, Any] | None:
        ledger = self.ledgers.get(ledger_id)
        if ledger is None and self.documents is not None:
            ledger = self._load(ledger_id)
        if ledger is None or ledger.get("created_by") != principal_subject:
            return None
        return ledger

    def _load(self, ledger_id: str) -> dict[str, Any] | None:
        """Rehydrate an evicted or another replica's ledger from storage."""
        assert self.documents is not None
        try:
            payload = self.documents.read(_ledger_document_name(ledger_id))
        except Exception:
            _LOGGER.warning("failed to read investigation ledger %s", ledger_id, exc_info=True)
            return None
        # The document store reads a missing *or corrupt* document as {}. For a
        # cache that is fine; for an audit record it is not, so require the
        # identity to match rather than trusting whatever came back.
        if not payload or payload.get("ledger_id") != ledger_id:
            return None
        self.ledgers[ledger_id] = payload
        self.ledgers.move_to_end(ledger_id)
        while len(self.ledgers) > self.max_entries:
            self.ledgers.popitem(last=False)
        return payload

    def record_decision(self, ledger_id: str, principal_subject: str, action: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        ledger = self.get(ledger_id, principal_subject)
        if ledger is None:
            return None
        decision = {"at": _now(), "action": action, "payload": payload}
        ledger["decisions"].append(decision)
        if action == "approve_plan":
            ledger["approvals"].append(decision)
        if action == "stop_investigation":
            ledger["status"] = "stopped"
            ledger["stop_reason"] = str(payload.get("reason") or "Stopped by human operator")
        elif action in {"accept_finding", "reject_finding", "assign_owner", "request_more_evidence"}:
            ledger["status"] = "human_review_in_progress"
        ledger["updated_at"] = _now()
        # An approval that vanishes on restart is worse than no approval at
        # all, so decisions are written through like the initial ledger.
        self._persist(ledger)
        return ledger


_LEDGER_STORE = InvestigationLedgerStore()


def ledger_store() -> InvestigationLedgerStore:
    return _LEDGER_STORE


def configure_ledger_store(documents: LedgerDocumentStore | None) -> InvestigationLedgerStore:
    """Attach durable storage to the process-wide ledger store.

    Called once during API startup. Ledgers already held in memory are flushed
    so a store configured after the first investigation does not leave a gap
    at the head of the audit trail.
    """
    _LEDGER_STORE.documents = documents
    if documents is not None:
        for ledger in list(_LEDGER_STORE.ledgers.values()):
            _LEDGER_STORE._persist(ledger)
    return _LEDGER_STORE
