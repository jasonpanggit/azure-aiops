from __future__ import annotations


class ImpactEstimator:
    """Summarizes business impact from risk and business-context evidence.

    The score weighs the business context the dependency analyzer already
    produced -- how many applications and services are affected, and how
    many owners and support teams stand behind them -- rather than raw
    dependency counts alone, so a resource with no known business mapping
    does not read as low-impact merely because it has few graph edges.
    """

    def estimate(self, risk, dependencies, simulation):
        owner_count = len(
            {
                *(dependencies.get("owners") or ()),
                *(dependencies.get("service_owners") or ()),
            }
        )
        business_context_score = min(
            len(dependencies.get("affected_applications") or ()) * 8
            + len(dependencies.get("affected_services") or ()) * 8
            + owner_count * 4
            + min(int(dependencies.get("dependency_count") or 0) * 5, 20),
            40,
        )
        score = min(
            (risk["business_risk"]["score"] or 0) * 3 // 10
            + (risk["service_impact_risk"]["score"] or 0) * 3 // 10
            + business_context_score,
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
