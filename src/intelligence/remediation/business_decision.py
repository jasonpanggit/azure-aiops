"""Business decision engine: consequence, disposition, alternatives -- not finding closure.

The user's locked correction is that remediation is not finding closure and
that technical severity alone must never decide priority. Every other module
in this package answers "what is technically wrong and how would we fix it";
this module answers the question an operator actually has to defend: what
happens if we act, what happens if we do not, why now or why later or why
never, and what the alternatives cost.

``BusinessDecisionEngine`` takes a correlated Defender case (as built by
``DefenderRemediationCorrelator``, or ``None`` when no Defender evidence
exists for the resource) together with the dependency, risk, simulation, and
rollback views already produced elsewhere in this package, and returns a
structured decision. It never computes a new numeric severity score and never
counts findings addressed or closed (D-17): the disposition guards below are
explicit preconditions, not an opaque weighted score, so an approver can see
exactly which evidence justified the outcome (D-08, D-10).

A resource lacking a known business mapping can never receive the
``act_now`` disposition regardless of technical severity (D-09) -- that
invariant is enforced as a hard guard order below, not as a tie-breaker.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DISPOSITIONS = ("act_now", "schedule", "defer", "not_applicable", "escalate")

_COST_DIMENSIONS = (
    "service_risk",
    "customer_impact",
    "operational_continuity",
    "compliance_exposure",
    "change_risk",
    "downtime",
    "effort",
    "opportunity_cost",
)

_SEVERITY_EXPOSURE_SCORE = {"critical": 100, "high": 75, "medium": 50, "low": 25}
_ACTIVE_EVIDENCE_SOURCE_TYPES = frozenset({"alert", "attack_path"})


def _unknown(detail: str) -> dict[str, Any]:
    return {"status": "unknown", "detail": detail, "evidence_citations": []}


def _known(detail: str, citations: list[str]) -> dict[str, Any]:
    return {"status": "known", "detail": detail, "evidence_citations": citations}


class BusinessDecisionEngine:
    """Turns a correlated case plus planning views into an operator decision.

    Every method is a pure read of its inputs: it never calls Azure, never
    shells out, and never mutates the case, dependency, risk, simulation, or
    rollback views it is given.
    """

    def decide(
        self,
        case: Mapping[str, Any] | None,
        *,
        dependencies: Mapping[str, Any] | None = None,
        risk: Mapping[str, Any] | None = None,
        simulation: Mapping[str, Any] | None = None,
        rollback: Mapping[str, Any] | None = None,
        action: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        case = dict(case or {})
        business_context = dict(dependencies or case.get("business_context") or {})
        citations = list(case.get("evidence_citations") or [])
        citation_ids = sorted(
            {f"{c.get('source_type')}:{c.get('source_id')}" for c in citations if c.get("source_id")}
        )[:50]
        mapped = bool(
            business_context.get("affected_applications")
            or business_context.get("affected_services")
        )
        contradictory = bool(case.get("contradictory_evidence"))
        max_severity = str(case.get("max_severity") or "").casefold()
        not_applicable_evidence = case.get("not_applicable_evidence")
        active_path = any(
            str(c.get("source_type") or "") in _ACTIVE_EVIDENCE_SOURCE_TYPES for c in citations
        )
        business_impact_score = None
        if risk is not None:
            business_impact_score = (risk.get("business_risk") or {}).get("score")

        disposition, urgency_rationale, review_requirements = self._disposition(
            not_applicable_evidence=not_applicable_evidence,
            mapped=mapped,
            contradictory=contradictory,
            active_path=active_path,
            max_severity=max_severity,
            business_impact_score=business_impact_score,
            risk=risk,
            citation_ids=citation_ids,
            resource_name=str(case.get("resource_name") or "this resource"),
            weakness_key=str(case.get("weakness_key") or ""),
            degraded_families=self._degraded_families(case),
        )

        cost_of_action = self._cost_of_action(
            mapped=mapped,
            business_context=business_context,
            risk=risk,
            rollback=rollback,
            action=action,
            citation_ids=citation_ids,
        )
        cost_of_inaction = self._cost_of_inaction(
            mapped=mapped,
            business_context=business_context,
            max_severity=max_severity,
            simulation=simulation,
            citation_ids=citation_ids,
        )
        confidence = self._confidence(
            mapped=mapped,
            contradictory=contradictory,
            citations=citations,
            degraded=bool(self._degraded_families(case)),
        )
        business_impact = self._business_impact_summary(
            mapped=mapped, business_context=business_context, risk=risk, max_severity=max_severity
        )
        options = self._options(
            disposition,
            case=case,
            business_context=business_context,
            risk=risk,
            simulation=simulation,
            rollback=rollback,
            action=action,
            cost_of_action=cost_of_action,
            cost_of_inaction=cost_of_inaction,
            citation_ids=citation_ids,
        )
        unknown_dimensions = sorted(
            {
                name
                for section in (cost_of_action, cost_of_inaction)
                for name, entry in section.items()
                if entry.get("status") == "unknown"
            }
        )

        return {
            "disposition": disposition,
            "urgency_rationale": urgency_rationale,
            "cost_of_action": cost_of_action,
            "cost_of_inaction": cost_of_inaction,
            "business_impact": business_impact,
            "confidence": confidence,
            "review_requirements": review_requirements,
            "options": options,
            "observed_facts": list(case.get("observed_facts") or []),
            "derived_inferences": list(case.get("derived_inferences") or []),
            "unknowns": sorted({*case.get("unknowns", []), *unknown_dimensions}),
            "read_only": True,
        }

    # -- disposition -----------------------------------------------------

    @staticmethod
    def _degraded_families(case: Mapping[str, Any]) -> list[str]:
        statuses = case.get("source_family_status") or {}
        if not isinstance(statuses, Mapping):
            return []
        return sorted(
            name
            for name, status in statuses.items()
            if isinstance(status, Mapping) and str(status.get("availability") or "unknown") != "available"
        )

    def _disposition(
        self,
        *,
        not_applicable_evidence: Any,
        mapped: bool,
        contradictory: bool,
        active_path: bool,
        max_severity: str,
        business_impact_score: int | None,
        risk: Mapping[str, Any] | None,
        citation_ids: list[str],
        resource_name: str,
        weakness_key: str,
        degraded_families: list[str],
    ) -> tuple[str, dict[str, Any], list[str]]:
        review_requirements: list[str] = []

        if not_applicable_evidence:
            return (
                "not_applicable",
                {
                    "reason_code": "EVIDENCE_CONFIRMS_NOT_APPLICABLE",
                    "message": (
                        f"Evidence confirms the finding does not affect {resource_name}: "
                        f"{not_applicable_evidence}."
                    ),
                    "evidence_citations": citation_ids,
                },
                review_requirements,
            )

        if not mapped or contradictory:
            if not mapped:
                review_requirements.append(
                    f"Confirm business ownership and mapping for {resource_name} before any "
                    "disposition above escalate can be trusted."
                )
            if contradictory:
                review_requirements.append(
                    f"Resolve conflicting severity signals across Defender source families for "
                    f"weakness {weakness_key or 'this weakness'} before trusting a single severity value."
                )
            reason_code = (
                "BUSINESS_MAPPING_UNKNOWN_OR_CONTRADICTORY"
                if not mapped
                else "CONTRADICTORY_EVIDENCE"
            )
            return (
                "escalate",
                {
                    "reason_code": reason_code,
                    "message": (
                        f"{(max_severity or 'unspecified')} severity signal cannot be promoted to "
                        "immediate action on technical severity alone while the business mapping is "
                        "unknown or the evidence is contradictory; escalate for human review."
                    ),
                    "evidence_citations": citation_ids,
                },
                review_requirements,
            )

        if degraded_families:
            review_requirements.append(
                "Confirm degraded Defender source family status before treating this decision as "
                f"final: {', '.join(degraded_families)}."
            )

        if active_path and (
            max_severity in {"critical", "high"}
            or (business_impact_score is not None and business_impact_score >= 75)
        ):
            return (
                "act_now",
                {
                    "reason_code": "ACTIVE_BUSINESS_IMPACT_PATH",
                    "message": (
                        "An active or imminent evidenced path to business impact is present against "
                        "a known business mapping; act now."
                    ),
                    "evidence_citations": citation_ids,
                },
                review_requirements,
            )

        change_risk_score = (risk.get("execution_risk") or {}).get("score") if risk else None
        current_exposure_score = _SEVERITY_EXPOSURE_SCORE.get(max_severity)
        if (
            change_risk_score is not None
            and current_exposure_score is not None
            and change_risk_score > current_exposure_score
        ):
            return (
                "defer",
                {
                    "reason_code": "CHANGE_RISK_EXCEEDS_EXPOSURE",
                    "message": (
                        f"Change risk ({change_risk_score}) exceeds current exposure "
                        f"({current_exposure_score}) for this {max_severity or 'unspecified'}-severity "
                        "finding; defer until the change risk is reduced or exposure grows."
                    ),
                    "evidence_citations": citation_ids,
                },
                review_requirements,
            )

        return (
            "schedule",
            {
                "reason_code": "BOUNDED_EXPOSURE_MAINTENANCE_WINDOW",
                "message": (
                    "Exposure is bounded and no active exploitation is evidenced against a known "
                    "business mapping; schedule within an identified maintenance window."
                ),
                "evidence_citations": citation_ids,
            },
            review_requirements,
        )

    # -- cost sections -----------------------------------------------------

    def _cost_of_action(
        self,
        *,
        mapped: bool,
        business_context: Mapping[str, Any],
        risk: Mapping[str, Any] | None,
        rollback: Mapping[str, Any] | None,
        action: Mapping[str, Any] | None,
        citation_ids: list[str],
    ) -> dict[str, Any]:
        services = business_context.get("affected_services") or business_context.get(
            "affected_applications"
        )
        dependency_count = business_context.get("dependency_count")
        section: dict[str, Any] = {}
        section["service_risk"] = (
            _known(
                f"Applying the fix touches {dependency_count} bounded dependency reference(s) "
                f"affecting {', '.join(services)}.",
                citation_ids,
            )
            if mapped
            else _unknown("Service risk of acting cannot be scoped without a known business mapping.")
        )
        section["customer_impact"] = (
            _known(
                f"Customer or SLA exposure during the change is bounded to {', '.join(services)}.",
                citation_ids,
            )
            if mapped
            else _unknown("Customer impact of acting cannot be scoped without a known business mapping.")
        )
        section["operational_continuity"] = (
            _known(
                f"Rollback plan defines {len(rollback['rollback_actions'])} reversible action(s) and "
                f"{len(rollback['validation_steps'])} validation step(s) to restore continuity if the "
                "change fails.",
                citation_ids,
            )
            if rollback
            else _unknown("No rollback plan view was supplied to assess operational continuity.")
        )
        section["compliance_exposure"] = (
            _known(
                f"Operational posture risk scored {risk['operational_risk']['score']} "
                f"({risk['operational_risk']['level']}); the change carries this compliance exposure "
                "until it completes.",
                citation_ids,
            )
            if risk and risk.get("operational_risk", {}).get("score") is not None
            else _unknown("No risk view was supplied to assess compliance exposure of acting.")
        )
        section["change_risk"] = (
            _known(
                f"Execution risk scored {risk['execution_risk']['score']} "
                f"({risk['execution_risk']['level']}) driven by "
                f"{', '.join(risk['execution_risk']['drivers'])}.",
                citation_ids,
            )
            if risk
            else _unknown("No risk view was supplied to assess the change risk of acting.")
        )
        section["downtime"] = _unknown(
            "The execution simulator does not produce a downtime estimate for this action."
        )
        section["effort"] = (
            _known(
                f"{len(action['execution_steps'])} execution step(s) across "
                f"{len(action['deployment_stages'])} deployment stage(s).",
                citation_ids,
            )
            if action
            else _unknown("No catalog action metadata was supplied to assess effort.")
        )
        section["opportunity_cost"] = _unknown(
            "No opportunity-cost evidence source is available for acting."
        )
        return section

    def _cost_of_inaction(
        self,
        *,
        mapped: bool,
        business_context: Mapping[str, Any],
        max_severity: str,
        simulation: Mapping[str, Any] | None,
        citation_ids: list[str],
    ) -> dict[str, Any]:
        severity_text = max_severity or "unspecified"
        services = business_context.get("affected_services") or business_context.get(
            "affected_applications"
        )
        section: dict[str, Any] = {}
        section["service_risk"] = (
            _known(
                f"Continued {severity_text}-severity exposure on {', '.join(services)} until remediated.",
                citation_ids,
            )
            if mapped
            else _unknown(
                f"Continued {severity_text}-severity exposure on an unmapped resource; business impact "
                "cannot be bounded until ownership is confirmed."
            )
        )
        section["customer_impact"] = (
            _known(
                f"Customers or SLAs on {', '.join(services)} remain exposed to the unremediated finding.",
                citation_ids,
            )
            if mapped
            else _unknown("Customer impact of inaction cannot be scoped without a known business mapping.")
        )
        section["operational_continuity"] = (
            _known(
                f"Operational debt remains at {simulation['current_operational_debt_score']} rather than "
                f"the estimated {simulation['estimated_residual_operational_debt_score']} after action.",
                citation_ids,
            )
            if simulation
            else _unknown("No simulation view was supplied to assess operational continuity of inaction.")
        )
        section["compliance_exposure"] = (
            _known(
                f"Forgoing action forgoes an estimated {simulation['compliance_improvement_percent']}% "
                "compliance improvement.",
                citation_ids,
            )
            if simulation
            else _unknown("No simulation view was supplied to assess compliance exposure of inaction.")
        )
        section["change_risk"] = _known(
            "No infrastructure change occurs while deferred; change risk is not incurred, but the "
            "underlying exposure persists.",
            citation_ids,
        )
        section["downtime"] = _known(
            "No planned downtime is introduced by declining to act.", citation_ids
        )
        section["effort"] = _known(
            "No remediation effort is incurred while the finding remains open.", citation_ids
        )
        section["opportunity_cost"] = (
            _known(
                f"Forgoing action forgoes an estimated {simulation['risk_reduction_percent']}% risk "
                "reduction and secure-score improvement.",
                citation_ids,
            )
            if simulation
            else _unknown("No simulation view was supplied to assess the opportunity cost of inaction.")
        )
        return section

    @staticmethod
    def _confidence(
        *, mapped: bool, contradictory: bool, citations: list[Mapping[str, Any]], degraded: bool
    ) -> float:
        source_types = {str(c.get("source_type") or "") for c in citations if c.get("source_type")}
        base = 0.85 if mapped else 0.3
        corroboration = min(0.1, 0.02 * max(0, len(source_types) - 1))
        confidence = min(base + corroboration, 0.95 if mapped else 0.45)
        if degraded:
            confidence -= 0.15
        if contradictory:
            confidence -= 0.2
        return round(max(0.05, confidence), 2)

    @staticmethod
    def _business_impact_summary(
        *,
        mapped: bool,
        business_context: Mapping[str, Any],
        risk: Mapping[str, Any] | None,
        max_severity: str,
    ) -> dict[str, Any]:
        if not mapped:
            return {
                "status": "unknown",
                "detail": "Business impact cannot be scoped without a known business mapping.",
            }
        services = business_context.get("affected_services") or business_context.get(
            "affected_applications"
        )
        level = None
        if risk is not None:
            level = (risk.get("business_risk") or {}).get("level")
        return {
            "status": "known",
            "detail": (
                f"{(max_severity or 'unspecified')}-severity finding affecting {', '.join(services)}"
                + (f" with {level} business criticality" if level else "")
                + "."
            ),
            "affected_services": list(services),
        }

    # -- alternatives comparison (D-13) ------------------------------------

    def _options(
        self,
        disposition: str,
        *,
        case: Mapping[str, Any],
        business_context: Mapping[str, Any],
        risk: Mapping[str, Any] | None,
        simulation: Mapping[str, Any] | None,
        rollback: Mapping[str, Any] | None,
        action: Mapping[str, Any] | None,
        cost_of_action: Mapping[str, Any],
        cost_of_inaction: Mapping[str, Any],
        citation_ids: list[str],
    ) -> list[dict[str, Any]]:
        option_ids = ["act_now", "schedule", "defer", "no_change"]
        if case.get("not_applicable_evidence"):
            option_ids.append("not_applicable")
        if disposition == "escalate":
            option_ids.append("escalate")
        return [
            self._build_option(
                option_id,
                disposition=disposition,
                business_context=business_context,
                risk=risk,
                simulation=simulation,
                rollback=rollback,
                action=action,
                cost_of_action=cost_of_action,
                cost_of_inaction=cost_of_inaction,
                citation_ids=citation_ids,
            )
            for option_id in option_ids
        ]

    def _build_option(
        self,
        option_id: str,
        *,
        disposition: str,
        business_context: Mapping[str, Any],
        risk: Mapping[str, Any] | None,
        simulation: Mapping[str, Any] | None,
        rollback: Mapping[str, Any] | None,
        action: Mapping[str, Any] | None,
        cost_of_action: Mapping[str, Any],
        cost_of_inaction: Mapping[str, Any],
        citation_ids: list[str],
    ) -> dict[str, Any]:
        escalated = disposition == "escalate"
        recommended = option_id == disposition
        approvable = not escalated and option_id != "escalate"
        reversible = rollback.get("reversible") if rollback else None
        risk_reduction = simulation.get("risk_reduction_percent") if simulation else None
        effort_detail = (
            f"{len(action['execution_steps'])} execution step(s) across "
            f"{len(action['deployment_stages'])} deployment stage(s)."
            if action
            else None
        )

        if option_id == "act_now":
            return {
                "option_id": option_id,
                "label": "Act now",
                "recommended": recommended,
                "approvable": approvable,
                "pros": ["Reduces risk immediately while business-impact evidence is active"],
                "cons": [
                    "Requires immediate maintenance coordination",
                    "Change risk is incurred without a scheduled window",
                ],
                "residual_risk": _known(
                    f"Estimated {risk_reduction}% risk reduction leaves residual exposure open."
                    if risk_reduction is not None
                    else "Residual risk after acting is not estimated by the simulator.",
                    citation_ids,
                )
                if risk_reduction is not None
                else _unknown("No simulation view was supplied to estimate residual risk."),
                "effort": _known(effort_detail, citation_ids)
                if effort_detail
                else _unknown("No catalog action metadata was supplied to assess effort."),
                "downtime": _unknown(
                    "The execution simulator does not produce a downtime estimate for this action."
                ),
                "reversibility": _known(
                    "Reversible: a rollback plan exists." if reversible else "Not reversible.",
                    citation_ids,
                )
                if reversible is not None
                else _unknown("No rollback view was supplied to assess reversibility."),
                "business_impact": cost_of_action["service_risk"],
            }
        if option_id == "schedule":
            return {
                "option_id": option_id,
                "label": "Schedule within a maintenance window",
                "recommended": recommended,
                "approvable": approvable,
                "pros": ["Bounds change risk to a planned maintenance window"],
                "cons": ["Exposure persists until the scheduled window arrives"],
                "residual_risk": cost_of_inaction["service_risk"],
                "effort": _known(effort_detail, citation_ids)
                if effort_detail
                else _unknown("No catalog action metadata was supplied to assess effort."),
                "downtime": _unknown(
                    "The execution simulator does not produce a downtime estimate for this action."
                ),
                "reversibility": _known(
                    "Reversible: a rollback plan exists." if reversible else "Not reversible.",
                    citation_ids,
                )
                if reversible is not None
                else _unknown("No rollback view was supplied to assess reversibility."),
                "business_impact": cost_of_action["service_risk"],
            }
        if option_id == "defer":
            return {
                "option_id": option_id,
                "label": "Defer",
                "recommended": recommended,
                "approvable": approvable,
                "pros": ["Avoids incurring change risk while it exceeds current exposure"],
                "cons": ["Exposure persists until change risk is reassessed"],
                "residual_risk": cost_of_inaction["service_risk"],
                "effort": _known(
                    "No remediation effort is incurred while deferred.", citation_ids
                ),
                "downtime": _known(
                    "No planned downtime is introduced by deferring.", citation_ids
                ),
                "reversibility": _known(
                    "Fully reversible: no change is made while deferred.", citation_ids
                ),
                "business_impact": cost_of_inaction["service_risk"],
            }
        if option_id == "not_applicable":
            return {
                "option_id": option_id,
                "label": "Not applicable",
                "recommended": recommended,
                "approvable": approvable,
                "pros": ["No action required; evidence confirms the finding does not affect this resource"],
                "cons": [],
                "residual_risk": _known(
                    "None: evidence confirms non-applicability.", citation_ids
                ),
                "effort": _known("None.", citation_ids),
                "downtime": _known("None.", citation_ids),
                "reversibility": _known("Not applicable.", citation_ids),
                "business_impact": _known("None.", citation_ids),
            }
        if option_id == "escalate":
            return {
                "option_id": option_id,
                "label": "Escalate for human review",
                "recommended": recommended,
                "approvable": False,
                "pros": ["Routes to human review before any commitment is made"],
                "cons": ["Delays remediation until business mapping or evidence is resolved"],
                "residual_risk": _unknown(
                    "Residual risk is unresolved until the escalation review completes."
                ),
                "effort": _unknown("Requires manual investigation effort to resolve."),
                "downtime": _unknown("Unknown pending review."),
                "reversibility": _unknown("Not applicable until the review completes."),
                "business_impact": _unknown(
                    "Unknown pending business mapping or evidence confirmation."
                ),
            }
        # option_id == "no_change"
        return {
            "option_id": option_id,
            "label": "No change",
            "recommended": recommended,
            "approvable": approvable,
            "pros": ["No operational disruption"],
            "cons": ["The finding remains open indefinitely"],
            "residual_risk": cost_of_inaction["service_risk"],
            "effort": cost_of_inaction["effort"],
            "downtime": cost_of_inaction["downtime"],
            "reversibility": _known(
                "Fully reversible: no change is made.", citation_ids
            ),
            "business_impact": cost_of_inaction["service_risk"],
        }
