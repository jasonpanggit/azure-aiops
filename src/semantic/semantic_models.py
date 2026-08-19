from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class SemanticEntity:
    entity_type: str
    name: str
    lifecycle_status: str = "active"

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.entity_type, self.name)
        ):
            raise ValueError("Semantic entity type and name are required")
        if not isinstance(self.lifecycle_status, str):
            raise TypeError("Semantic lifecycle_status must be a string")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DomainKnowledge:
    subject: SemanticEntity
    facts: dict[str, Any]

    section_names: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def build(
        cls, subject: SemanticEntity, sections: dict[str, Any]
    ) -> DomainKnowledge:
        return cls(
            subject,
            {
                name: sections[name]
                for name in cls.section_names
                if name in sections
            },
        )


class ApplicationKnowledge(DomainKnowledge):
    section_names = (
        "infrastructure",
        "ownership",
        "support_teams",
        "business_services",
        "services",
        "upstream_dependencies",
        "downstream_dependents",
        "compliance",
        "patch_status",
        "advisor_findings",
        "security_findings",
        "resource_health",
        "lifecycle",
        "cost_context",
    )


class ServiceKnowledge(DomainKnowledge):
    section_names = (
        "applications",
        "infrastructure",
        "dependencies",
        "risk_summary",
        "cost_context",
    )


class InfrastructureKnowledge(DomainKnowledge):
    section_names = (
        "applications",
        "business_services",
        "ownership",
        "support_teams",
        "compliance",
        "patching",
        "advisor_findings",
        "security_findings",
        "cost_context",
        "resource_health",
        "operational_classification",
        "lifecycle",
        "resource_count",
        "resources",
        "health",
        "cost",
    )


class ComplianceKnowledge(DomainKnowledge):
    section_names = ("compliance",)


class PatchingKnowledge(DomainKnowledge):
    section_names = ("patching", "patch_status")


class OwnershipKnowledge(DomainKnowledge):
    section_names = ("ownership", "support_teams")


class BusinessImpactKnowledge(DomainKnowledge):
    section_names = ("business_services", "applications", "services")


class ResourceHealthKnowledge(DomainKnowledge):
    section_names = ("resource_health", "health")


class OperationalRiskKnowledge(DomainKnowledge):
    section_names = ("risk_summary",)


class DependenciesKnowledge(DomainKnowledge):
    section_names = (
        "upstream_dependencies",
        "downstream_dependents",
        "dependencies",
    )


class LifecycleKnowledge(DomainKnowledge):
    section_names = ("lifecycle",)


class CostKnowledge(DomainKnowledge):
    section_names = ("cost", "cost_context")


class SecurityKnowledge(DomainKnowledge):
    section_names = ("security_findings",)


@dataclass(frozen=True)
class SemanticContext:
    context_type: str
    subject: SemanticEntity
    sections: dict[str, Any]
    freshness: str
    knowledge_version: str
    risk: RiskAssessment | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "context_type": self.context_type,
            "subject": self.subject.to_dict(),
            "sections": self.sections,
            "freshness": self.freshness,
            "knowledge_version": self.knowledge_version,
        }
        if self.risk is not None:
            payload["risk"] = self.risk.to_dict()
        return payload


@dataclass(frozen=True)
class RiskInputs:
    missing_owner: bool = False
    patch_compliant: bool | None = None
    advisor_recommendation_count: int = 0
    security_finding_count: int = 0
    criticality: str = ""
    environment: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.missing_owner, bool):
            raise TypeError("Semantic missing_owner must be boolean")
        if self.patch_compliant is not None and not isinstance(
            self.patch_compliant, bool
        ):
            raise TypeError("Semantic patch_compliant must be boolean or None")
        for field_name in (
            "advisor_recommendation_count",
            "security_finding_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Semantic {field_name} must be a non-negative integer")
        if not isinstance(self.criticality, str) or not isinstance(
            self.environment, str
        ):
            raise TypeError("Semantic risk classifications must be strings")


@dataclass(frozen=True)
class RiskAssessment:
    score: int | None
    level: str
    factors: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, int)
            or not 0 <= self.score <= 100
        ):
            raise ValueError("Semantic risk score must be an integer from 0 to 100")
        if self.level not in {"Unknown", "Low", "Moderate", "High", "Critical"}:
            raise ValueError("Semantic risk level is invalid")
        if (self.score is None) != (self.level == "Unknown"):
            raise ValueError(
                "Semantic Unknown risk requires no score and scored risk requires a level"
            )
        if not isinstance(self.factors, dict) or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in self.factors.items()
        ):
            raise TypeError("Semantic risk factors must be non-negative integer mappings")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RiskScorer:
    def score(self, inputs: RiskInputs) -> RiskAssessment:
        criticality = {
            "critical": 10,
            "high": 8,
            "medium": 5,
            "low": 2,
        }.get(inputs.criticality.casefold(), 0)
        environment = (
            5
            if inputs.environment.casefold() in {"production", "prod", "live"}
            else 0
        )
        factors = {
            "missing_owner": 25 if inputs.missing_owner else 0,
            "patch_noncompliance": 25 if inputs.patch_compliant is False else 0,
            "advisor_recommendations": min(
                max(inputs.advisor_recommendation_count, 0) * 15, 15
            ),
            "security_findings": min(max(inputs.security_finding_count, 0) * 20, 20),
            "resource_criticality": criticality,
            "environment_classification": environment,
        }
        score = min(max(sum(factors.values()), 0), 100)
        return RiskAssessment(score, self.level_for(score), factors)

    @staticmethod
    def level_for(score: int) -> str:
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError("Semantic risk score must be an integer from 0 to 100")
        if score >= 75:
            return "Critical"
        if score >= 50:
            return "High"
        if score >= 25:
            return "Moderate"
        return "Low"
