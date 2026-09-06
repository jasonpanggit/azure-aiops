"""Microsoft Agent Framework orchestration boundary for Operations Copilot.

MAF is the default orchestration contract: Operations Copilot coordinates
page-drawer turns and selects specialists from the user's question first, rather
than letting the page own the conversation. Set
``AIOPS_AGENT_ORCHESTRATION_MODE=deterministic`` to use the legacy
page-anchored rollback path, or ``canonical`` to route every surface through
the governed ``OrchestrationService``.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ENV_AGENT_ORCHESTRATION_MODE = "AIOPS_AGENT_ORCHESTRATION_MODE"
MODE_DETERMINISTIC = "deterministic"
MODE_MAF = "maf"
MODE_CANONICAL = "canonical"


@dataclass(frozen=True)
class OrchestrationDecision:
    """Specialist selection made for one Operations Copilot turn."""

    selected_ids: tuple[str, ...]
    strategy: str
    runtime: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_ids": list(self.selected_ids),
            "strategy": self.strategy,
            "runtime": self.runtime,
            "reason": self.reason,
        }


def maf_mode_enabled() -> bool:
    """Return whether the MAF orchestration route is enabled."""

    return os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold() != MODE_DETERMINISTIC


def canonical_orchestration_enabled() -> bool:
    """Return whether all surfaces route through the canonical OrchestrationService."""

    return os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold() == MODE_CANONICAL


def _maf_runtime_label() -> str:
    return (
        "microsoft-agent-framework"
        if importlib.util.find_spec("agent_framework") is not None
        else "maf-compatible"
    )


def _append_unique(target: list[str], value: str, *, limit: int) -> None:
    if value and value not in target and len(target) < limit:
        target.append(value)


def select_specialists_for_turn(
    *,
    page_kind: str,
    question: str,
    page_specialists: Mapping[str, Sequence[str]],
    catalog: Sequence[Any],
    limit: int,
) -> OrchestrationDecision:
    """Select specialists for a page turn using the MAF pivot contract.

    The old page-anchored selector made a Network drawer behave like a Network
    agent, even when the user asked an ownership, change, or patch question.
    MAF mode inverts that: Operations Copilot owns intent selection, then
    delegates to the matching specialists. The current page is used only as a
    fallback when the question has no specialist signal.

    Keyword matching is sourced from each catalog entry's own ``keywords``
    field (the single source of truth already used by the deterministic
    investigation path) rather than a second, independently-maintained table,
    so the two orchestration paths cannot silently drift apart.
    """

    lowered = question.casefold()
    selected: list[str] = []
    for agent in catalog:
        agent_id = getattr(agent, "id", "")
        if agent_id == "executive_summary":
            continue
        keywords = getattr(agent, "keywords", None) or ()
        if any(marker in lowered for marker in keywords):
            _append_unique(selected, agent_id, limit=limit)

    if selected:
        return OrchestrationDecision(
            selected_ids=tuple(selected),
            strategy="question_first",
            runtime=_maf_runtime_label(),
            reason="matched specialist intent from the operator question",
        )

    for agent_id in page_specialists.get(page_kind, ()):
        if agent_id != "executive_summary":
            _append_unique(selected, agent_id, limit=limit)

    return OrchestrationDecision(
        selected_ids=tuple(selected),
        strategy="page_fallback",
        runtime=_maf_runtime_label(),
        reason="no specialist intent matched; used the current page as context",
    )


# ---------------------------------------------------------------------------
# Deterministic keyword fallback for the canonical OrchestrationService
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ManifestCatalogEntry:
    """Lightweight catalog entry for ``select_specialists_for_turn``."""

    id: str
    keywords: tuple[str, ...]


def build_deterministic_fallback(
    request: Any,
    manifest: Any,
) -> Any:
    """Construct a keyword-selected CandidatePlan that passes the same policy.

    Uses ``select_specialists_for_turn`` for keyword matching, constrained to
    specialists whose ``page_mappings`` include the request's page_kind and
    whose catalogued tools are all read-only reviewed grants.  The candidate
    is structurally identical to a model-proposed plan so the deterministic
    policy validates it without special-casing.

    Imported types are resolved at call time to avoid a top-level import
    cycle between ``maf_orchestrator`` and the contract/manifest modules.
    """
    from operations.orchestration_contract import (
        COVERAGE_CITATION_ID,
        CandidatePlan,
        SpecialistStep,
        ToolCallCandidate,
    )

    page_kind: str = request.snapshot.page_kind
    page_mapping = manifest.page_mapping_projection()

    catalog = [
        _ManifestCatalogEntry(id=spec.id, keywords=spec.intent_examples)
        for spec in manifest.specialists
    ]

    decision = select_specialists_for_turn(
        page_kind=page_kind,
        question=request.question,
        page_specialists=page_mapping,
        catalog=catalog,
        limit=4,
    )

    # Keep only specialists that map to this page and have at least one tool.
    valid_ids: list[str] = []
    for sid in decision.selected_ids:
        try:
            spec = manifest.require(sid)
        except ValueError:
            continue
        if page_kind in spec.page_mappings and spec.operations_mcp_tools:
            valid_ids.append(sid)

    # If keyword selection found nothing for this page, use the page default.
    if not valid_ids:
        for spec in manifest.specialists:
            if (
                spec.id != "executive_summary"
                and page_kind in spec.page_mappings
                and spec.operations_mcp_tools
            ):
                valid_ids.append(spec.id)
                break

    citation_ids = [item.evidence_id for item in request.snapshot.evidence]
    if not citation_ids:
        citation_ids = [COVERAGE_CITATION_ID]

    steps: list[SpecialistStep] = []
    for sid in valid_ids:
        spec = manifest.require(sid)
        steps.append(
            SpecialistStep(
                specialist_id=sid,
                tool_calls=[
                    ToolCallCandidate(
                        tool=spec.operations_mcp_tools[0],
                        arguments={},
                        citation_ids=citation_ids,
                    )
                ],
            )
        )

    if not steps:
        # Absolute guard — should never be reached for a valid manifest.
        raise ValueError("no page-compatible specialist with tools found")

    return CandidatePlan(
        steps=steps,
        estimated_tokens=0,
        max_wall_seconds=5,
        mutation_intent=False,
    )
