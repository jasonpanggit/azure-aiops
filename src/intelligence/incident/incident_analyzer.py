from __future__ import annotations

from typing import Any

from .causality_engine import CausalityEngine
from .incident_context_builder import IncidentContextBuilder
from .incident_correlator import IncidentCorrelator


class IncidentAnalyzer:
    def __init__(
        self,
        context_builder: IncidentContextBuilder,
        *,
        correlator: IncidentCorrelator | None = None,
        causality: CausalityEngine | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.correlator = correlator or IncidentCorrelator()
        self.causality = causality or CausalityEngine()

    def analyze(self, incidents: list[dict[str, Any]], evidence: list[dict[str, Any]], *, now) -> list[dict[str, Any]]:
        findings = []
        for incident in incidents:
            context = self.context_builder.get(str(incident.get("resource_key") or ""))
            correlated = self.correlator.correlate(incident, evidence)
            causes = [self.causality.score(incident, row, now=now) for row in correlated]
            causes = sorted(causes, key=lambda row: (-row["causal_score"], row["evidence_type"], row["evidence_id"]))
            probable = [
                row for row in causes if row["classification"] == "Probable cause"
            ]
            contributing = [
                row for row in causes if row["classification"] == "Contributing factor"
            ]
            impacted_apps = context["impacted_applications"]
            impacted_services = context["impacted_services"]
            impacted_business = context["impacted_business_services"]
            public_context = {key: value for key, value in context.items() if not key.startswith("_")}
            findings.append(
                {
                    "incident": {
                        "incident_id": str(incident.get("incident_id") or "Unknown"),
                        "title": str(incident.get("title") or "Unknown"),
                        "status": str(incident.get("status") or "Unknown"),
                        "severity": str(incident.get("severity") or "Unknown"),
                        "started_at": str(incident.get("started_at") or ""),
                    },
                    **public_context,
                    "probable_causes": probable,
                    "contributing_factors": contributing,
                    "correlated_evidence_count": len(correlated),
                    "impacted_applications": impacted_apps,
                    "impacted_services": impacted_services,
                    "impacted_business_services": impacted_business,
                    "blast_radius": {
                        "application_count": len(impacted_apps),
                        "service_count": len(impacted_services),
                        "business_service_count": len(impacted_business),
                    },
                    "recommended_action": {
                        "priority": "Priority 1" if str(incident.get("severity") or "").casefold() == "critical" else "Priority 2",
                        "impact": str(context.get("business_criticality") or "Unknown"),
                        "confidence": probable[0]["confidence"] if probable else 0.0,
                        "rationale": probable[0]["evidence"] if probable else ["No probable cause reached the configured threshold."],
                        "suggested_action": "Validate the ranked evidence, dependency path, and responsible owner before deciding on any operational change.",
                        "advisory_only": True,
                    },
                    "read_only": True,
                }
            )
        return sorted(findings, key=lambda row: (row["incident"]["started_at"], row["incident"]["incident_id"]), reverse=True)
