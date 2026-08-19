from __future__ import annotations

from typing import Any


class ExecutionSimulator:
    """Produces declarative before/after estimates without touching infrastructure."""

    def simulate(
        self,
        resource: dict[str, Any],
        action: dict[str, Any],
        risk: dict[str, Any],
    ) -> dict[str, Any]:
        effectiveness = action.get("effectiveness") or {}
        values = {
            name: self._percent(effectiveness.get(name))
            for name in (
                "risk_reduction_percent",
                "compliance_improvement_percent",
                "lifecycle_exposure_reduction_percent",
                "operational_debt_reduction_percent",
            )
        }
        service_score = risk["service_impact_risk"]["score"]
        business_impact = "Unknown" if service_score is None else "Critical" if service_score >= 75 else "High" if service_score >= 50 else "Moderate" if service_score >= 25 else "Low"
        return {
            **values,
            "current_operational_debt_score": min(int(resource.get("operational_debt_score") or 0), 100),
            "estimated_residual_operational_debt_score": max(
                round(
                    int(resource.get("operational_debt_score") or 0)
                    * (100 - values["operational_debt_reduction_percent"])
                    / 100
                ),
                0,
            ),
            "business_impact": business_impact,
            "assumptions": [
                "All approvals and preconditions are satisfied",
                "The action follows the governed catalog steps",
                "Simulation estimates are not guaranteed outcomes",
            ],
            "simulation_only": True,
            "changes_executed": False,
        }

    @staticmethod
    def _percent(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("Remediation effectiveness values must be integer percentages")
        return value
