"""Pre-deployment risk scoring with evidence, confidence, and declared unknowns.

The score is an additive factor model in the style of
``intelligence.change.change_risk_engine.ChangeRiskEngine``, kept deliberately
transparent: every point is attributable to a named factor and a piece of
evidence an approver can inspect and disagree with. An opaque score would be
useless in a change advisory board, which has to justify its decision.

Confidence is scored separately from risk and moves in the opposite direction:
the more unknowns present, the less the score should be trusted. Reporting a
confident-looking number derived from an incomplete plan is the specific
failure mode this separation exists to prevent. A high-risk / low-confidence
result is a signal to go and find better data, not to block the change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from api.evidence import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNKNOWN,
)

from .models import DESTRUCTIVE_ACTIONS, ProposedChange
from .simulation import SEVERITY_HIGH, SEVERITY_MEDIUM
from .state_comparison import (
    FINDING_MISSING_TARGET,
    FINDING_UNMANAGED_DRIFT,
    FINDING_UNTRACKED_CREATE,
)

LEVEL_CRITICAL = "Critical"
LEVEL_HIGH = "High"
LEVEL_MODERATE = "Moderate"
LEVEL_LOW = "Low"

_PRODUCTION_ENVIRONMENTS = {"production", "prod", "live"}
_CRITICALITIES = {"critical": 15, "high": 10, "medium": 5}


def risk_level(score: int) -> str:
    if score >= 75:
        return LEVEL_CRITICAL
    if score >= 50:
        return LEVEL_HIGH
    if score >= 25:
        return LEVEL_MODERATE
    return LEVEL_LOW


def _criticality_points(blast_radius: Mapping[str, Any]) -> tuple[int, str]:
    highest, points = "", 0
    for resource in blast_radius.get("impacted_resources", []):
        value = str(resource.get("criticality") or "").casefold()
        if _CRITICALITIES.get(value, 0) > points:
            points, highest = _CRITICALITIES[value], value
    return points, highest


def score_change(
    change: ProposedChange,
    *,
    comparison: Mapping[str, Any],
    blast_radius: Mapping[str, Any],
    simulation: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce a pre-deployment risk assessment.

    Returns the score, its level, the attributed factors, the supporting
    evidence, a separately-derived confidence band, and every unknown that
    weakened that confidence.
    """
    factors: dict[str, int] = {}
    evidence: list[dict[str, Any]] = []

    severity_counts = simulation.get("by_severity", {}) or {}
    high_effects = int(severity_counts.get(SEVERITY_HIGH, 0))
    medium_effects = int(severity_counts.get(SEVERITY_MEDIUM, 0))

    factors["high_severity_effects"] = min(high_effects * 10, 30)
    if high_effects:
        evidence.append(
            {
                "factor": "high_severity_effects",
                "observation": f"{high_effects} simulated effect(s) were classified high severity.",
                "source": "predeploy.simulation",
            }
        )

    factors["medium_severity_effects"] = min(medium_effects * 4, 12)
    if medium_effects:
        evidence.append(
            {
                "factor": "medium_severity_effects",
                "observation": f"{medium_effects} simulated effect(s) were classified medium severity.",
                "source": "predeploy.simulation",
            }
        )

    destructive = [item for item in change.effective_changes if item.action in DESTRUCTIVE_ACTIONS]
    factors["destructive_actions"] = min(len(destructive) * 8, 20)
    if destructive:
        evidence.append(
            {
                "factor": "destructive_actions",
                "observation": (
                    f"{len(destructive)} resource(s) will be deleted or replaced: "
                    + ", ".join(item.address for item in destructive[:5])
                ),
                "source": "predeploy.ingestion",
            }
        )

    environment = str(change.target_environment or "").casefold()
    impacted_environments = {str(value).casefold() for value in blast_radius.get("environments", [])}
    in_production = environment in _PRODUCTION_ENVIRONMENTS or bool(
        impacted_environments & _PRODUCTION_ENVIRONMENTS
    )
    factors["production_environment"] = 12 if in_production else 0
    if in_production:
        evidence.append(
            {
                "factor": "production_environment",
                "observation": "The change targets or reaches production resources.",
                "source": "predeploy.blast_radius",
            }
        )

    criticality_points, highest_criticality = _criticality_points(blast_radius)
    factors["business_criticality"] = criticality_points
    if criticality_points:
        evidence.append(
            {
                "factor": "business_criticality",
                "observation": f"Blast radius includes resources rated '{highest_criticality}' criticality.",
                "source": "predeploy.blast_radius",
            }
        )

    business_services = blast_radius.get("business_services", []) or []
    factors["business_service_reach"] = min(len(business_services) * 5, 15)
    if business_services:
        evidence.append(
            {
                "factor": "business_service_reach",
                "observation": (
                    f"{len(business_services)} business service(s) depend on affected resources: "
                    + ", ".join(str(value) for value in business_services[:5])
                ),
                "source": "predeploy.blast_radius",
            }
        )

    total_impacted = int(blast_radius.get("total_impacted_count", 0))
    indirect = max(total_impacted - int(blast_radius.get("directly_changed_count", 0)), 0)
    factors["dependency_reach"] = min(indirect * 2, 12)
    if indirect:
        evidence.append(
            {
                "factor": "dependency_reach",
                "observation": f"{indirect} resource(s) depend transitively on the changed resources.",
                "source": "predeploy.blast_radius",
            }
        )

    counts = comparison.get("counts", {}) or {}
    drift_count = int(counts.get(FINDING_UNMANAGED_DRIFT, 0))
    missing_count = int(counts.get(FINDING_MISSING_TARGET, 0))
    untracked_count = int(counts.get(FINDING_UNTRACKED_CREATE, 0))

    factors["state_drift"] = min(drift_count * 6, 18)
    if drift_count:
        evidence.append(
            {
                "factor": "state_drift",
                "observation": (
                    f"{drift_count} resource(s) have discovered state that differs from the state this "
                    "change was planned against."
                ),
                "source": "predeploy.state_comparison",
            }
        )

    factors["missing_targets"] = min(missing_count * 5, 15)
    if missing_count:
        evidence.append(
            {
                "factor": "missing_targets",
                "observation": f"{missing_count} change target(s) were not found in discovered state.",
                "source": "predeploy.state_comparison",
            }
        )

    factors["untracked_creates"] = min(untracked_count * 4, 8)
    if untracked_count:
        evidence.append(
            {
                "factor": "untracked_creates",
                "observation": f"{untracked_count} resource(s) would be created but already exist.",
                "source": "predeploy.state_comparison",
            }
        )

    vulnerable = int(blast_radius.get("vulnerable_resources_in_path", 0))
    factors["vulnerable_resources_in_path"] = min(vulnerable * 4, 12)
    if vulnerable:
        evidence.append(
            {
                "factor": "vulnerable_resources_in_path",
                "observation": f"{vulnerable} resource(s) in the blast radius carry known vulnerability findings.",
                "source": "predeploy.blast_radius",
            }
        )

    subscriptions = blast_radius.get("subscriptions", []) or []
    factors["cross_subscription_reach"] = 8 if len(subscriptions) > 1 else 0
    if len(subscriptions) > 1:
        evidence.append(
            {
                "factor": "cross_subscription_reach",
                "observation": f"Impact spans {len(subscriptions)} subscriptions.",
                "source": "predeploy.blast_radius",
            }
        )

    score = min(sum(factors.values()), 100)

    unknowns = _collect_unknowns(change, comparison, blast_radius, simulation)
    confidence = _confidence(
        unknowns=unknowns,
        change=change,
        comparison=comparison,
        blast_radius=blast_radius,
    )

    contributing = {name: value for name, value in factors.items() if value}
    return {
        "score": score,
        "level": risk_level(score),
        "factors": factors,
        "contributing_factors": contributing,
        "evidence": evidence,
        "confidence": confidence["band"],
        "confidence_rationale": confidence["rationale"],
        "unknowns": unknowns,
        "justification": "; ".join(
            f"{name.replace('_', ' ')} +{value}" for name, value in contributing.items()
        )
        or "No pre-deployment risk factors were identified from the submitted change.",
        # Load-bearing: the score ranks *proposals* against each other from
        # declared configuration. It is not a probability of failure and must
        # not be read as one.
        "interpretation": (
            "This score ranks the proposed change by the risk factors present in its declared "
            "configuration and its dependency reach. It is not a probability of failure and does "
            "not assert that any listed resource will be disrupted."
        ),
        "confirmed_cause": False,
    }


def _collect_unknowns(
    change: ProposedChange,
    comparison: Mapping[str, Any],
    blast_radius: Mapping[str, Any],
    simulation: Mapping[str, Any],
) -> list[str]:
    """Every declared gap, from ingestion through simulation, in one list."""
    unknowns: list[str] = []
    unknowns.extend(change.ingestion_warnings)
    for stage in (comparison, blast_radius, simulation):
        unknowns.extend(str(value) for value in stage.get("unknowns", []) or [])
    # Preserve order while removing duplicates; the same gap is often reported
    # by more than one stage.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in unknowns:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _confidence(
    *,
    unknowns: Sequence[str],
    change: ProposedChange,
    comparison: Mapping[str, Any],
    blast_radius: Mapping[str, Any],
) -> dict[str, str]:
    """Derive a confidence band from the completeness of the inputs."""
    if not change.effective_changes:
        return {
            "band": CONFIDENCE_UNKNOWN,
            "rationale": "The submitted change contained no effective resource changes to assess.",
        }
    if int(comparison.get("discovered_count", 0)) == 0:
        return {
            "band": CONFIDENCE_UNKNOWN,
            "rationale": (
                "No discovered state was available in scope, so neither drift nor dependency "
                "reach could be established."
            ),
        }

    penalties: list[str] = []
    unresolved = int(comparison.get("counts", {}).get(FINDING_MISSING_TARGET, 0))
    if unresolved and unresolved >= len(change.effective_changes):
        # Discovered state exists, but none of it is the state being changed --
        # typically because the change targets a scope the caller cannot see.
        # Partial visibility here is indistinguishable from no visibility.
        return {
            "band": CONFIDENCE_UNKNOWN,
            "rationale": (
                "None of the proposed changes resolved to discovered state in scope, so neither "
                "drift nor dependency reach could be established for this change."
            ),
        }

    if change.ingestion_warnings:
        penalties.append(f"{len(change.ingestion_warnings)} ingestion warning(s)")
    if blast_radius.get("truncated"):
        penalties.append("blast-radius traversal was truncated")
    if unresolved:
        penalties.append(f"{unresolved} change target(s) missing from discovered state")

    if not penalties and not unknowns:
        return {
            "band": CONFIDENCE_HIGH,
            "rationale": (
                "Every proposed change resolved to discovered state and the dependency traversal "
                "completed without truncation."
            ),
        }
    if len(penalties) >= 2:
        return {
            "band": CONFIDENCE_LOW,
            "rationale": "Assessment inputs were materially incomplete: " + "; ".join(penalties) + ".",
        }
    return {
        "band": CONFIDENCE_MEDIUM,
        "rationale": (
            "Assessment inputs were mostly complete with declared gaps: "
            + ("; ".join(penalties) if penalties else "see unknowns")
            + "."
        ),
    }
