"""Microsoft Agent Framework orchestration boundary for Operations Copilot.

MAF is the default orchestration contract: Operations Copilot coordinates
page-drawer turns and selects specialists from the user's question first, rather
than letting the page own the conversation. Set
``AIOPS_AGENT_ORCHESTRATION_MODE=deterministic`` to use the legacy
page-anchored rollback path, or ``canonical`` to route every surface through
the governed ``OrchestrationService``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ENV_AGENT_ORCHESTRATION_MODE = "AIOPS_AGENT_ORCHESTRATION_MODE"
MODE_DETERMINISTIC = "deterministic"
MODE_MAF = "maf"
MODE_CANONICAL = "canonical"
ENV_COPILOT_ROLLOUT_MODE = "AIOPS_COPILOT_ROLLOUT_MODE"
ENV_COPILOT_CANARY_PERCENTAGE = "AIOPS_COPILOT_CANARY_PERCENTAGE"
ENV_COPILOT_ROLLBACK_MODE = "AIOPS_COPILOT_ROLLBACK_MODE"
ROLLOUT_COMPATIBILITY = "compatibility"
ROLLOUT_SHADOW = "shadow"
ROLLOUT_CANARY = "canary"
ROLLOUT_DEFAULT = "default"
ROLLOUT_MODES = frozenset(
    {
        ROLLOUT_COMPATIBILITY,
        ROLLOUT_SHADOW,
        ROLLOUT_CANARY,
        ROLLOUT_DEFAULT,
    }
)
_REVIEWED_CROSS_DOMAIN_GRANTS: Mapping[
    str,
    tuple[tuple[str, tuple[str, ...]], ...],
] = {
    "network": (
        (
            "vulnerability",
            ("cve", "vulnerab", "exploit", "exposure", "attack path"),
        ),
        (
            "governance",
            ("owner", "owned", "approval", "approver", "governance", "policy"),
        ),
    ),
    "vulnerability": (
        (
            "remediation",
            ("remediate", "remediation", "mitigation", "rollback"),
        ),
    ),
    "incident": (
        (
            "change",
            ("change", "changed", "deployment", "configuration", "drift"),
        ),
    ),
    "remediation": (
        (
            "governance",
            ("owner", "owned", "approval", "approver", "governance", "policy"),
        ),
        (
            "vulnerability",
            ("cve", "vulnerab", "exploit", "exposure", "attack path"),
        ),
    ),
    "finops": (
        (
            "resource_health_observability",
            ("resource-health", "resource health"),
        ),
    ),
}
_OVERVIEW_DOMAIN_SPECIALISTS = (
    "network",
    "vulnerability",
    "patch",
    "incident",
    "change",
    "governance",
    "remediation",
    "inventory_data_health",
    "identity_access",
    "finops",
    "resource_health_observability",
)
_OVERVIEW_SYNTHESIS_FALLBACK = ("incident", "governance")
_EXECUTIVE_INTENT_MARKERS = (
    "executive",
    "leadership",
    "cross-domain",
    "cross domain",
    "situation report",
    "roll up",
    "brief",
)


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


@dataclass(frozen=True)
class CopilotRolloutDecision:
    """Fail-closed request-bound selection for the staged rollout."""

    mode: str
    canonical_enabled: bool
    shadow_enabled: bool
    reason: str
    canary_bucket: int | None = None


def maf_mode_enabled() -> bool:
    """Return whether the MAF orchestration route is enabled."""

    return os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold() != MODE_DETERMINISTIC


def copilot_rollout_decision(*, stable_key: str = "") -> CopilotRolloutDecision:
    """Resolve compatibility → shadow → canary → default without widening.

    A missing or malformed deployment value selects compatibility. Canary
    assignment is stable for one principal and cannot fall back to random or
    process-local state. The retained rollback mode is intentionally fixed to
    compatibility; an unexpected value also fails closed.
    """

    if (
        os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold()
        == MODE_DETERMINISTIC
    ):
        return CopilotRolloutDecision(
            mode=ROLLOUT_COMPATIBILITY,
            canonical_enabled=False,
            shadow_enabled=False,
            reason="deterministic_override",
        )

    rollback_mode = os.environ.get(
        ENV_COPILOT_ROLLBACK_MODE, ROLLOUT_COMPATIBILITY
    ).strip().casefold()
    if rollback_mode != ROLLOUT_COMPATIBILITY:
        return CopilotRolloutDecision(
            mode=ROLLOUT_COMPATIBILITY,
            canonical_enabled=False,
            shadow_enabled=False,
            reason="rollback_mode_invalid",
        )

    raw_mode = os.environ.get(ENV_COPILOT_ROLLOUT_MODE)
    if raw_mode is None or not raw_mode.strip():
        if (
            os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold()
            == MODE_CANONICAL
        ):
            return CopilotRolloutDecision(
                mode=ROLLOUT_DEFAULT,
                canonical_enabled=True,
                shadow_enabled=False,
                reason="legacy_canonical_mode",
            )
        return CopilotRolloutDecision(
            mode=ROLLOUT_COMPATIBILITY,
            canonical_enabled=False,
            shadow_enabled=False,
            reason="rollout_mode_missing",
        )
    mode = raw_mode.strip().casefold()
    if mode not in ROLLOUT_MODES:
        return CopilotRolloutDecision(
            mode=ROLLOUT_COMPATIBILITY,
            canonical_enabled=False,
            shadow_enabled=False,
            reason="rollout_mode_invalid",
        )

    if mode == ROLLOUT_COMPATIBILITY:
        return CopilotRolloutDecision(mode, False, False, "compatibility_selected")
    if mode == ROLLOUT_SHADOW:
        return CopilotRolloutDecision(mode, False, True, "shadow_selected")

    if mode == ROLLOUT_CANARY:
        percentage_text = os.environ.get(
            ENV_COPILOT_CANARY_PERCENTAGE, ""
        ).strip()
        if not percentage_text.isdecimal():
            return CopilotRolloutDecision(
                ROLLOUT_COMPATIBILITY,
                False,
                False,
                "canary_percentage_invalid",
            )
        percentage = int(percentage_text)
        if not 0 <= percentage <= 100:
            return CopilotRolloutDecision(
                ROLLOUT_COMPATIBILITY,
                False,
                False,
                "canary_percentage_invalid",
            )
        if not stable_key:
            return CopilotRolloutDecision(
                ROLLOUT_COMPATIBILITY,
                False,
                False,
                "canary_stable_key_missing",
            )
        digest = hashlib.sha256(
            f"copilot-rollout-v1\0{stable_key}".encode()
        ).digest()
        bucket = int.from_bytes(digest[:8], "big") % 100
        return CopilotRolloutDecision(
            mode,
            bucket < percentage,
            False,
            "canary_selected",
            canary_bucket=bucket,
        )

    return CopilotRolloutDecision(mode, True, False, "default_selected")


def canonical_orchestration_enabled(*, stable_key: str = "") -> bool:
    """Return whether this request routes through the canonical service."""

    return copilot_rollout_decision(stable_key=stable_key).canonical_enabled


def _maf_runtime_label() -> str:
    return (
        "microsoft-agent-framework"
        if importlib.util.find_spec("agent_framework") is not None
        else "maf-compatible"
    )


def _append_unique(target: list[str], value: str, *, limit: int) -> None:
    if value and value not in target and len(target) < limit:
        target.append(value)


def reviewed_specialists_for_page(
    page_kind: str,
    page_specialists: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    """Return the page owners plus explicitly reviewed cross-domain grants."""

    reviewed: list[str] = []
    page_owners = tuple(page_specialists.get(page_kind, ()))
    if page_kind == "overview" and "executive_summary" in page_owners:
        page_owners = _OVERVIEW_DOMAIN_SPECIALISTS
    for specialist_id in page_owners:
        if specialist_id != "executive_summary":
            _append_unique(reviewed, specialist_id, limit=64)
    grant_page_kind = (
        page_kind.removesuffix("_page")
        if page_kind.endswith("_page")
        else page_kind
    )
    for specialist_id, _ in _REVIEWED_CROSS_DOMAIN_GRANTS.get(
        grant_page_kind, ()
    ):
        _append_unique(reviewed, specialist_id, limit=64)
    return tuple(reviewed)


def select_specialists_for_turn(
    *,
    page_kind: str,
    question: str,
    page_specialists: Mapping[str, Sequence[str]],
    catalog: Sequence[Any],
    limit: int,
) -> OrchestrationDecision:
    """Select specialists for a page turn using the MAF pivot contract.

    The manifest's ordered page mapping is the authorization boundary. Question
    intent may narrow that reviewed set, but globally matching keywords can
    never add a specialist that the active page does not permit. If no allowed
    specialist matches, the exact page mapping is used as the deterministic
    fallback. Unknown pages fail closed.

    Keyword matching is sourced from each catalog entry's own ``keywords``
    field (the single source of truth already used by the deterministic
    investigation path) rather than a second, independently-maintained table,
    so the two orchestration paths cannot silently drift apart.
    """

    page_owners = tuple(page_specialists.get(page_kind, ()))
    if page_kind == "overview" and "executive_summary" in page_owners:
        page_owners = _OVERVIEW_DOMAIN_SPECIALISTS
    allowed = tuple(
        agent_id
        for agent_id in page_owners
        if agent_id != "executive_summary"
    )
    if not allowed:
        return OrchestrationDecision(
            selected_ids=(),
            strategy="page_unmapped",
            runtime=_maf_runtime_label(),
            reason="the active page has no reviewed specialist mapping",
        )

    catalog_by_id = {
        getattr(agent, "id", ""): agent
        for agent in catalog
        if getattr(agent, "id", "")
    }
    lowered = question.casefold()
    selected: list[str] = []

    grant_page_kind = (
        page_kind.removesuffix("_page")
        if page_kind.endswith("_page")
        else page_kind
    )
    matched_cross_domain = [
        specialist_id
        for specialist_id, markers in _REVIEWED_CROSS_DOMAIN_GRANTS.get(
            grant_page_kind, ()
        )
        if specialist_id in catalog_by_id
        and any(marker in lowered for marker in markers)
    ]
    if matched_cross_domain:
        if allowed[0] in catalog_by_id:
            _append_unique(selected, allowed[0], limit=limit)
        for specialist_id in matched_cross_domain:
            _append_unique(selected, specialist_id, limit=limit)
        return OrchestrationDecision(
            selected_ids=tuple(selected),
            strategy="question_first",
            runtime=_maf_runtime_label(),
            reason="matched an explicitly reviewed cross-domain intent grant",
        )

    for agent_id in allowed:
        agent = catalog_by_id.get(agent_id)
        keywords = getattr(agent, "keywords", None) or ()
        if any(marker in lowered for marker in keywords):
            _append_unique(selected, agent_id, limit=limit)

    if selected:
        if (
            page_kind == "overview"
            and len(selected) < min(2, limit)
            and any(
            marker in lowered for marker in _EXECUTIVE_INTENT_MARKERS
            )
        ):
            for specialist_id in _OVERVIEW_SYNTHESIS_FALLBACK:
                _append_unique(selected, specialist_id, limit=limit)
                if len(selected) >= min(2, limit):
                    break
        return OrchestrationDecision(
            selected_ids=tuple(selected),
            strategy="question_first",
            runtime=_maf_runtime_label(),
            reason="matched specialist intent from the operator question",
        )

    for agent_id in allowed:
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
) -> Any | None:
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
    if page_kind == "overview":
        page_mapping[page_kind] = _OVERVIEW_DOMAIN_SPECIALISTS

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

    citation_ids = [item.evidence_id for item in request.snapshot.evidence]
    if not citation_ids:
        citation_ids = [COVERAGE_CITATION_ID]

    from operations.mcp_server import validate_tool_arguments

    def explicit_subject() -> str:
        entities = [
            *request.snapshot.selected_entities,
            *[
                item.entity
                for item in request.snapshot.evidence
                if item.entity is not None and (item.selected or item.direct)
            ],
        ]
        for entity in entities:
            resource_id = str(getattr(entity, "resource_id", "") or "").strip()
            if resource_id:
                return resource_id
            source_key = str(getattr(entity, "source_key", "") or "").strip()
            if source_key:
                return source_key
        for item in request.snapshot.evidence:
            if not (item.selected or item.direct):
                continue
            resource_id = str(item.resource_id or "").strip()
            if resource_id:
                return resource_id
        return ""

    def safe_call(spec: Any) -> ToolCallCandidate | None:
        for tool in spec.operations_mcp_tools:
            try:
                arguments, _ = validate_tool_arguments(tool, {})
            except ValueError:
                try:
                    _, missing = validate_tool_arguments(
                        tool,
                        {},
                        require_required=False,
                    )
                except ValueError:
                    continue
                derived: dict[str, Any] = {}
                for field in missing:
                    subject = explicit_subject()
                    if field == "name":
                        if subject:
                            break
                        derived[field] = request.question
                    elif field == "subject":
                        derived[field] = subject or request.question
                    elif field == "query":
                        derived[field] = request.snapshot.query or request.question
                    else:
                        break
                else:
                    try:
                        arguments, _ = validate_tool_arguments(tool, derived)
                    except ValueError:
                        continue
                    return ToolCallCandidate(
                        tool=tool,
                        arguments=arguments,
                        citation_ids=citation_ids,
                    )
                continue
            return ToolCallCandidate(
                tool=tool,
                arguments=arguments,
                citation_ids=citation_ids,
            )
        return None

    steps: list[SpecialistStep] = []
    reviewed_ids = set(reviewed_specialists_for_page(page_kind, page_mapping))
    for sid in decision.selected_ids:
        try:
            spec = manifest.require(sid)
        except ValueError:
            continue
        if sid not in reviewed_ids:
            continue
        call = safe_call(spec)
        if call is None:
            continue
        steps.append(
            SpecialistStep(
                specialist_id=sid,
                tool_calls=[call],
            )
        )

    if not steps:
        for sid in page_mapping.get(page_kind, ()):
            try:
                spec = manifest.require(sid)
            except ValueError:
                continue
            call = safe_call(spec)
            if call is None:
                continue
            steps.append(
                SpecialistStep(
                    specialist_id=sid,
                    tool_calls=[call],
                )
            )
            break

    if not steps:
        return None

    return CandidatePlan(
        steps=steps,
        estimated_tokens=0,
        max_wall_seconds=5,
        mutation_intent=False,
    )
