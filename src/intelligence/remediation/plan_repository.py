from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from ontology.confidence import compute_confidence

from .approval_decisions import RemediationDecisionStore, RevisionedDocumentStore


class PlanRepository:
    """Read-only projection repository for generated draft plans and ontology rows."""

    def __init__(
        self,
        *,
        max_plans: int = 1000,
        decision_store: RemediationDecisionStore | None = None,
        decision_document_store: RevisionedDocumentStore | None = None,
    ) -> None:
        if isinstance(max_plans, bool) or not isinstance(max_plans, int):
            raise TypeError("max_plans must be an integer")
        if max_plans < 1:
            raise ValueError("max_plans must be positive")
        if decision_store is not None and decision_document_store is not None:
            raise ValueError("Use either decision_store or decision_document_store, not both")
        self.max_plans = max_plans
        self._plans: tuple[dict[str, Any], ...] = ()
        self.decisions = decision_store or RemediationDecisionStore(
            document_store=decision_document_store
        )

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
        pending_relationships: list[dict[str, Any]] = []
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
            defender_relationships = self._defender_relationships_for_plan(
                plan,
                pending_relationships=pending_relationships,
            )
            relationships.extend(defender_relationships)
            for relationship in defender_relationships:
                entities.append(
                    self._entity(
                        relationship["object_id"],
                        relationship["object_type"],
                        relationship["object_id"],
                    )
                )
            for decision in self.decisions.list(plan_id):
                decision_id = decision["decision_id"]
                entities.append(
                    {
                        **self._entity(
                            decision_id,
                            "ApprovalDecision",
                            f"{decision['decision']} decision for {plan_id}",
                        ),
                        "lifecycle_status": str(decision["decision"]),
                    }
                )
                relationships.append(
                    self._relationship(plan_id, "hasApprovalDecision", decision_id)
                )
        return {
            "entities": list(
                {row["entity_id"]: row for row in entities}.values()
            ),
            "relationships": relationships,
            "pending_relationships": pending_relationships,
            "read_only": True,
        }

    def _defender_relationships_for_plan(
        self,
        plan: dict[str, Any],
        *,
        pending_relationships: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        plan_id = str(plan.get("plan_id") or "")
        resource_id = str(
            plan.get("resource", {}).get("id")
            or plan.get("resource", {}).get("resource_id")
            or plan.get("resource_key")
            or next(
                (
                    resource.get("resource_key")
                    for resource in plan.get("dependencies", {}).get("resources", [])
                    if resource.get("resource_key")
                ),
                "",
            )
            or next(
                (
                    citation.get("resource_id")
                    for citation in plan.get("evidence_citations") or []
                    if citation.get("resource_id")
                ),
                "",
            )
            or ""
        ).strip().casefold()
        if not plan_id:
            return []
        relationships: list[dict[str, Any]] = []
        for citation in plan.get("evidence_citations") or []:
            predicate_meta = self._predicate_for_citation(citation)
            if predicate_meta is None:
                continue
            predicate, object_type = predicate_meta
            object_id = str(citation.get("source_id") or "").strip()
            if not object_id or not resource_id:
                pending_relationships.append(
                    {
                        "plan_id": plan_id,
                        "predicate": predicate,
                        "object_type": object_type,
                        "citation": copy.deepcopy(citation),
                        "reason": "missing canonical resource id" if not resource_id else "missing citation source id",
                    }
                )
                continue
            relationships.append(
                self._relationship(
                    plan_id,
                    predicate,
                    object_id,
                    object_type=object_type,
                    payload={
                        "resource_id": resource_id,
                        "source_type": str(citation.get("source_type") or ""),
                        "source_id": object_id,
                    },
                    source="remediation-plan-citation",
                    confidence=compute_confidence("inventory", corroborated=False),
                )
            )
        return relationships

    @staticmethod
    def _predicate_for_citation(citation: dict[str, Any]) -> tuple[str, str] | None:
        source_type = str(citation.get("source_type") or "").strip().casefold()
        return {
            "assessment": ("addressesFinding", "DefenderAssessment"),
            "alert": ("addressesAlert", "SecurityAlert"),
            "attack_path": ("breaksAttackPath", "AttackPath"),
            "secure_score_control": ("improvesControl", "SecureScoreControl"),
        }.get(source_type)

    @staticmethod
    def _entity(identity: str, entity_type: str, name: str) -> dict[str, str]:
        return {
            "entity_id": identity,
            "entity_type": entity_type,
            "name": str(name)[:1024],
            "lifecycle_status": "draft",
        }

    @staticmethod
    def _relationship(
        subject: str,
        relationship_type: str,
        object_id: str,
        *,
        object_type: str = "",
        payload: dict[str, Any] | None = None,
        source: str = "remediation-plan",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        identity = hashlib.sha256(
            f"{subject}|{relationship_type}|{object_id}".encode()
        ).hexdigest()[:24]
        row = {
            "relationship_id": f"remediation-rel:{identity}",
            "subject_id": subject,
            "relationship_type": relationship_type,
            "object_id": object_id,
            "lifecycle_status": "draft",
            "confidence": confidence,
            "source": source,
        }
        if object_type:
            row["object_type"] = object_type
        if payload is not None:
            row["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return row

    @staticmethod
    def _safe_key(value: Any) -> str:
        text = re.sub(r"[^a-z0-9]+", "-", str(value or "unknown").casefold()).strip("-")
        return text[:128] or "unknown"
