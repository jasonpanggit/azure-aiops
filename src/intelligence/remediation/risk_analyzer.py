from __future__ import annotations

from typing import Any


class RiskAnalyzer:
    """Calculates explainable planning risk; it does not authorize execution."""

    def analyze(
        self,
        resource: dict[str, Any],
        dependencies: dict[str, Any],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        environment = str(resource.get("environment") or "").strip().casefold()
        criticality = str(resource.get("business_criticality") or "").strip().casefold()
        production = environment == "production"
        critical = criticality in {
            "critical",
            "mission critical",
        }
        stage_count = len(action.get("deployment_stages") or [])
        dependency_count = int(dependencies.get("dependency_count") or 0)
        execution = min(
            10 + stage_count * 6 + dependency_count * 5 + (20 if production else 0) + (15 if critical else 0),
            100,
        )
        operational_values = [
            min(max(int(resource[field]), 0), 100)
            for field in (
                "patch_risk_score",
                "lifecycle_risk_score",
                "predictive_risk_score",
                "defender_secure_score_gap",
            )
            if field in resource and resource[field] is not None
        ]
        if "configuration_drift_count" in resource and resource["configuration_drift_count"] is not None:
            operational_values.append(
                min(max(int(resource["configuration_drift_count"]), 0) * 20, 100)
            )
        operational = (
            sum(operational_values) // len(operational_values)
            if operational_values
            else None
        )
        business_levels = {
            "critical": 90,
            "mission critical": 90,
            "high": 70,
            "moderate": 35,
            "low": 10,
        }
        business = business_levels.get(criticality)
        environment_base = (
            60
            if production
            else 20
            if environment
            in {"development", "dev", "test", "uat", "stage", "staging", "non-production"}
            else None
        )
        service = (
            min((environment_base or 0) + dependency_count * 8, 100)
            if environment_base is not None or dependency_count
            else None
        )
        execution_drivers = ["Staged plan complexity"]
        if environment:
            execution_drivers.append(
                "Production scope" if production else "Non-production scope"
            )
        execution_drivers.append(f"{dependency_count} governed dependencies")
        result = {
            "execution_risk": self._dimension(execution, execution_drivers, "Known"),
            "operational_risk": self._dimension(
                operational,
                ["Known operational posture evidence"]
                if operational is not None
                else ["Operational posture evidence unavailable"],
                "Known" if len(operational_values) == 5 else "Partial" if operational_values else "Unknown",
            ),
            "business_risk": self._dimension(
                business,
                [f"Business criticality: {resource.get('business_criticality')}"]
                if business is not None
                else ["Business criticality evidence unavailable"],
                "Known" if business is not None else "Unknown",
            ),
            "service_impact_risk": self._dimension(
                service,
                ["Service environment", f"{dependency_count} upstream/downstream dependencies"]
                if service is not None
                else ["Service environment and dependency evidence unavailable"],
                "Known" if environment_base is not None else "Partial" if dependency_count else "Unknown",
            ),
        }
        known_scores = [
            item["score"] for item in result.values() if item["score"] is not None
        ]
        overall = max(known_scores) if known_scores else None
        result["overall_risk"] = {
            "score": overall,
            "level": self.level(overall),
            "drivers": sorted(
                {driver for item in result.values() for driver in item["drivers"]}
            ),
            "evidence_status": "Known" if known_scores else "Unknown",
        }
        return result

    @classmethod
    def _dimension(cls, score, drivers, evidence_status):
        return {
            "score": score,
            "level": cls.level(score),
            "drivers": drivers,
            "evidence_status": evidence_status,
        }

    @staticmethod
    def level(score: int | None) -> str:
        if score is None:
            return "Unknown"
        return "Critical" if score >= 75 else "High" if score >= 50 else "Moderate" if score >= 25 else "Low"
