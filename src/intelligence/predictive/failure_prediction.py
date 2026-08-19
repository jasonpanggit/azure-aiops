from __future__ import annotations

from .incident_probability_engine import IncidentProbabilityEngine


class FailurePredictionEngine:
    """Builds explainable resource failure-risk projections."""

    def __init__(self, probability_engine=None):
        self.probability = probability_engine or IncidentProbabilityEngine()

    def predict(self, context, trend, forecast, confidence):
        likelihood = self.probability.estimate(context, trend)
        risk_score = int(forecast["score"])
        evidence = likelihood["evidence"] or [
            "No non-zero governed failure contributor was observed"
            if likelihood["evidence_status"] != "Unknown"
            else "Insufficient governed evidence for a failure contributor estimate"
        ]
        consequences = []
        if context.get("application") not in {None, "", "Unknown"}:
            consequences.append(f"Application instability: {context['application']}")
        if context.get("business_service") not in {None, "", "Unknown"}:
            consequences.append(f"Business service disruption: {context['business_service']}")
        if int(context.get("incident_count_90d") or 0):
            consequences.append("Recurring incident demand and service-level degradation")
        return {
            "risk_score": risk_score,
            "risk_level": forecast["level"],
            **likelihood,
            "confidence": confidence,
            "evidence": evidence,
            "reasoning_chain": [
                "Observed incidents and governed posture are converted to named contributors",
                "Observed trend adjusts the future scenario without claiming causality",
                "Business relationships identify potential application and service impact",
            ],
            "potential_consequences": consequences or ["Operational degradation if the observed pattern continues"],
            "preventive_action": {
                "suggested_action": "Review the named evidence and preventive maintenance options through approved operational processes."
                if likelihood["evidence_status"] != "Unknown"
                else "Improve governed incident and posture evidence before prioritizing preventive work.",
                "predicted_outcome": "Reduced exposure if the contributing posture is addressed"
                if likelihood["evidence_status"] != "Unknown"
                else "Improved prediction evidence completeness",
                "risk_reduction_estimate_percent": min(risk_score, 75)
                if likelihood["evidence_status"] != "Unknown"
                else None,
                "advisory_only": True,
            },
        }
