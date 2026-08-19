from __future__ import annotations

from typing import Any


class PatchCorrelator:
    """Correlates patch evidence to application and business graph context."""

    def enrich(
        self,
        *,
        context: dict[str, Any],
        compliance: dict[str, Any],
        risk: dict[str, Any],
        priority: dict[str, Any],
        security_findings: list[dict[str, Any]],
        advisor_recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        severity = str(risk.get("level") or "Low")
        business_impact = self._impact(
            str(context.get("business_criticality") or ""), severity
        )
        resource_name = str((context.get("resource") or {}).get("name") or "Unknown")
        evidence = [
            {
                "source": "PatchAssessmentResources",
                "status": compliance.get("status"),
                "missing_critical_updates": compliance.get("missing_critical_updates"),
                "missing_security_updates": compliance.get("missing_security_updates"),
                "failed_update_count": compliance.get("failed_update_count"),
            }
        ]
        if security_findings:
            evidence.append(
                {
                    "source": "Semantic security findings",
                    "finding_count": len(security_findings),
                    "severities": sorted(
                        {str(item.get("severity") or "Unknown") for item in security_findings}
                    ),
                }
            )
        if advisor_recommendations:
            evidence.append(
                {
                    "source": "Advisor Recommendations",
                    "recommendation_count": len(advisor_recommendations),
                }
            )
        known_fields = sum(
            str(context.get(key) or "Unknown") != "Unknown"
            for key in ("application", "business_service", "owner", "support_team")
        )
        confidence = round(
            min(
                0.4
                + known_fields * 0.075
                + bool(security_findings) * 0.05
                + (0.2 if compliance.get("evidence_coverage") == "Complete" else 0),
                1.0,
            ),
            2,
        )
        public_context = {
            key: value for key, value in context.items() if not key.startswith("_")
        }
        return {
            **public_context,
            **compliance,
            "risk_score": risk["score"],
            "risk_level": risk["level"],
            "risk_factors": risk["factors"],
            "business_impact": business_impact,
            "blast_radius": context["blast_radius"],
            "priority": priority["priority"],
            "evidence": evidence,
            "affected_resources": [resource_name],
            "risk_justification": risk["justification"],
            "priority_reasoning": priority["rationale"],
            "recommended_action": priority["recommended_action"],
            "confidence_score": confidence,
            "advisory_only": True,
        }

    @staticmethod
    def _impact(criticality: str, risk_level: str) -> str:
        rank = {"low": 1, "moderate": 2, "medium": 2, "high": 3, "critical": 4}
        value = max(rank.get(criticality.casefold(), 1), rank.get(risk_level.casefold(), 1))
        return {1: "Low", 2: "Moderate", 3: "High", 4: "Critical"}[value]
