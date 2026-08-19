from __future__ import annotations

from typing import Any, ClassVar


class ChangeRiskEngine:
    SEVERITY: ClassVar[dict[str, int]] = {"critical": 20, "high": 15, "medium": 10, "moderate": 10, "low": 5}

    def calculate(self, *, change: dict[str, Any], context: dict[str, Any], drift: dict[str, Any], deviations: dict[str, int], incident_correlation: dict[str, Any]) -> dict[str, Any]:
        fields = {str(x).casefold() for x in change.get("changed_fields", [])}
        category = str(change.get("category") or "").casefold()
        factors = {
            "change_severity": self.SEVERITY.get(str(change.get("severity") or "").casefold(), 10),

            "sensitive_scope": 15 if category in {"network", "identity", "security"} or fields & {"publicnetworkaccess", "firewall", "roleassignments"} else 0,
            "production_environment": 10 if str(context.get("environment") or "").casefold() in {"production", "prod", "live"} else 0,
            "business_criticality": 15 if str(context.get("business_criticality") or "").casefold() == "critical" else 10 if str(context.get("business_criticality") or "").casefold() == "high" else 0,

            "configuration_drift": 15 if drift.get("drifted") else 0,
            "policy_deviation": 10 if deviations.get("policy") else 0,
            "security_deviation": 10 if deviations.get("security") else 0,
            "incident_proximity": 15 if int(incident_correlation.get("contribution_score") or 0) >= 60 else 0,
        }
        if "application" in context:
            factors["workload_scope"] = 5 if str(context.get("application") or "Unknown").casefold() != "unknown" else 0
        if "dependency_count" in context:
            factors["dependency_count"] = min(int(context.get("dependency_count") or 0) * 3, 15)
        if "historical_correlation_count" in context:
            factors["historical_correlation"] = min(int(context.get("historical_correlation_count") or 0) * 3, 10)
        score = min(sum(factors.values()), 100)
        return {"score": score, "level": self.level(score), "factors": factors, "justification": "; ".join(f"{k.replace('_', ' ')} +{v}" for k, v in factors.items() if v) or "No confirmed change risk factors."}

    @staticmethod
    def level(score: int) -> str:
        return "Critical" if score >= 75 else "High" if score >= 50 else "Moderate" if score >= 25 else "Low"
