from __future__ import annotations

from typing import Any


class IncidentAnalyzer:
    def __init__(self, impact_analyzer: Any) -> None:
        self.impact_analyzer = impact_analyzer

    def build(
        self,
        subject: str,
        context: dict[str, Any],
        *,
        subject_type: str = "",
    ) -> dict[str, Any]:
        impact = self.impact_analyzer.analyze(subject, subject_type=subject_type)
        sections = context.get("sections") or {}
        estimate = sections.get("affected_users_estimate")
        if estimate is None:
            affected_users = {
                "value": None,
                "basis": "No governed affected-user estimate is available in semantic evidence.",
            }
        elif not isinstance(estimate, dict):
            raise TypeError("Affected-user estimate must be a mapping")
        else:
            value = estimate.get("value")
            basis = str(estimate.get("basis") or "").strip()
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or not basis
            ):
                raise ValueError(
                    "Affected-user estimate requires a non-negative integer and basis"
                )
            affected_users = {"value": value, "basis": basis}
        return {
            "subject": context.get("subject", {}),
            "impacted_applications": impact["impacted_applications"],
            "impacted_services": impact["impacted_services"],
            "owners": sections.get("ownership", []),
            "support_teams": sections.get("support_teams", []),
            "dependencies": impact["dependency_tree"],
            "business_services": impact["impacted_business_services"],
            "blast_radius": impact["blast_radius"],
            "open_risks": context.get("risk", {}),
            "patch_status": sections.get("compliance") or sections.get("patching") or {},
            "advisor_findings": sections.get("advisor_findings", []),
            "security_findings": sections.get("security_findings", []),
            "affected_users_estimate": affected_users,
            "evidence": impact["evidence"],
            "data_sources": ["Semantic Knowledge Layer", "Fabric Ontology", "OneLake governed facts"],
            "freshness": context.get("freshness", ""),
            "knowledge_version": context.get("knowledge_version", ""),
            "read_only": True,
        }
