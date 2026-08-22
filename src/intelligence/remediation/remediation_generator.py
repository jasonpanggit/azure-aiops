from __future__ import annotations

import hashlib
import time
from typing import Any

from .approval_engine import ApprovalEngine
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
        plan_id = "RMP-" + hashlib.sha256(
            f"{opportunity['_resource_key']}|{action['action_id']}".encode()
        ).hexdigest()[:16].upper()
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
            "title": str(action.get("title") or "Remediation plan")[:512],
            "status": "Draft - Approval Required",
            "resource": opportunity["resource"],
            "application": opportunity["application"],
            "business_service": opportunity["business_service"],
            "environment": opportunity.get("environment", ""),
            "owner": opportunity.get("owner", ""),
            "subscription_id": opportunity.get("subscription_id", ""),
            "subscription_connection": opportunity.get(
                "subscription_connection", ""
            ),
            "opportunity_type": opportunity["opportunity_type"],
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
