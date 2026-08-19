from __future__ import annotations

import copy
import hashlib
import re
from typing import Any


class PlanRepository:
    """Read-only projection repository for generated draft plans and ontology rows."""

    def __init__(self, *, max_plans: int = 1000) -> None:
        if isinstance(max_plans, bool) or not isinstance(max_plans, int):
            raise TypeError("max_plans must be an integer")
        if max_plans < 1:
            raise ValueError("max_plans must be positive")
        self.max_plans = max_plans
        self._plans: tuple[dict[str, Any], ...] = ()

    def replace_generation(self, plans: list[dict[str, Any]]) -> None:
        if len(plans) > self.max_plans:
            raise ValueError("Generated remediation plans exceed repository bound")
        identities = [str(plan.get("plan_id") or "") for plan in plans]
        if any(not identity for identity in identities) or len(identities) != len(set(identities)):
            raise ValueError("Remediation repository requires unique plan_id")
        self._plans = tuple(copy.deepcopy(plans))

    def list(self) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self._plans))

    def get(self, plan_id: str) -> dict[str, Any] | None:
        return next(
            (copy.deepcopy(plan) for plan in self._plans if plan["plan_id"] == plan_id),
            None,
        )

    def ontology_projection(self) -> dict[str, Any]:
        entities: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        for plan in self._plans:
            plan_id = plan["plan_id"]
            entities.append(self._entity(plan_id, "RemediationPlan", plan["title"]))
            risk_id = f"{plan_id}:risk"
            simulation_id = f"{plan_id}:simulation"
            rollback_id = f"{plan_id}:rollback"
            entities.extend(
                [
                    self._entity(risk_id, "RiskAssessment", plan["risk_assessment"]["overall_risk"]["level"]),
                    self._entity(simulation_id, "SimulationResult", "Risk reduction simulation"),
                    self._entity(rollback_id, "RollbackPlan", "Reversible rollback strategy"),
                ]
            )
            for index, approval in enumerate(plan["approval_requirements"], 1):
                approval_id = f"{plan_id}:approval:{index}"
                entities.append(
                    self._entity(approval_id, "ApprovalRequirement", approval["role"])
                )
                relationships.append(
                    self._relationship(plan_id, "requiresApproval", approval_id)
                )
            for step in plan["execution_steps"]:
                step_id = f"{plan_id}:step:{step['step_number']}"
                entities.append(
                    self._entity(step_id, "ExecutionStep", step["description"])
                )
                relationships.append(self._relationship(plan_id, "hasStep", step_id))
            application = self._safe_key(plan["application"])
            service = self._safe_key(plan["business_service"])
            application_id = f"application:{application}"
            service_id = f"service:{service}"
            entities.extend(
                [
                    self._entity(application_id, "Application", plan["application"]),
                    self._entity(
                        service_id, "BusinessService", plan["business_service"]
                    ),
                ]
            )
            relationships.extend(
                [
                    self._relationship(application_id, "requiresPlan", plan_id),
                    self._relationship(plan_id, "mitigatesRisk", risk_id),
                    self._relationship(plan_id, "protectsService", service_id),
                    self._relationship(plan_id, "hasRollbackPlan", rollback_id),
                    self._relationship(plan_id, "hasSimulation", simulation_id),
                ]
            )
        return {
            "entities": list(
                {row["entity_id"]: row for row in entities}.values()
            ),
            "relationships": relationships,
            "read_only": True,
        }

    @staticmethod
    def _entity(identity: str, entity_type: str, name: str) -> dict[str, str]:
        return {
            "entity_id": identity,
            "entity_type": entity_type,
            "name": str(name)[:1024],
            "lifecycle_status": "draft",
        }

    @staticmethod
    def _relationship(subject: str, relationship_type: str, object_id: str) -> dict[str, str]:
        identity = hashlib.sha256(
            f"{subject}|{relationship_type}|{object_id}".encode()
        ).hexdigest()[:24]
        return {
            "relationship_id": f"remediation-rel:{identity}",
            "subject_id": subject,
            "relationship_type": relationship_type,
            "object_id": object_id,
            "lifecycle_status": "draft",
        }

    @staticmethod
    def _safe_key(value: Any) -> str:
        text = re.sub(r"[^a-z0-9]+", "-", str(value or "unknown").casefold()).strip("-")
        return text[:128] or "unknown"
