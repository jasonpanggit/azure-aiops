from __future__ import annotations

from typing import Any


class PatchPriorityEngine:
    """Maps business-aware patch risk to a four-tier review queue."""

    def prioritize(
        self,
        *,
        context: dict[str, Any],
        compliance: dict[str, Any],
        risk: dict[str, Any],
    ) -> dict[str, Any]:
        if not all(isinstance(value, dict) for value in (context, compliance, risk)):
            raise TypeError("Patch priority inputs must be mappings")
        score = risk.get("score", 0)
        critical_missing = compliance.get("missing_critical_updates", 0)
        ownership = context.get("ownership_coverage", False)
        if (
            isinstance(score, bool)
            or not isinstance(score, int)
            or not 0 <= score <= 100
        ):
            raise ValueError("Patch priority risk score must be an integer from 0 to 100")
        if (
            isinstance(critical_missing, bool)
            or not isinstance(critical_missing, int)
            or critical_missing < 0
        ):
            raise ValueError("Patch missing critical updates must be a non-negative integer")
        if not isinstance(ownership, bool):
            raise TypeError("Patch ownership_coverage must be boolean")
        critical_business = str(context.get("business_criticality") or "").casefold() == "critical"
        if score >= 75 or (critical_missing and critical_business):
            priority = "Priority 1"
        elif score >= 50:
            priority = "Priority 2"
        elif score >= 25:
            priority = "Priority 3"
        else:
            priority = "Priority 4"
        reasons = [
            f"patch risk score {score}",
            f"compliance score {compliance.get('compliance_score', 0)}",
        ]
        if critical_missing:
            reasons.append(f"{critical_missing} missing critical update(s)")
        if critical_business:
            reasons.append("critical business workload")
        if not ownership:
            reasons.append("ownership coverage missing")
        return {
            "priority": priority,
            "rationale": "; ".join(reasons) + ".",
            "recommended_action": (
                "Review patch evidence and schedule remediation through the approved change process; no action is executed by this platform."
            ),
        }
