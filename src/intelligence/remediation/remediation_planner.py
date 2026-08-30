from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from opentelemetry import metrics

from intelligence.incident.incident_intelligence import IncidentIntelligence
from intelligence.predictive.predictive_context_builder import PredictiveContextBuilder

from .approval_engine import ApprovalEngine
from .dependency_analyzer import DependencyAnalyzer
from .execution_simulator import ExecutionSimulator
from .impact_estimator import ImpactEstimator
from .plan_prioritizer import PlanPrioritizer
from .plan_repository import PlanRepository
from .remediation_generator import RemediationGenerator
from .remediation_opportunity_engine import RemediationOpportunityEngine
from .risk_analyzer import RiskAnalyzer
from .rollback_planner import RollbackPlanner


class RemediationTelemetry:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("aiops.remediation_planning", "0.1.0")
        self.plan_generation_latency = meter.create_histogram(
            "remediation.plan.generation.latency", unit="s"
        )
        self.simulation_duration = meter.create_histogram(
            "remediation.simulation.duration", unit="s"
        )
        self.dependency_traversal_latency = meter.create_histogram(
            "remediation.dependency.traversal.latency", unit="s"
        )
        self.risk_analysis_duration = meter.create_histogram(
            "remediation.risk.analysis.duration", unit="s"
        )
        self.approval_generation_time = meter.create_histogram(
            "remediation.approval.generation.time", unit="s"
        )
        self.rollback_generation_time = meter.create_histogram(
            "remediation.rollback.generation.time", unit="s"
        )


class RemediationPlanner:
    REPORT_TYPES: ClassVar[dict[str, str]] = {
        "modernization roadmap": "Lifecycle and modernization debt",
        "patch remediation plan": "Patch and vulnerability debt",
        "compliance recovery plan": "Configuration and policy debt",
        "high-risk service remediation plan": "high-risk",
        "technology debt reduction plan": "all",
        "executive risk reduction strategy": "all",
    }
    QUERY_NAMES: ClassVar[set[str]] = {
        "show high priority plans",
        "simulate remediation",
        "show risk reduction",
        "show required approvals",
        "show rollback plan",
        "should this plan be recommended",
    }

    def __init__(
        self,
        *,
        resources: list[dict[str, Any]],
        action_catalog: list[dict[str, Any]],
        approval_policies: list[dict[str, Any]],
        freshness: str,
        max_resources: int = 5000,
        max_plans: int = 1000,
        max_output_items: int = 100,
        max_dependencies: int = 100,
        max_serialized_bytes: int = 1_000_000,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
        telemetry: RemediationTelemetry | None = None,
    ) -> None:
        for name, value in (
            ("max_resources", max_resources),
            ("max_plans", max_plans),
            ("max_output_items", max_output_items),
            ("max_dependencies", max_dependencies),
            ("max_serialized_bytes", max_serialized_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if min(max_resources, max_plans, max_output_items, max_dependencies) < 1:
            raise ValueError("Remediation planning bounds must be positive")
        if max_serialized_bytes < 1024:
            raise ValueError("Remediation serialized bound must be at least 1024")
        if len(resources) > max_resources:
            raise ValueError("Remediation resources exceed configured bound")
        self.now = now
        self.clock = clock
        self.telemetry = telemetry or RemediationTelemetry()
        self.max_output_items = max_output_items
        self.max_serialized_bytes = max_serialized_bytes
        self.freshness = self._timestamp(freshness)
        if datetime.fromisoformat(self.freshness) > self._now():
            raise ValueError("Remediation freshness cannot be in the future")
        self.resources = self._resources(resources)
        self.opportunities = RemediationOpportunityEngine(action_catalog)
        self.repository = PlanRepository(max_plans=max_plans)
        approval_engine = ApprovalEngine(approval_policies)
        self.generator = RemediationGenerator(
            dependency_analyzer=DependencyAnalyzer(
                max_dependencies=max_dependencies
            ),
            risk_analyzer=RiskAnalyzer(),
            approval_engine=approval_engine,
            rollback_planner=RollbackPlanner(),
            simulator=ExecutionSimulator(),
            impact_estimator=ImpactEstimator(),
            prioritizer=PlanPrioritizer(),
            telemetry=self.telemetry,
            clock=self.clock,
        )

    @classmethod
    def from_snapshot(cls, **snapshot):
        return cls(**snapshot)

    @classmethod
    def from_semantic_engine(
        cls,
        semantic_engine,
        *,
        inventory,
        resource_signals,
        action_catalog,
        approval_policies,
        **kwargs,
    ):
        resources = []
        for row in inventory:
            key = PredictiveContextBuilder.canonical_key(row.get("resource_id"))
            if not key:
                continue
            entity_type = str(row.get("entity_type") or "Resource")
            try:
                context = semantic_engine.get_resource_context(
                    key, subject_type=entity_type
                )
                public = semantic_engine.indexes.public(key)
            except LookupError:
                continue
            sections = context.get("sections") or {}
            classification = sections.get("operational_classification") or {}
            resources.append(
                {
                    "resource_key": key,
                    "name": str(row.get("name") or "Unknown"),
                    "entity_type": entity_type,
                    "application": cls._first_name(sections.get("applications")),
                    "business_service": cls._first_name(
                        sections.get("business_services")
                    ),
                    "owner": cls._first_name(sections.get("ownership")),
                    "service_owner": cls._first_name(
                        sections.get("service_ownership")
                    ),
                    "support_team": cls._first_name(
                        sections.get("support_teams")
                    ),
                    "environment": str(
                        classification.get("environment") or "Unknown"
                    ),
                    "business_criticality": str(
                        classification.get("criticality") or "Unknown"
                    ),
                    "subscription_id": str(
                        public.get("subscription_id")
                        or row.get("subscription_id")
                        or ""
                    ),
                    "subscription_connection": str(
                        public.get("subscription_connection")
                        or row.get("subscription_connection")
                        or row.get("connection_id")
                        or ""
                    ),
                    "upstream_dependencies": cls._section_names(
                        sections.get("upstream_dependencies")
                    ),
                    "downstream_dependencies": cls._section_names(
                        sections.get("downstream_dependents")
                    ),
                    **dict(resource_signals.get(key) or {}),
                }
            )
        return cls(
            resources=resources,
            action_catalog=action_catalog,
            approval_policies=approval_policies,
            freshness=str(semantic_engine.freshness),
            **kwargs,
        )

    def identify_opportunities(self) -> dict[str, Any]:
        rows = self.opportunities.identify(self.resources)
        public = [self._public_opportunity(row) for row in rows]
        return self._bounded(
            {
                "opportunities": public[: self.max_output_items],
                "collection_metadata": {
                    "opportunities": self._metadata(public)
                },
                "freshness": self.freshness,
                "read_only": True,
                "execution_performed": False,
            }
        )

    def generate_plans(self) -> dict[str, Any]:
        started = self.clock()
        opportunities = self.opportunities.identify(self.resources)
        plans = [self.generator.generate(row) for row in opportunities]
        plans.sort(
            key=lambda row: (
                -row["priority_score"],
                -row["simulation_result"]["risk_reduction_percent"],
                row["resource"]["name"],
                row["plan_id"],
            )
        )
        self.repository.replace_generation(plans)
        self.telemetry.plan_generation_latency.record(self.clock() - started)
        return self._bounded(
            {
                "plans": plans[: self.max_output_items],
                "collection_metadata": {"plans": self._metadata(plans)},
                "summary": self._summary(plans),
                "freshness": self.freshness,
                "approval_required": True,
                "execution_performed": False,
                "read_only": True,
            }
        )

    def query(self, question: str) -> dict[str, Any]:
        normalized = " ".join(question.strip().rstrip(".?!").casefold().split())
        if normalized not in self.QUERY_NAMES:
            raise ValueError("Unsupported remediation planning query")
        plans = self._all_plans()
        if normalized == "show high priority plans":
            candidates = [p for p in plans if p["priority"] in {"Priority 1", "Priority 2"}]
        elif normalized == "simulate remediation":
            candidates = [
                {"plan_id": p["plan_id"], "resource": p["resource"], "simulation_result": p["simulation_result"]}
                for p in plans
            ]
        elif normalized == "show risk reduction":
            candidates = [
                {"plan_id": p["plan_id"], "resource": p["resource"], "risk_reduction_percent": p["simulation_result"]["risk_reduction_percent"], "operational_debt_reduction_percent": p["simulation_result"]["operational_debt_reduction_percent"]}
                for p in plans
            ]
        elif normalized == "show required approvals":
            candidates = [
                {"plan_id": p["plan_id"], "resource": p["resource"], "approval_requirements": p["approval_requirements"]}
                for p in plans
            ]
        elif normalized == "show rollback plan":
            candidates = [
                {"plan_id": p["plan_id"], "resource": p["resource"], "rollback_plan": p["rollback_plan"]}
                for p in plans
            ]
        else:
            candidates = [
                {
                    "plan_id": p["plan_id"],
                    "resource": p["resource"],
                    "recommended": p["priority"] in {"Priority 1", "Priority 2"}
                    and p["rollback_plan"]["reversible"]
                    and bool(p["approval_requirements"]),
                    "rationale": "Recommendation means approval-ready prioritization only; it does not authorize or execute the plan.",
                    "approval_required": True,
                }
                for p in plans
            ]
        return self._bounded(
            {
                "query": normalized,
                "result": candidates[: self.max_output_items],
                "collection_metadata": {"result": self._metadata(candidates)},
                "freshness": self.freshness,
                "execution_performed": False,
                "read_only": True,
            }
        )

    def report(self, report_type: str) -> dict[str, Any]:
        normalized = " ".join(report_type.strip().casefold().split())
        if normalized not in self.REPORT_TYPES:
            raise ValueError("Unsupported remediation planning report")
        plans = self._all_plans()
        focus = self.REPORT_TYPES[normalized]
        if focus == "high-risk":
            candidates = [p for p in plans if p["priority"] in {"Priority 1", "Priority 2"}]
        elif focus == "all":
            candidates = plans
        else:
            candidates = [p for p in plans if p["opportunity_type"] == focus]
        total_reduction = sum(
            p["simulation_result"]["risk_reduction_percent"] for p in candidates
        )
        return self._bounded(
            {
                "report_type": normalized.replace(" ", "_"),
                "headline": f"{len(candidates)} approval-ready draft plans with {round(total_reduction / len(candidates)) if candidates else 0}% average simulated risk reduction.",
                "plans": candidates[: self.max_output_items],
                "collection_metadata": {"plans": self._metadata(candidates)},
                "portfolio_summary": self._summary(candidates),
                "freshness": self.freshness,
                "approval_required": True,
                "execution_performed": False,
                "read_only": True,
            }
        )

    def _all_plans(self) -> list[dict[str, Any]]:
        if not self.repository.list():
            self.generate_plans()
        return self.repository.list()

    def _resources(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        identities: set[str] = set()
        result = []
        for source in rows:
            row = dict(source)
            key = PredictiveContextBuilder.canonical_key(row.get("resource_key"))
            if not key or key in identities:
                raise ValueError("Remediation resources require unique canonical identity")
            identities.add(key)
            row["resource_key"] = key
            result.append(row)
        return result

    @staticmethod
    def _public_opportunity(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if not key.startswith("_")}

    @staticmethod
    def _first_name(value: Any) -> str:
        names = RemediationPlanner._section_names(value)
        return names[0] if names else "Unknown"

    @staticmethod
    def _section_names(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            str(item.get("name") if isinstance(item, dict) else item)[:512]
            for item in value[:100]
            if str(item.get("name") if isinstance(item, dict) else item).strip()
        ]

    def _metadata(self, values: list[Any]) -> dict[str, Any]:
        returned = min(len(values), self.max_output_items)
        return {
            "count": len(values),
            "returned": returned,
            "truncated": returned < len(values),
        }

    @staticmethod
    def _summary(plans: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "plan_count": len(plans),
            "priority_1_count": sum(p["priority"] == "Priority 1" for p in plans),
            "approval_requirement_count": sum(
                len(p["approval_requirements"]) for p in plans
            ),
            "average_risk_reduction_percent": round(
                sum(p["simulation_result"]["risk_reduction_percent"] for p in plans)
                / len(plans)
            )
            if plans
            else 0,
        }

    def _bounded(self, value: dict[str, Any]) -> dict[str, Any]:
        sanitized = IncidentIntelligence._sanitize_public(value)
        size = len(
            json.dumps(sanitized, sort_keys=True, separators=(",", ":")).encode()
        )
        if size > self.max_serialized_bytes:
            raise ValueError("Remediation planning output exceeds configured bound")
        return sanitized

    def _now(self) -> datetime:
        value = self.now()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _timestamp(value: Any) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Remediation freshness must be ISO timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
