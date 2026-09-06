from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .semantic_models import (
    ApplicationKnowledge,
    BusinessImpactKnowledge,
    ComplianceKnowledge,
    CostKnowledge,
    DependenciesKnowledge,
    DomainKnowledge,
    InfrastructureKnowledge,
    LifecycleKnowledge,
    NetworkKnowledge,
    OperationalRiskKnowledge,
    OwnershipKnowledge,
    PatchingKnowledge,
    ResourceHealthKnowledge,
    SecurityKnowledge,
    SemanticEntity,
    ServiceKnowledge,
)

if TYPE_CHECKING:
    from ontology_discovery.generation_resolver import (
        CompatibilityAlias,
        GenerationSelection,
    )


@dataclass(frozen=True)
class SemanticModelDefinition:
    name: str
    description: str
    sources: tuple[str, ...]
    model_type: type
    generation_id: str = ""
    alias_version: str = ""


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
            "Network": "Network topology, enforcement and design-conformance context",
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
            "Network": NetworkKnowledge,
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

    def for_generation(
        self,
        generation: GenerationSelection,
        aliases: Mapping[str, CompatibilityAlias],
    ) -> SemanticRegistry:
        """Return registry definitions pinned to one compatibility alias set."""
        definitions: list[SemanticModelDefinition] = []
        for definition in self._models.values():
            sources: list[str] = []
            for source in definition.sources:
                alias = aliases.get(source)
                if alias is None:
                    sources.append(source)
                    continue
                if (
                    alias.logical_name != source
                    or alias.generation_id != generation.generation_id
                ):
                    raise ValueError(
                        f"Semantic alias for {source!r} is not bound to the selection"
                    )
                sources.append(alias.logical_name)
            definitions.append(
                SemanticModelDefinition(
                    name=definition.name,
                    description=definition.description,
                    sources=tuple(sources),
                    model_type=definition.model_type,
                    generation_id=generation.generation_id,
                    alias_version=generation.compatibility_alias_version,
                )
            )
        return SemanticRegistry(tuple(definitions))

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
