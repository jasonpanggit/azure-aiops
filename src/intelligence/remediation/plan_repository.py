from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from intelligence.lifecycle.lifecycle_context_builder import canonical_resource_key
from ontology.confidence import compute_confidence
from storage.onelake_documents import DocumentConflictError

from .approval_decisions import RemediationDecisionStore, RevisionedDocumentStore


class PlanRepository:
    """Store generated draft plans and expose their read-only ontology projection."""

    _SCHEMA_VERSION = "1.0.0"

    def __init__(
        self,
        *,
        max_plans: int = 1000,
        decision_store: RemediationDecisionStore | None = None,
        decision_document_store: RevisionedDocumentStore | None = None,
        plan_document_store: RevisionedDocumentStore | None = None,
        plan_document_name: str = "state/remediation_plans.json",
    ) -> None:
        if isinstance(max_plans, bool) or not isinstance(max_plans, int):
            raise TypeError("max_plans must be an integer")
        if max_plans < 1:
            raise ValueError("max_plans must be positive")
        if decision_store is not None and decision_document_store is not None:
            raise ValueError("Use either decision_store or decision_document_store, not both")
        self.max_plans = max_plans
        self._plans: tuple[dict[str, Any], ...] = ()
        # WR-01: 03.2-02 makes one PlanRepository instance shared across
        # concurrently in-flight requests for up to 30s (the hybrid_remediation
        # TTL cache). All remediation router handlers are plain ``def`` routes,
        # which Starlette dispatches to its worker thread pool, so two
        # concurrent requests can call generate_plans() -> replace_generation()
        # on the *same* repository object from two OS threads at once. Use the
        # same threading.RLock() pattern RemediationExecutionStore already uses
        # around every read/write so a slower request's write can never
        # interleave with -- or silently lose to -- a faster one's.
        self._lock = threading.RLock()
        self._plan_document_store = plan_document_store
        self._plan_document_name = plan_document_name
        self.decisions = decision_store or RemediationDecisionStore(
            document_store=decision_document_store
        )

    def replace_generation(self, plans: list[dict[str, Any]]) -> None:
        if len(plans) > self.max_plans:
            raise ValueError("Generated remediation plans exceed repository bound")
        identities = [str(plan.get("plan_id") or "") for plan in plans]
        if any(not identity for identity in identities) or len(identities) != len(set(identities)):
            raise ValueError("Remediation repository requires unique plan_id")
        materialized = tuple(copy.deepcopy(plans))
        with self._lock:
            if self._plan_document_store is not None:
                for _ in range(3):
                    state = self._read_plan_state()
                    next_revision = state["revision"] + 1
                    payload = {
                        "schema_version": self._SCHEMA_VERSION,
                        "revision": next_revision,
                        "plans": list(materialized),
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                    try:
                        self._plan_document_store.write(
                            self._plan_document_name,
                            payload,
                            expected_revision=state["revision"],
                        )
                    except DocumentConflictError:
                        continue
                    self._plans = materialized
                    return
                raise DocumentConflictError(
                    "Remediation plan store changed during update"
                )
            self._plans = materialized

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            plans = self._read_plan_state()["plans"]
        return copy.deepcopy(list(plans))

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            plans = self._read_plan_state()["plans"]
        return next(
            (copy.deepcopy(plan) for plan in plans if plan["plan_id"] == plan_id),
            None,
        )

    def ontology_projection(
        self,
        defender_entities: Iterable[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Project plans against the authoritative typed Defender entity set."""

        entities: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        pending_relationships: list[dict[str, Any]] = []
        defender_index = self._defender_entity_index(defender_entities)
        for plan in self.list():
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
                    self._relationship(
                        plan_id,
                        "RemediationPlan",
                        "requiresApproval",
                        approval_id,
                        "ApprovalRequirement",
                    )
                )
            for step in plan["execution_steps"]:
                step_id = f"{plan_id}:step:{step['step_number']}"
                entities.append(
                    self._entity(step_id, "ExecutionStep", step["description"])
                )
                relationships.append(
                    self._relationship(
                        plan_id,
                        "RemediationPlan",
                        "hasStep",
                        step_id,
                        "ExecutionStep",
                    )
                )
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
                    self._relationship(
                        application_id,
                        "Application",
                        "requiresPlan",
                        plan_id,
                        "RemediationPlan",
                    ),
                    self._relationship(
                        plan_id,
                        "RemediationPlan",
                        "mitigatesRisk",
                        risk_id,
                        "RiskAssessment",
                    ),
                    self._relationship(
                        plan_id,
                        "RemediationPlan",
                        "protectsService",
                        service_id,
                        "BusinessService",
                    ),
                    self._relationship(
                        plan_id,
                        "RemediationPlan",
                        "hasRollbackPlan",
                        rollback_id,
                        "RollbackPlan",
                    ),
                    self._relationship(
                        plan_id,
                        "RemediationPlan",
                        "hasSimulation",
                        simulation_id,
                        "SimulationResult",
                    ),
                ]
            )
            defender_relationships = self._defender_relationships_for_plan(
                plan,
                defender_index=defender_index,
                pending_relationships=pending_relationships,
            )
            relationships.extend(defender_relationships)
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
                    self._relationship(
                        plan_id,
                        "RemediationPlan",
                        "hasApprovalDecision",
                        decision_id,
                        "ApprovalDecision",
                    )
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
        defender_index: dict[str, tuple[Mapping[str, Any], ...]],
        pending_relationships: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        plan_id = str(plan.get("plan_id") or "")
        resource_id = canonical_resource_key(
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
        )
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
                self._record_pending(
                    pending_relationships,
                    plan_id=plan_id,
                    predicate=predicate,
                    object_type=object_type,
                    citation=citation,
                    reason=(
                        "Missing canonical plan resource ID"
                        if not resource_id
                        else "Missing citation source ID"
                    ),
                )
                continue
            citation_resource_id = canonical_resource_key(
                citation.get("resource_id")
            )
            if citation_resource_id and citation_resource_id != resource_id:
                self._record_pending(
                    pending_relationships,
                    plan_id=plan_id,
                    predicate=predicate,
                    object_type=object_type,
                    citation=citation,
                    reason="Citation resource does not match plan resource",
                )
                continue
            candidates = defender_index.get(canonical_resource_key(object_id), ())
            if not candidates:
                self._record_pending(
                    pending_relationships,
                    plan_id=plan_id,
                    predicate=predicate,
                    object_type=object_type,
                    citation=citation,
                    reason="Defender entity not found",
                )
                continue
            entity = next(
                (
                    row
                    for row in candidates
                    if str(row.get("entity_type") or "") == object_type
                ),
                None,
            )
            if entity is None:
                self._record_pending(
                    pending_relationships,
                    plan_id=plan_id,
                    predicate=predicate,
                    object_type=object_type,
                    citation=citation,
                    reason="Defender entity type does not match citation source type",
                )
                continue
            if resource_id not in self._defender_resource_ids(
                entity,
                defender_index=defender_index,
            ):
                self._record_pending(
                    pending_relationships,
                    plan_id=plan_id,
                    predicate=predicate,
                    object_type=object_type,
                    citation=citation,
                    reason="Defender entity is not associated with plan resource",
                )
                continue
            relationships.append(
                self._relationship(
                    plan_id,
                    "RemediationPlan",
                    predicate,
                    str(entity.get("resource_id") or ""),
                    object_type,
                    payload={
                        "resource_id": resource_id,
                        "source_type": str(citation.get("source_type") or ""),
                        "source_id": str(entity.get("resource_id") or ""),
                    },
                    source="remediation-plan-citation",
                    confidence=compute_confidence("inventory", corroborated=False),
                )
            )
        return relationships

    @staticmethod
    def _defender_entity_index(
        entities: Iterable[Mapping[str, Any]],
    ) -> dict[str, tuple[Mapping[str, Any], ...]]:
        mutable: dict[str, list[Mapping[str, Any]]] = {}
        for entity in entities:
            entity_id = canonical_resource_key(entity.get("resource_id"))
            if not entity_id:
                continue
            mutable.setdefault(entity_id, []).append(entity)
        return {
            entity_id: tuple(rows)
            for entity_id, rows in mutable.items()
        }

    @classmethod
    def _defender_resource_ids(
        cls,
        entity: Mapping[str, Any],
        *,
        defender_index: dict[str, tuple[Mapping[str, Any], ...]],
    ) -> set[str]:
        payload = cls._entity_payload(entity)
        entity_type = str(entity.get("entity_type") or "")
        if entity_type == "DefenderAssessment":
            values = [
                payload.get("targetResourceId"),
                payload.get("target_resource_id"),
                entity.get("target_resource_id"),
            ]
        elif entity_type in {"SecurityAlert", "AttackPath"}:
            raw = (
                payload.get("resourceIds")
                or payload.get("resource_ids")
                or entity.get("resource_ids")
                or ()
            )
            values = list(raw) if isinstance(raw, (list, tuple, set)) else [raw]
        elif entity_type == "SecureScoreControl":
            references = (
                payload.get("assessmentDefinitions")
                or payload.get("assessment_definitions")
                or entity.get("assessment_definitions")
                or ()
            )
            references = (
                list(references)
                if isinstance(references, (list, tuple, set))
                else [references]
            )
            values = []
            for reference in references:
                for assessment in defender_index.get(
                    canonical_resource_key(reference),
                    (),
                ):
                    if assessment.get("entity_type") == "DefenderAssessment":
                        values.extend(
                            cls._defender_resource_ids(
                                assessment,
                                defender_index=defender_index,
                            )
                        )
        else:
            values = []
        return {
            canonical
            for value in values
            if (canonical := canonical_resource_key(value))
        }

    @staticmethod
    def _entity_payload(entity: Mapping[str, Any]) -> dict[str, Any]:
        payload = entity.get("payload_json")
        if isinstance(payload, Mapping):
            return dict(payload)
        try:
            parsed = json.loads(str(payload or "{}"))
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}

    @staticmethod
    def _record_pending(
        pending_relationships: list[dict[str, Any]],
        *,
        plan_id: str,
        predicate: str,
        object_type: str,
        citation: Mapping[str, Any],
        reason: str,
    ) -> None:
        pending_relationships.append(
            {
                "plan_id": plan_id,
                "predicate": predicate,
                "object_type": object_type,
                "citation": copy.deepcopy(dict(citation)),
                "reason": reason,
            }
        )

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
        subject_type: str,
        relationship_type: str,
        object_id: str,
        object_type: str,
        *,
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
            "subject_type": subject_type,
            "relationship_type": relationship_type,
            "object_id": object_id,
            "object_type": object_type,
            "lifecycle_status": "draft",
            "confidence": confidence,
            "source": source,
        }
        if payload is not None:
            row["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return row

    def _read_plan_state(self) -> dict[str, Any]:
        if self._plan_document_store is None:
            return {
                "revision": 0,
                "plans": self._plans,
                "updated_at": "",
            }
        payload = self._plan_document_store.read(self._plan_document_name)
        if not payload:
            return {"revision": 0, "plans": (), "updated_at": ""}
        if not isinstance(payload, dict):
            raise TypeError("Remediation plan state must be an object")
        plans = payload.get("plans", [])
        if not isinstance(plans, list) or any(
            not isinstance(item, dict) for item in plans
        ):
            raise TypeError("Remediation plan state plans must be a list of objects")
        if len(plans) > self.max_plans:
            raise ValueError("Stored remediation plans exceed repository bound")
        revision = payload.get("revision", 0)
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
        ):
            raise TypeError("Remediation plan state revision must be non-negative")
        return {
            "revision": revision,
            "plans": tuple(plans),
            "updated_at": str(payload.get("updated_at") or ""),
        }

    @staticmethod
    def _safe_key(value: Any) -> str:
        text = re.sub(r"[^a-z0-9]+", "-", str(value or "unknown").casefold()).strip("-")
        return text[:128] or "unknown"
