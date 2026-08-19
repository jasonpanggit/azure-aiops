from __future__ import annotations


class ImpactEstimator:
    """Summarizes business impact from risk and dependency evidence."""

    def estimate(self, risk, dependencies, simulation):
        score = min(
            (risk["business_risk"]["score"] or 0) * 4 // 10
            + (risk["service_impact_risk"]["score"] or 0) * 4 // 10
            + min(int(dependencies.get("dependency_count") or 0) * 5, 20),
            100,
        )
        level = "Critical" if score >= 75 else "High" if score >= 50 else "Moderate" if score >= 25 else "Low"
        return {
            "score": score,
            "level": level,
            "affected_application_count": len(dependencies["affected_applications"]),
            "affected_service_count": len(dependencies["affected_services"]),
            "dependency_count": dependencies["dependency_count"],
            "expected_risk_reduction_percent": simulation["risk_reduction_percent"],
        }
