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
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from operations.copilot_canary_authorization import (
    CanaryAuthorizationError,
    require_canary_authorization_if_requested,
)

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
_ROLLOUT_DECISION_PROOF = object()
_CANONICAL_ROUTE_PROOF = object()


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
    authorization_id: str = ""
    authorization_manifest_sha256: str = ""
    reviewed_tree_sha256: str = ""
    stable_key_sha256: str = ""
    authorization_expires_at: datetime | None = None
    _proof: object | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class CanonicalRouteAuthority:
    """Request-bound capability permitting one canonical execution."""

    mode: str
    principal_sha256: str
    stable_key_sha256: str
    execution_sha256: str
    authorization_id: str
    authorization_manifest_sha256: str
    reviewed_tree_sha256: str
    canary_bucket: int
    expires_at: datetime
    _proof: object = field(repr=False, compare=False)


def _identity_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_execution_sha256(
    request: Any,
    *,
    selection_snapshot: Any = None,
    canonical_selection_snapshot: Any = None,
) -> str:
    """Return a deterministic digest of every canonical execution input."""

    def _json_value(value: Any) -> Any:
        if value is None:
            return None
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json")
        return value

    payload = {
        "request": _json_value(request),
        "selection_snapshot": _json_value(selection_snapshot),
        "canonical_selection_snapshot": _json_value(
            canonical_selection_snapshot
        ),
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def canonical_route_authority(
    decision: CopilotRolloutDecision,
    *,
    request: Any,
    principal_subject: str,
    stable_key: str,
    selection_snapshot: Any = None,
    canonical_selection_snapshot: Any = None,
) -> CanonicalRouteAuthority:
    """Bind one validated canonical rollout decision to one execution."""

    stable_key_sha256 = _identity_sha256(stable_key)
    if (
        decision._proof is not _ROLLOUT_DECISION_PROOF
        or decision.mode != ROLLOUT_CANARY
        or not decision.canonical_enabled
        or decision.canary_bucket is None
        or not principal_subject
        or stable_key != principal_subject
        or decision.stable_key_sha256 != stable_key_sha256
        or not decision.authorization_id
        or not decision.authorization_manifest_sha256
        or not decision.reviewed_tree_sha256
        or decision.authorization_expires_at is None
    ):
        raise CanaryAuthorizationError(
            "canonical route was not selected by validated canary authority"
        )
    return CanonicalRouteAuthority(
        mode=decision.mode,
        principal_sha256=_identity_sha256(principal_subject),
        stable_key_sha256=stable_key_sha256,
        execution_sha256=canonical_execution_sha256(
            request,
            selection_snapshot=selection_snapshot,
            canonical_selection_snapshot=canonical_selection_snapshot,
        ),
        authorization_id=decision.authorization_id,
        authorization_manifest_sha256=(
            decision.authorization_manifest_sha256
        ),
        reviewed_tree_sha256=decision.reviewed_tree_sha256,
        canary_bucket=decision.canary_bucket,
        expires_at=decision.authorization_expires_at,
        _proof=_CANONICAL_ROUTE_PROOF,
    )


def validate_canonical_route_authority(
    authority: CanonicalRouteAuthority | None,
    *,
    request: Any,
    principal_subject: str,
    selection_snapshot: Any = None,
    canonical_selection_snapshot: Any = None,
) -> None:
    """Refuse absent, stale, mismatched, or forged canonical authority."""

    if authority is None or authority._proof is not _CANONICAL_ROUTE_PROOF:
        raise CanaryAuthorizationError(
            "canonical execution route authority is absent or mismatched"
        )
    identity_sha256 = _identity_sha256(principal_subject)
    expected_execution_sha256 = canonical_execution_sha256(
        request,
        selection_snapshot=selection_snapshot,
        canonical_selection_snapshot=canonical_selection_snapshot,
    )
    if (
        authority.mode != ROLLOUT_CANARY
        or authority.principal_sha256 != identity_sha256
        or authority.stable_key_sha256 != identity_sha256
        or authority.execution_sha256 != expected_execution_sha256
        or not authority.authorization_id
        or not authority.authorization_manifest_sha256
        or not authority.reviewed_tree_sha256
        or not 0 <= authority.canary_bucket < 100
        or datetime.now(UTC) >= authority.expires_at
    ):
        raise CanaryAuthorizationError(
            "canonical execution route authority is absent or mismatched"
        )


def maf_mode_enabled() -> bool:
    """Return whether the MAF orchestration route is enabled."""

    return os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold() != MODE_DETERMINISTIC


def _canary_bucket(stable_key: str) -> int:
    digest = hashlib.sha256(
        f"copilot-rollout-v1\0{stable_key}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") % 100


def copilot_rollout_decision(*, stable_key: str = "") -> CopilotRolloutDecision:
    """Resolve compatibility → shadow → canary → default without widening.

    An unspecified, blank, or malformed non-canary deployment value selects
    compatibility. Canary misconfiguration raises before external execution,
    and default mode is not authorized. Canary assignment is stable for one
    principal and cannot fall back to random or process-local state. The
    retained rollback mode is fixed to compatibility.
    """

    authority = require_canary_authorization_if_requested()

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
    if raw_mode is None:
        return CopilotRolloutDecision(
            mode=ROLLOUT_COMPATIBILITY,
            canonical_enabled=False,
            shadow_enabled=False,
            reason="rollout_mode_unspecified",
        )
    if not raw_mode.strip():
        return CopilotRolloutDecision(
            mode=ROLLOUT_COMPATIBILITY,
            canonical_enabled=False,
            shadow_enabled=False,
            reason="rollout_mode_invalid",
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
        if authority is None:
            raise CanaryAuthorizationError("validated route authority is missing")
        percentage = authority.percentage
        if not stable_key:
            raise CanaryAuthorizationError("canary stable key is missing")
        bucket = _canary_bucket(stable_key)
        return CopilotRolloutDecision(
            mode,
            bucket < percentage,
            False,
            "canary_selected",
            canary_bucket=bucket,
            authorization_id=authority.authorization_id,
            authorization_manifest_sha256=authority.manifest_sha256,
            reviewed_tree_sha256=authority.reviewed_tree_sha256,
            stable_key_sha256=_identity_sha256(stable_key),
            authorization_expires_at=authority.expires_at,
            _proof=_ROLLOUT_DECISION_PROOF,
        )

    raise CanaryAuthorizationError("default rollout mode is not authorized")


def canonical_orchestration_enabled(
    *,
    stable_key: str = "",
    decision: CopilotRolloutDecision | None = None,
) -> bool:
    """Return whether a legacy endpoint opts into the canonical service.

    The rollout decision governs the canonical ``/copilot/investigations``
    endpoint. Existing context, investigation, history, and multi-agent
    endpoints retain their legacy behavior unless their original
    ``AIOPS_AGENT_ORCHESTRATION_MODE=canonical`` switch is explicit.
    """

    decision = decision or copilot_rollout_decision(stable_key=stable_key)
    if decision.mode == ROLLOUT_CANARY and decision.authorization_id:
        return decision.canonical_enabled
    legacy_mode = os.environ.get(ENV_AGENT_ORCHESTRATION_MODE, "").strip().casefold()
    return legacy_mode == MODE_CANONICAL and decision.canonical_enabled


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
        page_kind.removesuffix("_page") if page_kind.endswith("_page") else page_kind
    )
    for specialist_id, _ in _REVIEWED_CROSS_DOMAIN_GRANTS.get(grant_page_kind, ()):
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
        agent_id for agent_id in page_owners if agent_id != "executive_summary"
    )
    if not allowed:
        return OrchestrationDecision(
            selected_ids=(),
            strategy="page_unmapped",
            runtime=_maf_runtime_label(),
            reason="the active page has no reviewed specialist mapping",
        )

    catalog_by_id = {
        getattr(agent, "id", ""): agent for agent in catalog if getattr(agent, "id", "")
    }
    lowered = question.casefold()
    selected: list[str] = []

    grant_page_kind = (
        page_kind.removesuffix("_page") if page_kind.endswith("_page") else page_kind
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
            and any(marker in lowered for marker in _EXECUTIVE_INTENT_MARKERS)
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
        tools = list(spec.operations_tools_for_page(page_kind))
        lowered_question = request.question.casefold()
        preferred_arguments: dict[str, dict[str, Any]] = {}
        if page_kind == "kb_detail" and "kb_detail" in tools:
            tools.remove("kb_detail")
            tools.insert(0, "kb_detail")
        if "firewall_nsg_gaps" in tools and any(
            marker in lowered_question
            for marker in ("bypass", "inspection", "firewall gap", "nsg gap")
        ):
            tools.remove("firewall_nsg_gaps")
            tools.insert(0, "firewall_nsg_gaps")
            if "bypass" in lowered_question or "inspection" in lowered_question:
                preferred_arguments["firewall_nsg_gaps"] = {
                    "category": "firewall_bypass"
                }
        for tool in tools:
            try:
                arguments, _ = validate_tool_arguments(
                    tool,
                    preferred_arguments.get(tool, {}),
                )
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
                    elif field == "kb_id":
                        match = re.search(
                            r"\bKB\d{4,}\b",
                            (f"{request.snapshot.page_id} {request.question}"),
                            flags=re.IGNORECASE,
                        )
                        if not match:
                            break
                        derived[field] = match.group(0).upper()
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
