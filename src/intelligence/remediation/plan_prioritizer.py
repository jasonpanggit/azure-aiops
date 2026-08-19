from __future__ import annotations


class PlanPrioritizer:
    """Prioritizes planning candidates without authorizing execution."""

    def prioritize(self, resource, dependencies, simulation):
        reduction = int(simulation["risk_reduction_percent"])
        criticality = str(resource.get("business_criticality") or "").casefold()
        criticality_points = 20 if criticality in {"critical", "mission critical"} else 14 if criticality == "high" else 6
        dependency_points = min(int(dependencies.get("dependency_count") or 0) * 5, 15)
        lifecycle_points = min(int(resource.get("lifecycle_risk_score") or 0) * 15 // 100, 15)
        patch_points = min(int(resource.get("patch_risk_score") or 0) * 15 // 100, 15)
        incident_points = min(int(resource.get("incident_count_90d") or 0) * 2, 10)
        score = min(
            reduction * 35 // 100
            + criticality_points
            + dependency_points
            + lifecycle_points
            + patch_points
            + incident_points,
            100,
        )
        priority = "Priority 1" if score >= 75 else "Priority 2" if score >= 50 else "Priority 3" if score >= 25 else "Priority 4"
        return {
            "priority": priority,
            "priority_score": score,
            "priority_factors": {
                "expected_risk_reduction": reduction * 35 // 100,
                "service_criticality": criticality_points,
                "dependency_count": dependency_points,
                "lifecycle_risk": lifecycle_points,
                "patch_risk": patch_points,
                "incident_history": incident_points,
            },
        }
