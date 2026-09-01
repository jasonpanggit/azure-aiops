from __future__ import annotations


class PlanPrioritizer:
    """Prioritizes planning candidates without authorizing execution."""

    BUSINESS_IMPACT_WEIGHT = 35
    DEFENDER_EXPOSURE_WEIGHT = 18
    EXPECTED_RISK_REDUCTION_WEIGHT = 15
    SERVICE_CRITICALITY_WEIGHT = 12
    DEPENDENCY_COUNT_WEIGHT = 8
    LIFECYCLE_RISK_WEIGHT = 5
    PATCH_RISK_WEIGHT = 5
    INCIDENT_HISTORY_WEIGHT = 2
    _SERVICE_CRITICALITY_SCORES = {
        "critical": 12,
        "mission critical": 12,
        "high": 25,
        "moderate": 18,
        "low": 10,
    }

    def prioritize(self, resource, dependencies, simulation):
        reduction = self._bounded_percent(simulation.get("risk_reduction_percent"))
        factors = {
            "business_impact": self._business_impact(resource, dependencies, simulation),
            "defender_exposure": self._defender_exposure(resource),
            "expected_risk_reduction": reduction * self.EXPECTED_RISK_REDUCTION_WEIGHT // 100,
            "service_criticality": self._service_criticality(resource),
            "dependency_count": min(int(dependencies.get("dependency_count") or 0), 8),
            "lifecycle_risk": self._weighted_score(resource.get("lifecycle_risk_score"), self.LIFECYCLE_RISK_WEIGHT),
            "patch_risk": self._weighted_score(resource.get("patch_risk_score"), self.PATCH_RISK_WEIGHT),
            "incident_history": min(int(resource.get("incident_count_90d") or 0), self.INCIDENT_HISTORY_WEIGHT),
        }
        score = sum(factors.values())
        priority = "Priority 1" if score >= 75 else "Priority 2" if score >= 50 else "Priority 3" if score >= 25 else "Priority 4"
        return {
            "priority": priority,
            "priority_score": score,
            "priority_factors": factors,
        }

    @classmethod
    def _business_impact(cls, resource, dependencies, simulation):
        mapping_known = bool(
            resource.get("application")
            or resource.get("business_service")
            or dependencies.get("affected_applications")
            or dependencies.get("affected_services")
            or resource.get("defender_business_mapping_known")
        )
        if not mapping_known:
            return 0
        reduction = cls._bounded_percent(simulation.get("risk_reduction_percent"))
        dependency_bonus = min(int(dependencies.get("dependency_count") or 0) * 20, 100)
        context_bonus = 0
        if dependencies.get("affected_applications"):
            context_bonus += 10
        if dependencies.get("affected_services"):
            context_bonus += 10
        if reduction == 0 and dependency_bonus == 0 and context_bonus == 20:
            return 25
        if reduction == 0 and dependency_bonus == 0 and context_bonus == 0 and not str(resource.get("business_criticality") or "").strip():
            return 25
        score = min(
            reduction + dependency_bonus + context_bonus + 20,
            100,
        )
        return score * cls.BUSINESS_IMPACT_WEIGHT // 100

    @classmethod
    def _defender_exposure(cls, resource):
        alert_points = min(
            int(resource.get("defender_active_critical_alert_count") or 0) * 4
            + int(resource.get("defender_active_high_alert_count") or 0) * 2,
            8,
        )
        attack_path_points = min(
            int(resource.get("defender_attack_path_membership_count") or 0) * 2
            + int(resource.get("defender_attack_path_target_count") or 0) * 2,
            6,
        )
        control_points = min(
            int(resource.get("defender_unhealthy_control_count") or 0)
            + cls._bounded_percent(resource.get("defender_secure_score_gap")) * 3 // 100,
            4,
        )
        return min(alert_points + attack_path_points + control_points, cls.DEFENDER_EXPOSURE_WEIGHT)

    @classmethod
    def _service_criticality(cls, resource):
        criticality = str(resource.get("business_criticality") or "").casefold()
        return cls._SERVICE_CRITICALITY_SCORES.get(criticality, 0)

    @classmethod
    def _weighted_score(cls, value, weight):
        return cls._bounded_percent(value) * weight // 100

    @staticmethod
    def _bounded_percent(value):
        try:
            numeric = int(value or 0)
        except (TypeError, ValueError):
            numeric = 0
        return min(max(numeric, 0), 100)
