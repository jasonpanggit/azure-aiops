from __future__ import annotations

from dataclasses import dataclass

from .semantic_models import (
    ApplicationKnowledge,
    BusinessImpactKnowledge,
    ComplianceKnowledge,
    CostKnowledge,
    DependenciesKnowledge,
    DomainKnowledge,
    InfrastructureKnowledge,
    LifecycleKnowledge,
    OperationalRiskKnowledge,
    OwnershipKnowledge,
    PatchingKnowledge,
    ResourceHealthKnowledge,
    SecurityKnowledge,
    SemanticEntity,
    ServiceKnowledge,
)


@dataclass(frozen=True)
class SemanticModelDefinition:
    name: str
    description: str
    sources: tuple[str, ...]
    model_type: type


class SemanticRegistry:
    def __init__(self, models: tuple[SemanticModelDefinition, ...]) -> None:
        self._models = {model.name: model for model in models}
        if len(self._models) != len(models):
            raise ValueError("Semantic model names must be unique")

    @classmethod
    def default(cls) -> SemanticRegistry:
        sources = (
            "ontology_entities",
            "ontology_relationships",
            "inventory",
            "compliance",
        )
        source_overrides = {
            "Patching": (*sources, "patch_assessments"),
            "OperationalRisk": (*sources, "security", "cost"),
            "Cost": ("ontology_entities", "ontology_relationships", "cost"),
            "Security": (
                "ontology_entities",
                "ontology_relationships",
                "security",
            ),
        }
        descriptions = {
            "Application": "Application topology and operational posture",
            "Service": "Service composition and business alignment",
            "Infrastructure": "Azure infrastructure and containment context",
            "Compliance": "Assessment and policy compliance context",
            "Patching": "Patch assessment and failure context",
            "Ownership": "Owner and support accountability",
            "BusinessImpact": "Business-service and application impact",
            "ResourceHealth": "Current resource operational health",
            "OperationalRisk": "Explainable operational risk score",
            "Dependencies": "Upstream and downstream dependency chains",
            "Lifecycle": "Active, retired, and lifecycle context",
            "Cost": "Cost center and business-function context",
            "Security": "Security finding and exposure context",
        }
        model_types = {
            "Application": ApplicationKnowledge,
            "Service": ServiceKnowledge,
            "Infrastructure": InfrastructureKnowledge,
            "Compliance": ComplianceKnowledge,
            "Patching": PatchingKnowledge,
            "Ownership": OwnershipKnowledge,
            "BusinessImpact": BusinessImpactKnowledge,
            "ResourceHealth": ResourceHealthKnowledge,
            "OperationalRisk": OperationalRiskKnowledge,
            "Dependencies": DependenciesKnowledge,
            "Lifecycle": LifecycleKnowledge,
            "Cost": CostKnowledge,
            "Security": SecurityKnowledge,
        }
        return cls(
            tuple(
                SemanticModelDefinition(
                    name,
                    description,
                    source_overrides.get(name, sources),
                    model_types[name],
                )
                for name, description in descriptions.items()
            )
        )

    def names(self) -> tuple[str, ...]:
        return tuple(self._models)

    def get(self, name: str) -> SemanticModelDefinition:
        try:
            return self._models[name]
        except KeyError as exc:
            raise KeyError(f"Unknown semantic model: {name}") from exc

    def build(
        self,
        name: str,
        subject: SemanticEntity,
        sections: dict,
    ) -> DomainKnowledge:
        definition = self.get(name)
        return definition.model_type.build(subject, sections)
