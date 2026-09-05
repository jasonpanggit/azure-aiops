from __future__ import annotations

import hashlib
import time
from typing import Any

from .action_version import action_version_for
from .approval_engine import ApprovalEngine
from .business_decision import BusinessDecisionEngine
from .dependency_analyzer import DependencyAnalyzer
from .execution_simulator import ExecutionSimulator
from .impact_estimator import ImpactEstimator
from .plan_prioritizer import PlanPrioritizer
from .risk_analyzer import RiskAnalyzer
from .rollback_planner import RollbackPlanner


class RemediationGenerator:
    """Generates approval-ready plans from declarative catalog actions."""

    def __init__(
        self,
        *,
        dependency_analyzer: DependencyAnalyzer,
        risk_analyzer: RiskAnalyzer,
        approval_engine: ApprovalEngine,
        rollback_planner: RollbackPlanner,
        simulator: ExecutionSimulator,
        impact_estimator: ImpactEstimator,
        prioritizer: PlanPrioritizer,
        telemetry=None,
        clock=time.monotonic,
        defender_correlator: Any = None,
        business_decision_engine: BusinessDecisionEngine | None = None,
    ) -> None:
        self.dependencies = dependency_analyzer
        self.risks = risk_analyzer
        self.approvals = approval_engine
        self.rollback = rollback_planner
        self.simulator = simulator
        self.impacts = impact_estimator
        self.prioritizer = prioritizer
        self.telemetry = telemetry
        self.clock = clock
        self.defender_correlator = defender_correlator
        self.business_decisions = business_decision_engine or BusinessDecisionEngine()

    def generate(self, opportunity: dict[str, Any]) -> dict[str, Any]:
        resource = opportunity["_resource"]
        action = opportunity["_action"]
        started = self.clock()
        dependencies = self.dependencies.analyze(resource)
        if self.telemetry:
            self.telemetry.dependency_traversal_latency.record(self.clock() - started)
        started = self.clock()
        risk = self.risks.analyze(resource, dependencies, action)
        if self.telemetry:
            self.telemetry.risk_analysis_duration.record(self.clock() - started)
        started = self.clock()
        rollback = self.rollback.build(action)
        if self.telemetry:
            self.telemetry.rollback_generation_time.record(self.clock() - started)
        started = self.clock()
        simulation = self.simulator.simulate(resource, action, risk)
        if self.telemetry:
            self.telemetry.simulation_duration.record(self.clock() - started)
        impact = self.impacts.estimate(risk, dependencies, simulation)
        started = self.clock()
        approvals = self.approvals.requirements(resource, action, risk)
        if self.telemetry:
            self.telemetry.approval_generation_time.record(self.clock() - started)
        priority = self.prioritizer.prioritize(resource, dependencies, simulation)
        case = self._case_for(opportunity["_resource_key"])
        decision = self.business_decisions.decide(
            case,
            dependencies=dependencies,
            risk=risk,
            simulation=simulation,
            rollback=rollback,
            action=action,
        )
        evidence_citations = list((case or {}).get("evidence_citations") or [])
        secure_score_improvement = self._secure_score_improvement(case, action)
        plan_id = "RMP-" + hashlib.sha256(
            f"{opportunity['_resource_key']}|{action['action_id']}".encode()
        ).hexdigest()[:16].upper()

        # Shared, evidence-sensitive action_version (Phase 03.5, D-04) --
        # the same helper used by the live patch/Defender planners.
        action_version = action_version_for(
            action_id=action["action_id"],
            target_id=str(opportunity["_resource_key"]),
            scope={
                "execution_steps": action.get("execution_steps"),
                "rollback_actions": action.get("rollback_actions"),
            },
            evidence_citations=evidence_citations,
        )
        steps = [
            {
                "step_number": index,
                "description": str(description).strip()[:1024],
                "stage": str(
                    (action.get("deployment_stages") or ["Planning"])[
                        min(index - 1, len(action.get("deployment_stages") or ["Planning"]) - 1)
                    ]
                ),
                "requires_approval": True,
                "execution_status": "Not Executed",
            }
            for index, description in enumerate(action["execution_steps"][:50], 1)
        ]
        confidence = min(
            0.35
            + (0.15 if opportunity["evidence"] else 0)
            + min(len(dependencies["owners"] + dependencies["service_owners"]), 2) * 0.1
            + (0.15 if approvals else 0)
            + (0.1 if rollback["reversible"] else 0),
            0.95,
        )
        return {
            "plan_id": plan_id,
            "action_version": action_version,
            "title": str(action.get("title") or "Remediation plan")[:512],
            "status": "Draft - Approval Required",
            "resource": opportunity["resource"],
            "resource_key": opportunity["_resource_key"],
            "application": opportunity["application"],
            "business_service": opportunity["business_service"],
            "environment": opportunity.get("environment", ""),
            "owner": opportunity.get("owner", ""),
            "subscription_id": opportunity.get("subscription_id", ""),
            "subscription_connection": opportunity.get(
                "subscription_connection", ""
            ),
            "opportunity_type": opportunity["opportunity_type"],
            "action_id": str(opportunity.get("action_id") or action.get("action_id") or ""),
            "objective": f"Reduce {opportunity['opportunity_type'].casefold()} using the governed action catalog.",
            "execution_steps": steps,
            "dependencies": dependencies,
            "risk_assessment": risk,
            "business_impact": impact,
            "approval_requirements": approvals,
            "rollback_plan": rollback,
            "simulation_result": simulation,
            **priority,
            "risk_drivers": risk["overall_risk"]["drivers"],
            "evidence": opportunity["evidence"],
            "evidence_citations": evidence_citations,
            "business_decision": decision,
            "expected_secure_score_improvement": secure_score_improvement,
            "uncertainty": list(decision["unknowns"]),
            "confidence": round(confidence, 2),
            "confidence_kind": "Plan evidence completeness, not execution success probability",
            "recommended_action": {
                "suggested_action": "Submit this draft plan and its evidence for required human approvals; no change is executed.",
                "advisory_only": True,
            },
            "execution_authorized": False,
            "execution_performed": False,
            "read_only": True,
        }

    def _case_for(self, resource_key: str) -> dict[str, Any] | None:
        """Look up the correlated Defender case for this resource, if any.

        Absent a correlator, or when a resource carries no correlated case,
        return None; ``BusinessDecisionEngine.decide`` handles a missing case
        by reporting unknown business mapping rather than failing, per
        D-14/D-26 (plans target Defender evidence, they never claim to have
        cleared it).
        """
        correlator = self.defender_correlator
        if correlator is None:
            return None
        for case in correlator.cases():
            if case.get("resource_key") == resource_key:
                return case
        return None

    @staticmethod
    def _secure_score_improvement(
        case: dict[str, Any] | None, action: dict[str, Any]
    ) -> dict[str, Any]:
        """Expected secure-score point improvement from this action's effect
        on the case's own secure-score control evidence.

        Marked unknown -- never a guessed number -- when the case carries no
        secure-score control citation, per D-15.
        """
        if not case:
            return {"status": "unknown", "detail": "No correlated Defender case for this resource.", "points": 0}
        citations = [
            citation
            for citation in case.get("evidence_citations") or []
            if citation.get("source_type") == "secure_score_control"
        ]
        if not citations:
            return {
                "status": "unknown",
                "detail": "No secure-score control evidence is associated with this resource.",
                "points": 0,
            }
        effectiveness = (action.get("effectiveness") or {}).get("compliance_improvement_percent")
        if not isinstance(effectiveness, int) or effectiveness <= 0:
            effectiveness = (action.get("effectiveness") or {}).get("risk_reduction_percent")
        if not isinstance(effectiveness, int) or effectiveness <= 0:
            return {
                "status": "unknown",
                "detail": "The governed action carries no compliance or risk-reduction effectiveness value.",
                "points": 0,
            }
        points = max(1, round(effectiveness / 10))
        citation_ids = sorted({str(citation.get("source_id") or "") for citation in citations if citation.get("source_id")})
        return {
            "status": "known",
            "points": points,
            "detail": f"Estimated +{points} secure score point(s) from resolving {len(citations)} control gap(s).",
            "evidence_citations": [f"secure_score_control:{cid}" for cid in citation_ids],
        }
