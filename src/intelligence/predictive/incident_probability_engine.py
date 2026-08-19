from __future__ import annotations


class IncidentProbabilityEngine:
    """Transparent evidence-weighted incident likelihood estimate."""

    def estimate(self, context, trend):
        known = context.get("_known_signals") or set()
        contributors = {
            "recent_incidents": min(int(context.get("incident_count_90d") or 0) * 7, 35) if "incident_count_90d" in known else None,
            "patch_exposure": min(int(context.get("patch_risk_score") or 0) * 15 // 100, 15) if "patch_risk_score" in known else None,
            "lifecycle_exposure": min(int(context.get("lifecycle_risk_score") or 0) * 10 // 100, 10) if "lifecycle_risk_score" in known else None,
            "configuration_drift": min(int(context.get("configuration_drift_count") or 0) * 4, 15) if "configuration_drift_count" in known else None,
            "change_volatility": min(int(context.get("change_risk_score") or 0) * 10 // 100, 10) if "change_risk_score" in known else None,
            "advisor_exposure": min(int(context.get("advisor_recommendation_count") or 0) * 2, 5) if "advisor_recommendation_count" in known else None,
            "observed_growth": min(max(int(trend.get("growth_index") or 0), 0), 10) if int(trend.get("observation_count") or 0) else None,
        }
        known_values = [value for value in contributors.values() if value is not None]
        estimate = min(sum(known_values), 95) if known_values else None
        return {
            "estimated_probability_percent": estimate,
            "probability_kind": "Evidence-weighted estimate, not a calibrated probability",
            "contributors": contributors,
            "evidence": [
                f"{name.replace('_', ' ')} +{value}"
                for name, value in contributors.items()
                if value is not None and value
            ],
            "evidence_status": "Known" if len(known_values) == len(contributors) else "Partial" if known_values else "Unknown",
        }
