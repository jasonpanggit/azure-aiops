from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticIntent(StrEnum):
    APPLICATION_CONTEXT = "application_context"
    SERVICE_CONTEXT = "service_context"
    RESOURCE_CONTEXT = "resource_context"
    SUBSCRIPTION_CONTEXT = "subscription_context"
    ORPHAN_RESOURCES = "orphan_resources"
    OWNERSHIP_GAPS = "ownership_gaps"
    DEPENDENCY_CHAINS = "dependency_chains"
    DOWNSTREAM_IMPACT = "downstream_impact"
    UPSTREAM_DEPENDENCIES = "upstream_dependencies"
    OPERATIONAL_RISK = "operational_risk"
    IMPACT_CONTEXT = "impact_context"
    NETWORK_CONTEXT = "network_context"
    SEARCH = "search"


@dataclass(frozen=True)
class SemanticQuery:
    intent: SemanticIntent
    subject: str = ""

    @classmethod
    def parse(cls, question: str, *, subject: str = "") -> SemanticQuery:
        normalized = " ".join(question.strip().rstrip(".?!").casefold().split())
        if "orphan" in normalized:
            intent = SemanticIntent.ORPHAN_RESOURCES
        elif "ownership gap" in normalized or "missing ownership" in normalized:
            intent = SemanticIntent.OWNERSHIP_GAPS
        elif (
            normalized.startswith(("find ", "show all "))
            or "services" in normalized
            and "operational risk" in normalized
            or "production" in normalized
            and "failed patch" in normalized
        ):
            intent = SemanticIntent.SEARCH
        elif "blast radius" in normalized or "impacted by" in normalized or "outage" in normalized:
            intent = SemanticIntent.IMPACT_CONTEXT
        elif "what owns" in normalized or "who owns" in normalized:
            intent = SemanticIntent.RESOURCE_CONTEXT
        elif "application context" in normalized:
            intent = SemanticIntent.APPLICATION_CONTEXT
        elif "service context" in normalized:
            intent = SemanticIntent.SERVICE_CONTEXT
        elif (
            "network context" in normalized
            or "vnet context" in normalized
            or "network topology" in normalized
        ):
            intent = SemanticIntent.NETWORK_CONTEXT
        elif "vm context" in normalized or "server context" in normalized or "resource context" in normalized:
            intent = SemanticIntent.RESOURCE_CONTEXT
        elif "subscription context" in normalized:
            intent = SemanticIntent.SUBSCRIPTION_CONTEXT

        elif "dependency chain" in normalized:
            intent = SemanticIntent.DEPENDENCY_CHAINS
        elif "downstream impact" in normalized:
            intent = SemanticIntent.DOWNSTREAM_IMPACT
        elif "upstream" in normalized:
            intent = SemanticIntent.UPSTREAM_DEPENDENCIES
        elif "operational risk" in normalized:
            intent = SemanticIntent.OPERATIONAL_RISK
        else:
            raise ValueError(
                "Supported semantic queries: application/service/resource/subscription/network context; "
                "orphan resources; ownership gaps; dependency chains; downstream impact; "
                "upstream dependencies; operational risk"
            )
        return cls(intent, subject)
