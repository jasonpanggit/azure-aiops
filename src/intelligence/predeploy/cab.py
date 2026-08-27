"""Change advisory board recommendation.

Turns the risk assessment into one of three verdicts. The verdict is derived
from stated rules rather than a threshold on the score alone, because two
changes can share a score for entirely different reasons and warrant different
handling — a data-destructive change and a broad-but-reversible network change
are not interchangeable at 60 points.

Low confidence never lowers the verdict. A change that cannot be assessed is
escalated for human review rather than waved through on a low score, since a
low score computed from missing data is an absence of evidence, not evidence of
safety.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from api.evidence import CONFIDENCE_LOW, CONFIDENCE_UNKNOWN

from .models import DESTRUCTIVE_ACTIONS, ProposedChange
from .risk import LEVEL_CRITICAL, LEVEL_HIGH, LEVEL_MODERATE
from .simulation import SEVERITY_HIGH

VERDICT_APPROVE = "approve"
VERDICT_APPROVE_WITH_CONDITIONS = "approve_with_conditions"
VERDICT_REQUIRE_REVIEW = "require_review"

# Effects that always demand a human decision regardless of computed score,
# because their downside is irreversible or security-relevant.
_ESCALATING_EFFECTS = frozenset(
    {
        "data_service_replaced_or_deleted",
        "retention_reduced",
        "internet_inbound_exposure",
        "public_network_access_enabled",
        "identity_grant_removed",
        "data_protection_setting_changed",
    }
)


def recommend(
    change: ProposedChange,
    *,
    risk: Mapping[str, Any],
    blast_radius: Mapping[str, Any],
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce a CAB verdict with its conditions and triggering evidence."""
    triggers: list[dict[str, Any]] = []
    conditions: list[str] = []

    level = str(risk.get("level") or "")
    confidence = str(risk.get("confidence") or "")
    unknowns = list(risk.get("unknowns") or [])

    effects = simulation.get("effects", []) or []
    escalating = [effect for effect in effects if effect.get("effect") in _ESCALATING_EFFECTS]
    for effect in escalating:
        triggers.append(
            {
                "trigger": "escalating_effect",
                "reason": effect.get("detail") or effect.get("effect"),
                "address": effect.get("address"),
                "domain": effect.get("domain"),
            }
        )

    if level in {LEVEL_CRITICAL, LEVEL_HIGH}:
        triggers.append(
            {
                "trigger": "risk_level",
                "reason": f"Pre-deployment risk was assessed as {level} ({risk.get('score')}/100).",
            }
        )

    if confidence in {CONFIDENCE_LOW, CONFIDENCE_UNKNOWN}:
        triggers.append(
            {
                "trigger": "low_confidence",
                "reason": (
                    f"Assessment confidence is {confidence}: {risk.get('confidence_rationale') or 'inputs were incomplete'}"
                ),
            }
        )

    destructive = [item for item in change.effective_changes if item.action in DESTRUCTIVE_ACTIONS]
    if destructive:
        triggers.append(
            {
                "trigger": "destructive_action",
                "reason": f"{len(destructive)} resource(s) will be deleted or replaced.",
            }
        )

    business_services = blast_radius.get("business_services", []) or []
    if business_services:
        triggers.append(
            {
                "trigger": "business_service_impact",
                "reason": (
                    f"{len(business_services)} business service(s) depend on affected resources: "
                    + ", ".join(str(value) for value in business_services[:5])
                ),
            }
        )

    # Verdict. Escalation beats everything, then confidence, then risk level.
    if escalating or confidence in {CONFIDENCE_LOW, CONFIDENCE_UNKNOWN} or level == LEVEL_CRITICAL:
        verdict = VERDICT_REQUIRE_REVIEW
    elif level in {LEVEL_HIGH, LEVEL_MODERATE} or destructive or business_services:
        verdict = VERDICT_APPROVE_WITH_CONDITIONS
    else:
        verdict = VERDICT_APPROVE

    # Conditions: the concrete validations that must be satisfied. Sourced from
    # the simulators so they are specific to what the change actually does.
    for effect in effects:
        if effect.get("severity") == SEVERITY_HIGH or effect.get("effect") in _ESCALATING_EFFECTS:
            for validation in effect.get("requires_validation", []) or []:
                if validation not in conditions:
                    conditions.append(str(validation))

    if destructive and verdict != VERDICT_APPROVE:
        rollback = "Document and rehearse a rollback path for every resource being deleted or replaced."
        if rollback not in conditions:
            conditions.append(rollback)
    if business_services and verdict != VERDICT_APPROVE:
        notify = (
            "Notify the owners of the affected business services and agree a deployment window: "
            + ", ".join(str(value) for value in business_services[:5])
        )
        if notify not in conditions:
            conditions.append(notify)
    if unknowns and verdict == VERDICT_REQUIRE_REVIEW:
        resolve = "Resolve the declared unknowns and re-run the assessment before the change board decides."
        if resolve not in conditions:
            conditions.append(resolve)

    if verdict == VERDICT_APPROVE:
        summary = (
            "No escalating effects, destructive actions, or business-service dependencies were "
            "identified from the submitted change."
        )
    elif verdict == VERDICT_APPROVE_WITH_CONDITIONS:
        summary = (
            f"The change is assessed as {level} risk and may proceed once the listed conditions "
            "are satisfied and evidenced."
        )
    else:
        summary = (
            "The change requires human review before deployment because of escalating effects or "
            "insufficient assessment confidence."
        )

    return {
        "verdict": verdict,
        "summary": summary,
        "conditions": conditions,
        "triggers": triggers,
        "risk_level": level,
        "risk_score": risk.get("score"),
        "confidence": confidence,
        "unknowns": unknowns,
        "required_approvals": _approvals(verdict, blast_radius),
        # Load-bearing: the recommendation is advisory input derived from a
        # declared plan, not an authorization decision or a failure prediction.
        "interpretation": (
            "This recommendation is advisory input for a change advisory board, derived from the "
            "submitted plan and discovered state. It does not authorize deployment and does not "
            "predict an incident."
        ),
        "confirmed_cause": False,
    }


def _approvals(verdict: str, blast_radius: Mapping[str, Any]) -> list[str]:
    if verdict == VERDICT_APPROVE:
        return []
    approvers: list[str] = []
    for field in ("owners", "support_teams"):
        for value in blast_radius.get(field, []) or []:
            text = str(value)
            if text and text not in approvers:
                approvers.append(text)
    if verdict == VERDICT_REQUIRE_REVIEW and "change_advisory_board" not in approvers:
        approvers.append("change_advisory_board")
    return approvers
