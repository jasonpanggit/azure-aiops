"""Operations Copilot route.

The Copilot is a *narration* layer over the Semantic Knowledge Layer, not a
second source of truth. One request does two things in order:

1. Retrieve governed operational context through :class:`SemanticEngine` — the
   same call the ``/search`` route makes, so the Copilot is subject to the
   identical scope filtering and evidence contract.
2. Ask the configured Azure AI Foundry prompt agent to narrate *only* that
   context.

If no agent is configured, or the agent call fails, the route still returns the
retrieved results and records a warning. A degraded answer with visible
evidence is strictly better than a 502 for an assistant surface.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from operations.foundry_agent import FoundryAgentError
from operations.investigation import (
    conversation_store,
    run_investigation,
    tool_catalog,
)

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope, scope_attributes

logger = logging.getLogger("hermes.api.copilot")
audit_logger = logging.getLogger("hermes.api.copilot.audit")

router = APIRouter(prefix="/api/v1", tags=["copilot"])

SOURCE_ENGINE = "semantic.SemanticEngine"
NARRATION_ENGINE = "operations.FoundryPromptAgent"

# Per-turn wall-clock budget for the whole investigation (planning + every
# tool call + narration). A question that cannot be answered inside this
# budget is reported as partial rather than left to hang the request.
INVESTIGATION_TIMEOUT_SECONDS = 20.0

# `SemanticEngine.search` returns its hits under `items`. `results` is accepted
# too so the route keeps working if the engine is ever normalized to the name
# used by the public API contract.
_RESULT_KEYS = ("items", "results")


class CopilotRequest(BaseModel):
    """A single Copilot turn."""

    question: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "An operational question. Retrieval is intent-driven (see /search); "
            "an unsupported intent is reported as a warning rather than answered "
            "from the model's own knowledge."
        ),
    )


class InvestigationRequest(BaseModel):
    """A multi-step Copilot turn: plan tools, execute, narrate."""

    question: str = Field(min_length=1, max_length=1024)
    session_id: str = Field(
        default="",
        max_length=128,
        description="Optional bounded conversation id, scoped to the caller.",
    )
    tool: str = Field(
        default="",
        max_length=64,
        description="Optional tool name a UI starter question already knows to call, bypassing the planner.",
    )
    tool_arguments: dict[str, Any] = Field(default_factory=dict)


_HIDDEN = object()


def _filter_scoped(value: Any, scope: Scope) -> Any:
    """Recursively drop entities the caller is not entitled to see.

    Applied to the *whole* retrieval payload, not just the top-level hit list:
    the engine nests entities under several keys, and a filter that only walked
    one of them would leak out-of-scope facts into the model prompt.
    """
    if isinstance(value, dict):
        attributes = scope_attributes(value)
        if attributes and not scope.matches(attributes):
            return _HIDDEN
        return {
            key: filtered
            for key, child in value.items()
            if (filtered := _filter_scoped(child, scope)) is not _HIDDEN
        }
    if isinstance(value, list):
        return [
            filtered
            for child in value
            if (filtered := _filter_scoped(child, scope)) is not _HIDDEN
        ]
    return value


def _results_of(payload: dict[str, Any]) -> list[Any]:
    """Extract the hit list under whichever key the engine used."""
    for key in _RESULT_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


@router.post("/copilot/ask", summary="Ask the Operations Copilot")
def ask(payload: CopilotRequest, context: Context, scope: ReadScope) -> dict[str, Any]:
    """Answer an operational question from governed context.

    Returns the retrieved rows alongside the narrated answer so the UI can show
    both the prose and the underlying evidence.
    """
    question = payload.question.strip()
    warnings: list[str] = []

    try:
        subscription_ids = list(scope.values("subscription"))
        live_search = question.casefold().strip().startswith("show list of") and (
            "vm" in question.casefold() or "server" in question.casefold()
        )
        if (
            context.hybrid_search_provider is not None
            and subscription_ids
            and live_search
        ):
            retrieved = context.hybrid_search_provider(question, subscription_ids)
        else:
            retrieved = context.semantic().search(question)
    except ApiError:
        raise
    except (LookupError, ValueError) as exc:
        # An unsupported intent is a legitimate, expected outcome; report it as
        # a bounded 400 with the supported list rather than letting the model
        # answer a question the knowledge layer cannot ground.
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc) or "The Copilot cannot ground this question in operational context",
            details={"question": question},
        ) from exc

    # Filter the entire payload before anything is shown or sent to the model,
    # so out-of-scope facts never reach either the caller or Foundry.
    filtered = _filter_scoped(retrieved, scope)
    grounding: dict[str, Any] = filtered if isinstance(filtered, dict) else {}
    results = _results_of(grounding)

    answer: dict[str, Any] | None = None
    agent = context.foundry_agent()
    if agent is None:
        warnings.append(
            "No Foundry prompt agent is configured; returning retrieved context "
            "without a narrated answer."
        )
    else:
        try:
            answer = agent.answer(question=question, context=grounding).to_dict()
        except FoundryAgentError as exc:
            # Never fail the turn on the narration layer: retrieval already
            # produced a usable, fully-evidenced answer.
            logger.warning("foundry_agent_unavailable error=%s", exc)
            if context.provider_runtime is not None:
                context.provider_runtime.record_failure("copilot", exc)
            warnings.append(
                "The Foundry prompt agent could not be reached; showing "
                "retrieved context only."
            )

    evidence = [
        Evidence.from_context(
            retrieved,
            source_engine=SOURCE_ENGINE,
            source_table="ontology_entities",
            confidence=CONFIDENCE_MEDIUM,
        )
    ]
    if answer is not None:
        evidence.append(
            Evidence(
                source_engine=NARRATION_ENGINE,
                source_table=str(answer.get("agent_name") or ""),
                timestamp=str(retrieved.get("freshness") or ""),
                # The narration is a restatement of medium-confidence retrieval;
                # it can never be more trustworthy than the facts it summarizes.
                confidence=CONFIDENCE_MEDIUM,
            )
        )

    return envelope(
        {
            "question": question,
            "intent": retrieved.get("intent"),
            "results": results,
            "answer": answer,
        },
        evidence=evidence,
        scope=scope.to_dict(),
        knowledge_version=str(retrieved.get("knowledge_version") or ""),
        warnings=warnings,
    )


@router.get("/copilot/tools", summary="Governed toolset the Copilot may call")
def tools(context: Context, scope: ReadScope) -> dict[str, Any]:
    """The tool contracts, for docs and for the UI's starter-question hints."""
    return envelope({"tools": tool_catalog()}, scope=scope.to_dict())


@router.post("/copilot/investigate", summary="Multi-step Operations Copilot investigation")
def investigate(
    payload: InvestigationRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Answer an operational question via a bounded tool-calling loop.

    Unlike ``/copilot/ask`` (single retrieval call), this plans up to
    :data:`MAX_TOOL_CALLS` governed tool invocations -- topology, traffic-flow,
    CVE exposure, incidents, remediation, and ontology context -- executes
    each one scope-filtered, and narrates the aggregate. Every tool call's
    status and evidence is returned alongside the narration so a caller can
    audit exactly what was observed vs. inferred vs. unavailable.
    """
    question = payload.question.strip()
    if payload.tool and payload.tool not in tool_catalog_names():
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            f"Unknown tool {payload.tool!r}",
            details={"supported_tools": sorted(tool_catalog_names())},
        )

    started = time.monotonic()
    investigation = run_investigation(
        question,
        context=context,
        scope=scope,
        hint_tool=payload.tool or None,
        hint_args=payload.tool_arguments,
    )
    duration_ms = (time.monotonic() - started) * 1000.0
    if duration_ms > INVESTIGATION_TIMEOUT_SECONDS * 1000.0:
        logger.warning(
            "copilot_investigation_over_budget duration_ms=%.0f question_len=%d",
            duration_ms,
            len(question),
        )

    if payload.session_id:
        conversation_store().record(payload.session_id, principal.subject, investigation)

    # Audit trail: which tools ran, their outcome, and who asked -- never the
    # question text or tool payloads, to avoid a secret sink in application
    # logs while still letting an operator reconstruct tool-selection behavior.
    audit_logger.info(
        "copilot_investigation subject=%s tools=%s statuses=%s fact_status=%s duration_ms=%.0f",
        principal.subject,
        [call.tool for call in investigation.calls],
        [call.result.status for call in investigation.calls],
        investigation.fact_status,
        duration_ms,
    )

    evidence: list[Evidence] = []
    for call in investigation.calls:
        evidence.extend(call.result.evidence)
    if investigation.answer is not None:
        evidence.append(
            Evidence(
                source_engine=NARRATION_ENGINE,
                source_table=str(investigation.answer.get("agent_name") or ""),
                confidence=CONFIDENCE_MEDIUM,
            )
        )

    return envelope(
        investigation.to_dict(),
        evidence=evidence,
        scope=scope.to_dict(),
        warnings=list(investigation.warnings),
    )


@router.get("/copilot/history/{session_id}", summary="Bounded conversation history")
def history(session_id: str, context: Context, scope: ReadScope, principal: CurrentPrincipal) -> dict[str, Any]:
    """Prior turns for one caller's session -- never visible to another principal."""
    turns = conversation_store().history(session_id, principal.subject)
    return envelope({"session_id": session_id, "turns": turns}, scope=scope.to_dict())


def tool_catalog_names() -> set[str]:
    return {entry["name"] for entry in tool_catalog()}
