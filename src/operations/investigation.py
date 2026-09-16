"""Multi-step Operations Copilot investigation loop.

This is the orchestrator that turns a single question into a bounded sequence
of governed tool calls followed by one narration. It is deliberately a plain
Python loop rather than native Foundry tool-calling: the platform's non-
negotiable is "Foundry never touches Azure or Fabric directly", and a
Python-side planner keeps every retrieval on the exact same code path
(``operations.tools.call_tool``) that already applies scope filtering and
evidence stamping, regardless of which model is behind the agent.

Each turn:

1. Selects up to :data:`MAX_TOOL_CALLS` tools with a small heuristic planner
   (keyword rules over the question), calling only tools relevant to the
   question rather than every tool every time. If the caller already knows
   which tool to use (a UI "starter question" can carry a hint), that skips
   planning.
2. Executes each selected tool through the governed registry, per-call scoped
   to the caller's effective :class:`Scope`.
3. Assembles a compact, evidence-carrying context (never raw provider dumps)
   and asks the Foundry agent to narrate it, or degrades to a fact-only
   answer when no agent is configured or the agent fails.
4. Records the turn in bounded, per-session conversation state so a follow-up
   question ("what about the other subscription?") can reference prior
   findings without re-running every tool, while never leaking one user's
   session into another's.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from api.scope import Scope
from operations.foundry_agent import FoundryAgentError
from operations.tools import (
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    ToolResult,
    call_tool,
    tool_catalog,
)

_LOGGER = logging.getLogger(__name__)

# Tool-call budget per turn. Bounds both latency and the size of the context
# handed to the narration model; a question needing more than this is reported
# as partial rather than silently truncated mid-investigation.
MAX_TOOL_CALLS = 5

# Bounds how many prior turns are kept per session, and how long a session may
# sit idle before it is evicted -- "bounded" conversation state, not unlimited.
MAX_TURNS_PER_SESSION = 12
MAX_SESSIONS = 2_000
SESSION_TTL_SECONDS = 60 * 60  # 1 hour


# ---------------------------------------------------------------------------
# Planner: question -> ordered tool calls
# ---------------------------------------------------------------------------

# Keyword -> (tool name, argument builder). Order matters: the first matching
# rules win, and at most MAX_TOOL_CALLS are kept. This is intentionally a
# simple, auditable heuristic rather than a second LLM call -- tool selection
# must be deterministic and cheap so it can be evaluated (see the eval suite)
# and never itself invents an argument the question didn't contain.
def _extract_quoted_or_capitalized(question: str) -> str:
    """Best-effort subject extraction: a quoted phrase, else the longest
    capitalized run of words (crude but auditable; the tool itself returns
    STATUS_EMPTY if the guess is wrong, so a bad extraction never fabricates
    an answer).
    """
    import re

    quoted = re.findall(r"[\"“]([^\"”]{2,80})[\"”]", question)
    if quoted:
        return quoted[0].strip()
    stopwords = {
        "cve",
        "kb",
        "uat",
        "prod",
        "which",
        "what",
        "who",
        "when",
        "where",
        "how",
        "why",
        "can",
        "does",
        "is",
        "are",
        "the",
    }
    capitalized = re.findall(r"\b([A-Z][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*)*)\b", question)
    candidates = [
        candidate.strip()
        for candidate in capitalized
        if candidate.casefold() not in stopwords
        and not any(word.casefold() in stopwords for word in candidate.split())
    ]
    if candidates:
        return max(candidates, key=len)
    return ""


def _plan(question: str) -> list[tuple[str, dict[str, Any]]]:
    """Return an ordered, budgeted list of (tool_name, args) to execute."""
    lowered = question.casefold()
    subject = _extract_quoted_or_capitalized(question)
    plan: list[tuple[str, dict[str, Any]]] = []

    def add(name: str, args: dict[str, Any]) -> None:
        if len(plan) < MAX_TOOL_CALLS and not any(existing[0] == name for existing in plan):
            plan.append((name, args))

    # "Can UAT reach PROD" / "traffic from X to Y" style reachability question.
    reach_markers = ("reach", "traffic", "connect to", "can talk to", "flow")
    if any(marker in lowered for marker in reach_markers):
        import re

        endpoints = re.findall(r"\b(uat|prod|production|dev|staging|test)\b", lowered)
        if len(endpoints) >= 2:
            add("traffic_flow", {"source": endpoints[0], "destination": endpoints[1]})
        add("network_topology", {})
        add("firewall_nsg_gaps", {})

    if "hub" in lowered and ("firewall" in lowered or "depend" in lowered):
        add("network_topology", {})
        if subject:
            add("hub_dependents", {"vnet_id": subject})
        add("firewall_nsg_gaps", {})

    if "cve" in lowered or "vulnerab" in lowered or "patch" in lowered or "kb" in lowered:
        import re

        cve_ids = re.findall(r"\bCVE-\d{4}-\d{4,7}\b", question, flags=re.IGNORECASE)
        kb_ids = re.findall(r"\bKB\d{4,}\b", question, flags=re.IGNORECASE)
        if cve_ids:
            add("cve_detail", {"cve_id": cve_ids[0]})
            add("cve_attack_path", {"cve_id": cve_ids[0]})
        elif kb_ids:
            add("kb_detail", {"kb_id": kb_ids[0].upper()})
        elif "kb" in lowered or "patch" in lowered:
            add("patch_priorities", {})
        else:
            add("cve_exposure", {"business_service": subject} if subject else {})
            if subject:
                add("risk_context", {"subject": subject})

    if "incident" in lowered or "outage" in lowered or "what changed" in lowered:
        import re

        incident_ids = re.findall(r"\bINC-[A-Za-z0-9-]+\b", question, flags=re.IGNORECASE)
        add("incidents", {"incident_id": incident_ids[0]} if incident_ids else {})

    inventory_markers = ("vm", "vms", "virtual machine", "server", "servers", "storage account", "list of resources", "show resources")
    if any(marker in lowered for marker in inventory_markers):
        resource_type = ""
        if "vm" in lowered or "virtual machine" in lowered or "server" in lowered:
            resource_type = "Microsoft.Compute/virtualMachines"
        elif "storage account" in lowered:
            resource_type = "Microsoft.Storage/storageAccounts"
        add("inventory_resources", {"resource_type": resource_type} if resource_type else {})

    if "remediat" in lowered or "should be fixed" in lowered or "prioritiz" in lowered:
        add("remediation_opportunities", {})
        add("remediation_plans", {})

    if "depend" in lowered and subject:
        add("impact_context", {"subject": subject})

    if not plan and subject:
        # Generic "tell me about X" -- try both context shapes; empty results
        # from one do not block the other, and the narration step reports
        # whichever came back.
        add("business_service_context", {"name": subject})
        add("application_context", {"name": subject})
        add("risk_context", {"subject": subject})

    if not plan:
        add("search", {"query": question})

    return plan[:MAX_TOOL_CALLS]


# ---------------------------------------------------------------------------
# Investigation execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCallRecord:
    """One executed tool call, kept for citations and session recall."""

    tool: str
    arguments: dict[str, Any]
    result: ToolResult

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "arguments": self.arguments, **self.result.to_dict()}


@dataclass(frozen=True)
class Investigation:
    """The outcome of one Copilot turn."""

    question: str
    calls: tuple[ToolCallRecord, ...]
    answer: dict[str, Any] | None
    fact_status: str  # ok | partial | empty | unavailable
    warnings: tuple[str, ...] = ()
    selected_specialist: str | None = None
    deterministic_answer: bool = False

    def to_dict(self) -> dict[str, Any]:
        citations = _legacy_citations(self.calls)
        freshness = _legacy_freshness(self.calls)
        uncertainty = list(self.warnings)
        return {
            "contract_version": "1",
            "question": self.question,
            "tool_calls": [call.to_dict() for call in self.calls],
            "answer": self.answer,
            "fact_status": self.fact_status,
            "warnings": uncertainty,
            "selected_specialist": self.selected_specialist,
            "selected_specialists": (
                [self.selected_specialist] if self.selected_specialist else []
            ),
            "selected_tools": [call.tool for call in self.calls],
            "policy_status": "fallback",
            "fallback_reason": "compatibility_rollout",
            "coverage": _legacy_coverage(self.calls),
            "freshness": freshness,
            "citations": citations,
            "uncertainty": uncertainty,
            "synthesis": _legacy_synthesis(
                self.answer,
                citations=citations,
                deterministic=self.deterministic_answer,
                freshness=freshness,
                uncertainty=uncertainty,
                selected_specialist=self.selected_specialist,
            ),
            "mutation_authorized": False,
        }


def _legacy_citations(calls: Sequence[ToolCallRecord]) -> list[dict[str, str]]:
    """Project governed tool evidence into the dedicated surface citation wire."""
    citations: list[dict[str, str]] = []
    for call_index, call in enumerate(calls):
        data = call.result.data if isinstance(call.result.data, Mapping) else {}
        query_version = str(data.get("query_version") or "")
        if not call.result.evidence:
            citations.append(
                {
                    "citation_id": f"legacy:{call_index}:status:{call.tool}",
                    "source": f"tool:{call.tool}",
                    "status": call.result.status,
                    "observed_at": "",
                    "query_version": query_version,
                    "resource_id": "",
                }
            )
            continue
        for evidence_index, evidence in enumerate(call.result.evidence):
            citations.append(
                {
                    "citation_id": (
                        f"legacy:{call_index}:{evidence_index}:{call.tool}"
                    ),
                    "source": "/".join(
                        part
                        for part in (
                            evidence.source_engine,
                            evidence.source_table,
                        )
                        if part
                    ),
                    "status": call.result.status,
                    "observed_at": evidence.timestamp,
                    "query_version": query_version,
                    "resource_id": evidence.resource_id,
                }
            )
    return citations


def _legacy_coverage(calls: Sequence[ToolCallRecord]) -> dict[str, Any]:
    """Summarize bounded per-tool record coverage without entity joins."""
    visible_count = 0
    total_count = 0
    complete = bool(calls)
    list_keys = (
        "resources",
        "items",
        "results",
        "records",
        "gaps",
        "incidents",
        "plans",
        "findings",
    )
    total_keys = ("total", "total_count", "count")

    for call in calls:
        data = call.result.data if isinstance(call.result.data, Mapping) else {}
        visible = next(
            (
                len(value)
                for key in list_keys
                if isinstance((value := data.get(key)), list)
            ),
            None,
        )
        total = next(
            (
                value
                for key in total_keys
                if (value := _nonnegative_int(data.get(key))) is not None
            ),
            None,
        )
        if visible is None:
            visible = 0
            if call.result.status != STATUS_EMPTY:
                complete = False
        if total is None or total < visible:
            total = visible
            complete = False
        visible_count += visible
        total_count += total
        if (
            call.result.status not in {STATUS_OK, STATUS_EMPTY}
            or total != visible
            or "truncat" in call.result.warning.casefold()
        ):
            complete = False
    if len(calls) > 1:
        complete = False

    return {
        "visible_count": visible_count,
        "total_count": total_count,
        "complete": complete,
        "basis": "bounded_tool_record_sum",
    }


def _legacy_freshness(
    calls: Sequence[ToolCallRecord],
) -> list[dict[str, str]]:
    """Return source-specific freshness projected from governed evidence."""
    freshness: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for call in calls:
        for evidence in call.result.evidence:
            if (
                evidence.freshness
                not in {"fresh", "aging", "stale", "partial", "unavailable"}
            ):
                continue
            source = "/".join(
                part
                for part in (evidence.source_engine, evidence.source_table)
                if part
            )
            key = (source, evidence.timestamp, evidence.freshness)
            if key in seen:
                continue
            seen.add(key)
            freshness.append(
                {
                    "source": source,
                    "observed_at": evidence.timestamp,
                    "status": evidence.freshness,
                }
            )
    return freshness


def _legacy_synthesis(
    answer: Mapping[str, Any] | None,
    *,
    citations: Sequence[Mapping[str, str]],
    deterministic: bool,
    freshness: Sequence[Mapping[str, str]],
    uncertainty: Sequence[str],
    selected_specialist: str | None,
) -> dict[str, Any]:
    """Close a compatibility narration over its governed evidence citations."""
    citation_ids = []
    for citation in citations:
        citation_id = str(citation.get("citation_id") or "")
        if not citation_id:
            continue
        if not deterministic and ":status:" in citation_id:
            continue
        citation_ids.append(citation_id)
    text = str((answer or {}).get("text") or "").strip()
    if not text or not citation_ids:
        return {
            "status": "degraded",
            "reason": "citation_closed_narration_unavailable",
            "domain_count": 1 if selected_specialist else 0,
            "claims": [],
            "warning": (
                "Compatibility tool evidence is shown without an uncited "
                "narrative claim."
            ),
        }
    freshness_states = {
        str(record.get("status") or "unknown") for record in freshness
    }
    if "stale" in freshness_states:
        claim_freshness = "stale"
    elif "aging" in freshness_states:
        claim_freshness = "aging"
    elif "partial" in freshness_states:
        claim_freshness = "partial"
    elif freshness_states == {"fresh"}:
        claim_freshness = "fresh"
    else:
        claim_freshness = "unknown"
    return {
        "status": "deterministic" if deterministic else "synthesized",
        "reason": "compatibility_citation_projection",
        "domain_count": 1 if selected_specialist else 0,
        "claims": [
            {
                "finding_id": "legacy:compatibility:answer",
                "summary": text,
                "evidence_refs": citation_ids,
                "confidence": "medium",
                "freshness": claim_freshness,
                "uncertainty": list(uncertainty),
            }
        ],
        "warning": (
            "Compatibility orchestration used governed local tools; citations "
            "were projected from those tool results."
        ),
    }


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _failed_patch_starter_answer(
    question: str,
    calls: Sequence[ToolCallRecord],
) -> dict[str, Any] | None:
    """Return a fail-closed answer for aggregate failed-patch server intent."""
    tool_names = {call.tool for call in calls}
    if tool_names != {"patch_priorities", "inventory_resources"}:
        return None

    by_tool = {call.tool: call for call in calls}
    patch_call = by_tool.get("patch_priorities")
    inventory_call = by_tool.get("inventory_resources")
    patch_data = (
        patch_call.result.data
        if patch_call is not None and isinstance(patch_call.result.data, Mapping)
        else {}
    )
    inventory_data = (
        inventory_call.result.data
        if inventory_call is not None
        and isinstance(inventory_call.result.data, Mapping)
        else {}
    )
    patch_count = _nonnegative_int(patch_data.get("total_count"))
    inventory_count = _nonnegative_int(inventory_data.get("total"))

    statements: list[str] = []
    if patch_count is not None:
        statements.append(
            f"Patch priority evidence lists {patch_count} record"
            f"{'' if patch_count == 1 else 's'}, but it does not include "
            "per-server resource identifiers."
        )
    elif patch_call is not None and patch_call.result.status == STATUS_UNAVAILABLE:
        statements.append("Patch priority evidence is unavailable.")
    else:
        statements.append(
            "Patch priority evidence does not provide a valid record count or "
            "per-server resource identifiers."
        )

    if inventory_count is not None:
        statements.append(
            f"Inventory separately lists {inventory_count} resource record"
            f"{'' if inventory_count == 1 else 's'}."
        )
    elif inventory_call is not None and inventory_call.result.status == STATUS_UNAVAILABLE:
        statements.append("Resource inventory is unavailable.")
    else:
        statements.append("Resource inventory has no valid total.")

    statements.append(
        "No specific resource can be confirmed as having a failed patch from "
        "the available evidence."
    )
    warnings = [
        call.result.warning.strip()
        for call in calls
        if call.result.warning.strip()
    ]
    if warnings:
        statements.append(" ".join(dict.fromkeys(warnings)))

    return {
        "text": " ".join(statements),
        "agent_name": "patch",
        "model": "deterministic",
        "grounded": True,
        "agent_version": "",
    }


def _status_only_answer(
    calls: Sequence[ToolCallRecord],
) -> dict[str, Any] | None:
    """Describe provider status only when no factual evidence was returned."""
    if (
        not calls
        or any(call.result.evidence for call in calls)
        or any(
            call.result.status not in {STATUS_EMPTY, STATUS_UNAVAILABLE, STATUS_DENIED}
            for call in calls
        )
    ):
        return None
    status_counts = Counter(call.result.status for call in calls)
    statuses = []
    for status, count in sorted(status_counts.items()):
        lookup = f"{count} governed lookup{'' if count == 1 else 's'}"
        if status == STATUS_EMPTY:
            statuses.append(f"{lookup} found no matching records")
        elif status == STATUS_UNAVAILABLE:
            statuses.append(
                f"{lookup} could not access required provider data"
            )
        else:
            statuses.append(
                f"{lookup} {'was' if count == 1 else 'were'} not permitted "
                "for the current scope"
            )
    return {
        "text": (
            f"{'; '.join(statuses)}. "
            "No provider-backed records were returned, "
            "so the requested operational facts cannot be determined."
        ),
        "agent_name": "operations-copilot",
        "model": "deterministic",
        "grounded": True,
        "agent_version": "",
    }


def _overall_status(calls: list[ToolCallRecord]) -> str:
    if not calls:
        return STATUS_EMPTY
    statuses = {call.result.status for call in calls}
    if statuses == {STATUS_EMPTY}:
        return STATUS_EMPTY
    if STATUS_OK in statuses and (STATUS_UNAVAILABLE in statuses or STATUS_DENIED in statuses):
        return "partial"
    if STATUS_OK in statuses:
        return STATUS_OK
    if STATUS_UNAVAILABLE in statuses:
        return STATUS_UNAVAILABLE
    return STATUS_DENIED


def _specialist_agent_for_context(
    question: str, page_kind: str | None = None
) -> str | None:
    """Select specialist agent by page context or question keywords.

    Returns agent id (e.g., "vulnerability", "patch") if a specialist match is found,
    else None (fallback to generic Copilot agent).

    Mapping:
    - page_kind takes priority (e.g., vulnerability_page → vulnerability)
    - Otherwise keyword matching against question
    - Fallback order: network, then None (generic)
    """
    if not page_kind and not question:
       return None

    # Page context takes absolute priority
    page_to_agent = {
       "vulnerability_page": "vulnerability",
       "patch_page": "patch",
       "incident_page": "incident",
       "change_page": "change",
       "governance_page": "governance",
       "remediation_page": "remediation",
       "executive_summary_page": "executive_summary",
       "network_page": "network",
    }
    if page_kind and page_kind in page_to_agent:
       return page_to_agent[page_kind]

    # Fallback: keyword matching
    q_lower = question.lower()
    keywords = {
       "vulnerability": ("cve", "vulnerab", "exploit", "exposure", "risk"),
       "patch": ("patch", "kb", "update", "sla"),
       "incident": ("incident", "outage", "alert", "root cause", "timeline"),
       "change": ("change", "changed", "deployment", "configuration"),
       "governance": ("owner", "approval", "governance", "policy", "scope", "exception"),
       "remediation": ("remediat", "fix", "mitigat", "rollback", "plan"),
       "executive_summary": ("executive", "summary", "decision"),
       "network": ("network", "traffic", "firewall", "nsg", "route", "blast", "hub"),
    }
    for agent_id, agent_keywords in keywords.items():
       if any(kw in q_lower for kw in agent_keywords):
           return agent_id

    return None


def _narration_context(calls: list[ToolCallRecord]) -> dict[str, Any]:
    """Compact, labeled context for the model -- observed facts only.

    Every entry is tagged with its own status so the agent's system prompt
    (which requires it to distinguish observed fact from unknown) has the
    signal to do so per-tool rather than for the turn as a whole.
    """
    return {
        "facts": [
            {
                "tool": call.tool,
                "status": call.result.status,
                "data": call.result.data,
                "warning": call.result.warning,
            }
            for call in calls
        ]
    }


def run_investigation(
    question: str,
    *,
    context: Any,
    scope: Scope,
    principal: Any | None = None,
    hint_tool: str | None = None,
    hint_args: dict[str, Any] | None = None,
    planned_calls: Sequence[tuple[str, dict[str, Any]]] | None = None,
    page_kind: str | None = None,
) -> Investigation:
    """Plan, execute, and narrate one Copilot turn.

    ``hint_tool``/``hint_args`` let a UI "starter question" bypass the
    heuristic planner and call a known tool directly (e.g. a button on the
    vulnerability page that always means ``cve_exposure``).

    ``page_kind`` (e.g., "vulnerability_page") routes to a specialist agent
    instead of the generic Copilot agent.
    """
    plan = (
        [(hint_tool, hint_args or {})]
        if hint_tool
        else list(planned_calls)
        if planned_calls is not None
        else _plan(question)
    )
    calls: list[ToolCallRecord] = []
    for name, args in plan:
        result = call_tool(
            name,
            args,
            context=context,
            scope=scope,
            principal=principal,
        )
        calls.append(ToolCallRecord(tool=name, arguments=dict(args), result=result))

    fact_status = _overall_status(calls)
    warnings: list[str] = []
    for call in calls:
        if call.result.status == STATUS_UNAVAILABLE:
            warnings.append(
                f"{call.tool}: {call.result.warning or 'provider unavailable'}"
            )
        elif call.result.status == STATUS_DENIED:
            warnings.append(
                f"{call.tool}: "
                f"{call.result.warning or 'not permitted for this scope'}"
            )
        elif call.result.warning:
            warnings.append(f"{call.tool}: {call.result.warning}")

    answer = _failed_patch_starter_answer(question, calls)
    if answer is None:
        answer = _status_only_answer(calls)
    deterministic_answer = answer is not None

    specialist_id = _specialist_agent_for_context(question, page_kind)
    if answer is None and specialist_id and hasattr(context, "specialist_agent"):
        agent = context.specialist_agent(specialist_id)
    elif answer is None and hasattr(context, "foundry_agent"):
        agent = context.foundry_agent()
    else:
        agent = None

    if answer is None and (fact_status in (STATUS_OK, "partial") or calls):
        if agent is None:
            warnings.append(
                "No Foundry prompt agent is configured; returning tool results without narration."
            )
        else:
            try:
                narration_context = _narration_context(calls)
                agent_answer = agent.answer(question=question, context=narration_context)
                answer = agent_answer.to_dict()
            except FoundryAgentError as exc:
                _LOGGER.warning("copilot_narration_failed specialist=%s error=%s", specialist_id, exc)
                if getattr(context, "provider_runtime", None) is not None:
                    context.provider_runtime.record_failure("copilot", exc)
                warnings.append("The Foundry prompt agent could not be reached; showing tool results only.")

    return Investigation(
        question=question,
        calls=tuple(calls),
        answer=answer,
        fact_status=fact_status,
        warnings=tuple(warnings),
        selected_specialist=specialist_id,
        deterministic_answer=deterministic_answer,
    )


# ---------------------------------------------------------------------------
# Bounded per-session conversation state
# ---------------------------------------------------------------------------


@dataclass
class _SessionState:
    principal_subject: str
    turns: list[dict[str, Any]] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)


class ConversationStore:
    """In-process, bounded conversation state, keyed by (principal, session).

    Every entry is stamped with the owning principal's subject; a lookup for a
    session id under a different principal is treated as a miss, which is
    what prevents one signed-in user's investigation state from leaking into
    another's turn even if a session id were guessed or replayed. State is
    bounded on three axes: turns kept per session, sessions kept overall (an
    LRU eviction), and idle time (a TTL sweep on write), so this can never
    grow unbounded in a long-lived process.
    """

    def __init__(
        self,
        *,
        max_sessions: int = MAX_SESSIONS,
        max_turns: int = MAX_TURNS_PER_SESSION,
        ttl_seconds: float = SESSION_TTL_SECONDS,
    ) -> None:
        self._max_sessions = max_sessions
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [
            key
            for key, state in self._sessions.items()
            if now - state.last_seen > self._ttl_seconds
        ]
        for key in expired:
            del self._sessions[key]

    def record(
        self, session_id: str, principal_subject: str, investigation: Investigation
    ) -> None:
        if not session_id:
            return
        with self._lock:
            self._evict_expired()
            state = self._sessions.get(session_id)
            if state is None or state.principal_subject != principal_subject:
                state = _SessionState(principal_subject=principal_subject)
            state.turns.append(investigation.to_dict())
            state.turns = state.turns[-self._max_turns :]
            state.last_seen = time.time()
            self._sessions[session_id] = state
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def history(self, session_id: str, principal_subject: str) -> list[dict[str, Any]]:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None or state.principal_subject != principal_subject:
                return []
            return list(state.turns)

    def clear(self, session_id: str, principal_subject: str) -> None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is not None and state.principal_subject == principal_subject:
                del self._sessions[session_id]


# Process-wide singleton: conversation state is a runtime concern (like
# ProviderRuntime), not per-request, so it must survive across requests within
# one process while staying bounded as above.
_CONVERSATION_STORE = ConversationStore()


def conversation_store() -> ConversationStore:
    return _CONVERSATION_STORE


# ---------------------------------------------------------------------------
# Canonical compatibility projection (Plan 11-03)
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "1"


def canonicalize_investigation(investigation: Investigation) -> dict[str, Any]:
    """Project an Investigation result into the canonical wire contract.

    The legacy ``to_dict`` shape is preserved so existing clients are not
    broken; only ``contract_version`` is added to signal the canonical path.
    """
    result = investigation.to_dict()
    result["contract_version"] = CONTRACT_VERSION
    return result


__all__ = [
    "CONTRACT_VERSION",
    "MAX_TOOL_CALLS",
    "MAX_TURNS_PER_SESSION",
    "ConversationStore",
    "Investigation",
    "ToolCallRecord",
    "canonicalize_investigation",
    "conversation_store",
    "run_investigation",
    "tool_catalog",
]
